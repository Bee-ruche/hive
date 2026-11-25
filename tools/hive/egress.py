#!/usr/bin/env python3
"""The local bee's network gate: an HTTP proxy that opens a tunnel to github.com:443 and to nothing else, and never
reads the bytes that pass through it.

On a volunteer's machine the hive's tool runs in a container on a Docker network created `--internal` (no route out).
This gate runs in a second container, on that network and on an ordinary one, and is the tool's only way out: git
reads `https_proxy=http://<gate>:3128` and asks for `CONNECT github.com:443`. What the gate does, rule by rule (each
one has a test in test_egress.py that fails without it):

- Only `CONNECT`: no plain HTTP, no other method, no absolute URL. The request line is exactly
  `CONNECT github.com:443 HTTP/1.1` (or 1.0): the target is compared as bytes with the one allowed, so another host,
  another port, an IP literal, a user part, a trailing dot, another case, a sub-domain or an encoded character are
  all simply not equal to it.
- A bounded head (MAX_HEAD bytes, HEAD_SECONDS in all), every line ending in CRLF, header lines of visible ASCII; the
  headers are checked for form and otherwise ignored (a `Host:` naming another site changes nothing). No byte may
  follow the head before the gate answers: a second request cannot ride behind the first.
- The gate resolves github.com itself and connects to an address, never to a name, so nothing is resolved twice.
  Every answer must be a global unicast address: one private, loopback, link-local, shared, multicast, reserved or
  unspecified answer refuses the whole request, and an IPv6 answer must lie in 2000::/3 and not be 6to4 or Teredo
  (so no IPv4-compatible, mapped or NAT64 form either). A DNS answer cannot point the tunnel at the machine,
  Docker's own host, or a cloud's metadata address.
- Once the tunnel is up the gate copies bytes both ways and reads none of them: what the client sends reaches
  github.com:443 as it is, and the gate neither checks nor needs that it is TLS. A tunnel idle for IDLE_SECONDS is
  closed, and any tunnel TUNNEL_SECONDS old. At most MAX_PER_CLIENT tunnels per client address and MAX_TUNNELS in all.
- A failing accept() or a thread that cannot start costs one connection, not the gate.
- One line per request on stderr, from a fixed vocabulary and the client's address: the request's own bytes are
  never written anywhere.

Standard library only. Run as `python3 -I egress.py [--listen ADDRESS] [--port N]`.
"""

import argparse
import ipaddress
import re
import select
import socket
import sys
import threading
import time

ALLOWED = frozenset({b"github.com:443"})
LISTEN_PORT = 3128
MAX_HEAD = 4096
HEAD_SECONDS = 10
CONNECT_SECONDS = 10
IDLE_SECONDS = 300
# A tunnel's whole life, however busy. The tool's fetches are a project's history (at most PROJECT_COMMITS commits in
# hive.py) and the owner's fork: the pilots' are tens of megabytes. Two hours carry a full gigabyte at 1.2 Mbit/s,
# far beyond any of them on the slowest line a volunteer would work on; a fetch cut short fails, and the next command
# fetches again.
TUNNEL_SECONDS = 7200
ACCEPT_PAUSE = 0.1  # after accept() fails (no file descriptor left, a connection aborted): a pause, not a busy loop
MAX_PER_CLIENT = 4
MAX_TUNNELS = 16
CHUNK = 65536

# The only IPv6 addresses a tunnel may reach: global unicast (RFC 4291), so that no change in Python's `is_global` can
# widen the rule. Everything outside it is refused whatever Python says: the IPv4-compatible `::/96` and mapped
# `::ffff:0:0/96` forms, NAT64's `64:ff9b::/96` and `64:ff9b:1::/48`, link-local, unique local, multicast.
GLOBAL_UNICAST6 = ipaddress.ip_network("2000::/3")

END_OF_HEAD = b"\r\n\r\n"
REQUEST_LINE = re.compile(rb"CONNECT ([!-~]+) HTTP/1\.[01]\Z")
# A field name of token characters, a colon, then visible ASCII, space and tab (RFC 9110); no folded line.
HEADER_LINE = re.compile(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+:[\t -~]*\Z")

# Each refusal: its status line, and the word the log says.
STATUS = {
    "method": b"405 Method Not Allowed",
    "target": b"403 Forbidden",
    "head": b"400 Bad Request",
    "header": b"400 Bad Request",
    "early-data": b"400 Bad Request",
    "too-long": b"431 Request Header Fields Too Large",
    "slow": b"408 Request Timeout",
    "address": b"403 Forbidden",
    "dns": b"502 Bad Gateway",
    "upstream": b"502 Bad Gateway",
    "busy": b"503 Service Unavailable",
    "thread": b"503 Service Unavailable",
}


class Refused(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def decide(head):
    """The (host, port) a complete head (up to and without its blank line) may reach, or Refused."""
    lines = head.split(b"\r\n")
    if any(b"\r" in line or b"\n" in line or b"\0" in line for line in lines):
        raise Refused("head")
    if not lines[0].startswith(b"CONNECT "):
        raise Refused("method")
    request = REQUEST_LINE.match(lines[0])
    if request is None:
        raise Refused("head")
    target = request.group(1)
    if target not in ALLOWED:
        raise Refused("target")
    for line in lines[1:]:
        if not HEADER_LINE.match(line):
            raise Refused("header")
    host, _, port = target.decode("ascii").rpartition(":")
    return host, int(port)


def public(address):
    """True for a global unicast address, False for anything the tunnel must never reach."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if ip.version == 6 and (ip not in GLOBAL_UNICAST6 or ip.sixtofour is not None or ip.teredo is not None):
        return False  # inside 2000::/3, 6to4 and Teredo still carry an IPv4 address that could be a private one
    return ip.is_global and not ip.is_multicast


def resolve(host, port):
    """Every address the name has, as getaddrinfo gives them, in its order."""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    return [info[4][0] for info in infos]


def dial(address, port):
    return socket.create_connection((address, port), timeout=CONNECT_SECONDS)


def read_head(client):
    """The head of the request, without its blank line; Refused if it is too long, too slow or followed by data."""
    deadline = time.monotonic() + HEAD_SECONDS
    data = b""
    while END_OF_HEAD not in data:
        if len(data) > MAX_HEAD:
            raise Refused("too-long")
        left = deadline - time.monotonic()
        if left <= 0:
            raise Refused("slow")
        client.settimeout(left)
        try:
            got = client.recv(MAX_HEAD + len(END_OF_HEAD) + 1 - len(data))
        except socket.timeout:
            raise Refused("slow")
        if not got:
            raise Refused("head")
        data += got
    head, _, rest = data.partition(END_OF_HEAD)
    if len(head) > MAX_HEAD:
        raise Refused("too-long")
    if rest:
        raise Refused("early-data")
    return head


def relay(client, upstream):
    """Copy bytes both ways until both sides have closed, until nothing moves for IDLE_SECONDS, or until the tunnel
    is TUNNEL_SECONDS old, however busy."""
    deadline = time.monotonic() + TUNNEL_SECONDS
    for one in (client, upstream):
        one.settimeout(IDLE_SECONDS)
    other = {client: upstream, upstream: client}
    open_ = [client, upstream]
    while open_:
        left = deadline - time.monotonic()
        if left <= 0:
            return "expired"
        ready, _, _ = select.select(open_, [], [], min(IDLE_SECONDS, left))
        if not ready:
            return "idle" if deadline - time.monotonic() > 0 else "expired"
        for one in ready:
            data = one.recv(CHUNK)
            if data:
                other[one].sendall(data)
            else:
                open_.remove(one)
                try:
                    other[one].shutdown(socket.SHUT_WR)
                except OSError:
                    pass
    return "closed"


class Gate:
    """The rules of one gate; resolve, dial and start are attributes so that the tests can stand in for the network
    and for a machine out of threads."""

    def __init__(self, resolve=resolve, dial=dial, log=None):
        self.resolve = resolve
        self.dial = dial
        self.start = start
        self.log = log or (lambda line: print(line, file=sys.stderr, flush=True))
        self.lock = threading.Lock()
        self.per_client = {}
        self.tunnels = 0

    def say(self, client_address, word):
        self.log(f"egress: {word} {client_address}")

    def admit(self, client_address):
        with self.lock:
            if self.tunnels >= MAX_TUNNELS or self.per_client.get(client_address, 0) >= MAX_PER_CLIENT:
                return False
            self.tunnels += 1
            self.per_client[client_address] = self.per_client.get(client_address, 0) + 1
            return True

    def leave(self, client_address):
        with self.lock:
            self.tunnels -= 1
            self.per_client[client_address] -= 1
            if not self.per_client[client_address]:
                del self.per_client[client_address]

    def open_tunnel(self, client):
        """Read the request, apply every rule, and return a connected upstream socket; Refused otherwise."""
        host, port = decide(read_head(client))
        try:
            addresses = self.resolve(host, port)
        except OSError:
            raise Refused("dns")
        if not addresses:
            raise Refused("dns")
        if not all(public(address) for address in addresses):
            raise Refused("address")
        for address in addresses:
            try:
                return self.dial(address, port)
            except OSError:
                continue
        raise Refused("upstream")

    def handle(self, client, client_address):
        try:
            try:
                upstream = self.open_tunnel(client)
            except Refused as refusal:
                self.say(client_address, f"refused {refusal.reason}")
                answer(client, STATUS[refusal.reason])
                return
            try:
                client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                self.say(client_address, "tunnel")
                self.say(client_address, f"ended {relay(client, upstream)}")
            finally:
                upstream.close()
        except OSError:
            self.say(client_address, "ended broken")
        finally:
            client.close()
            self.leave(client_address)

    def serve(self, listener):
        """Accept for ever. A failing accept() or a thread that cannot start costs one connection, never the gate;
        the loop ends only when the listener itself is closed."""
        while True:
            try:
                client, peer = listener.accept()
            except OSError:
                if listener.fileno() < 0:
                    return
                self.log("egress: accept failed")
                time.sleep(ACCEPT_PAUSE)
                continue
            client_address = peer[0]
            if not self.admit(client_address):
                self.say(client_address, "refused busy")
                answer(client, STATUS["busy"])
                client.close()
                continue
            try:
                self.start(self.handle, (client, client_address))
            except RuntimeError:  # "can't start new thread"
                self.say(client_address, "refused thread")
                answer(client, STATUS["thread"])
                client.close()
                self.leave(client_address)


def start(target, args):
    threading.Thread(target=target, args=args, daemon=True).start()


def answer(client, status):
    """Say a refusal: a few bytes into a fresh socket's buffer, which never waits on the client."""
    try:
        client.settimeout(1)
        client.sendall(b"HTTP/1.1 " + status + b"\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
    except OSError:
        pass


def listen(address, port):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    listener = socket.socket(family, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind((address, port))
    listener.listen(64)
    return listener


def main(argv=None):
    parser = argparse.ArgumentParser(description="An HTTP proxy that tunnels to github.com:443 and nowhere else.")
    parser.add_argument("--listen", default="0.0.0.0", help="the address to listen on (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=LISTEN_PORT, help=f"the port to listen on (default {LISTEN_PORT})")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("the port is between 1 and 65535")
    listener = listen(args.listen, args.port)
    print(f"egress: listening {args.listen} {args.port}", file=sys.stderr, flush=True)
    Gate().serve(listener)


if __name__ == "__main__":
    main()
