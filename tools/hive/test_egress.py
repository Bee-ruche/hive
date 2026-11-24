#!/usr/bin/env python3
"""Tests of the local bee's network gate (tools/hive/egress.py): every rule it holds, each shown by a request it
refuses: other methods and plain HTTP, other hosts, other ports, IP literals, the tricks of a CONNECT target, a head
of the wrong form, too long or too slow, a second request behind the first, DNS answers pointing inside the machine,
too many tunnels; and what it lets through: one tunnel to the address github.com resolves to, which it copies without
reading. The live tests run the gate on the loopback with real sockets; the network beyond it is stood in for by a
resolver and a dialer of the tests' own, so no test reaches outside the machine.

Standard library only, no network. `python3 tools/hive/test_egress.py`
"""

import ipaddress
import os
import random
import re
import socket
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import egress  # noqa: E402

GITHUB = "140.82.112.3"  # one of GitHub's addresses: global, so the gate accepts it as an answer
ALLOWED = b"CONNECT github.com:443 HTTP/1.1\r\nHost: github.com:443\r\nUser-Agent: git/2.43.0\r\n\r\n"
WAIT = 5
# Every line the gate may log: a fixed word, then the client's address.
LOG_LINE = re.compile(r"egress: (?:tunnel|ended (?:idle|closed|broken)|refused (?:" + "|".join(
    re.escape(reason) for reason in egress.STATUS) + r")) [0-9a-f.:]+\Z")


def connect_line(target, version=b"HTTP/1.1"):
    return b"CONNECT " + target + b" " + version


def reason_of(head):
    """The word of the gate's refusal for a head, or None if it lets it through."""
    try:
        egress.decide(head)
    except egress.Refused as refusal:
        return refusal.reason
    return None


class TestTarget(unittest.TestCase):
    """The request line: CONNECT to github.com:443, compared as bytes, and nothing else."""

    def test_the_one_target_allowed(self):
        self.assertEqual(egress.decide(connect_line(b"github.com:443")), ("github.com", 443))
        self.assertEqual(egress.decide(connect_line(b"github.com:443", b"HTTP/1.0")), ("github.com", 443))
        self.assertEqual(egress.decide(ALLOWED[:-4]), ("github.com", 443))

    def assertRefused(self, targets, reason):
        for target in targets:
            with self.subTest(target=target):
                self.assertEqual(reason_of(connect_line(target)), reason)

    def test_other_hosts(self):
        self.assertRefused([b"example.com:443", b"api.github.com:443", b"gist.github.com:443",
                            b"raw.githubusercontent.com:443", b"github.com.example.com:443", b"evilgithub.com:443",
                            b"githubXcom:443", b"github.co:443", b"localhost:443", b"hive-egress:443"], "target")

    def test_other_ports(self):
        self.assertRefused([b"github.com:22", b"github.com:80", b"github.com:8443", b"github.com:0443",
                            b"github.com:4430", b"github.com:+443", b"github.com:443:443", b"github.com:",
                            b"github.com", b"github.com:65979", b"github.com:https"], "target")

    def test_ip_literals(self):
        self.assertRefused([GITHUB.encode() + b":443", b"127.0.0.1:443", b"[::1]:443", b"[::ffff:140.82.112.3]:443",
                            b"2354212867:443", b"0x8c.0x52.0x70.0x03:443", b"0214.0122.0160.03:443",
                            b"169.254.169.254:443", b"[2606:50c0:8000::153]:443"], "target")

    def test_connect_tricks(self):
        self.assertRefused([b"user@github.com:443", b"github.com@example.com:443", b"github.com:443@example.com:443",
                            b"github.com.:443", b"GitHub.com:443", b"GITHUB.COM:443", b"github%2ecom:443",
                            b"github.com%3a443", b"https://github.com:443", b"https://github.com:443/",
                            b"//github.com:443", b"github.com:443/", b"github.com:443#", b"github.com:443?x",
                            b"github.com:443,example.com:443", b"github.com\\@example.com:443"], "target")

    def test_the_request_line_form(self):
        for line in [b"CONNECT  github.com:443 HTTP/1.1", b"CONNECT github.com:443  HTTP/1.1",
                     b"CONNECT github.com:443", b"CONNECT github.com:443 HTTP/2.0",
                     b"CONNECT github.com:443 HTTP/1.1 ", b"CONNECT github.com:443 http/1.1",
                     b"CONNECT github.com:443 HTTP/1.1 example.com:443", b"CONNECT github.com:443 HTTP/1.10",
                     b"CONNECT github.com:443\tHTTP/1.1", b"CONNECT " + "github.com:443".encode("utf-16-le") + b" HTTP/1.1",
                     b"CONNECT github.com:443\xa0HTTP/1.1", b"CONNECT "]:
            with self.subTest(line=line):
                self.assertEqual(reason_of(line), "head")

    def test_other_methods_and_plain_http(self):
        for line in [b"GET http://github.com/ HTTP/1.1", b"GET / HTTP/1.1", b"POST http://github.com:443/ HTTP/1.1",
                     b"connect github.com:443 HTTP/1.1", b"Connect github.com:443 HTTP/1.1",
                     b" CONNECT github.com:443 HTTP/1.1", b"CONNECTgithub.com:443 HTTP/1.1", b"OPTIONS * HTTP/1.1",
                     b"CONNECT\tgithub.com:443 HTTP/1.1", b"PRI * HTTP/2.0", b"\x16\x03\x01\x02", b""]:
            with self.subTest(line=line):
                self.assertEqual(reason_of(line), "method")

    def test_line_ends_are_crlf(self):
        # A bare LF or CR, or a NUL, anywhere in the head: a parser of another reading would split it otherwise.
        for head in [b"CONNECT github.com:443 HTTP/1.1\nHost: example.com:443",
                     b"CONNECT github.com:443 HTTP/1.1\rHost: example.com:443",
                     b"CONNECT github.com:443 HTTP/1.1\r\nHost: github.com\n:443",
                     b"CONNECT github.com:443\0 HTTP/1.1", b"CONNECT github.com:443 HTTP/1.1\r\nX: a\0b"]:
            with self.subTest(head=head):
                self.assertEqual(reason_of(head), "head")

    def test_header_lines(self):
        line = connect_line(b"github.com:443")
        for header in [b" folded", b"\tfolded", b"No Colon", b"Bad Name: x", b": no name", b"X-\xc3\xa9: x",
                       b"X: caf\xc3\xa9", b"X: \x1b[31m", b"X: \x7f", b"Host"]:
            with self.subTest(header=header):
                self.assertEqual(reason_of(line + b"\r\n" + header), "header")
        # A header of the right form is ignored, whatever it names: the target is the request line's.
        self.assertEqual(egress.decide(line + b"\r\nHost: example.com:443\r\nProxy-Authorization: Basic eDp5"),
                         ("github.com", 443))

    def test_near_misses_drawn(self):
        """Targets drawn one edit away from github.com:443: every one refused, and the true one, slipped in among
        them, let through."""
        seed = int(os.environ.get("EGRESS_SEED", random.randrange(1 << 30)))
        draw = random.Random(seed)
        exact = b"github.com:443"
        visible = bytes(range(0x21, 0x7f))
        drawn = []
        for _ in range(3000):
            target = bytearray(exact)
            edit = draw.randrange(7)
            at = draw.randrange(len(target))
            if edit == 0:
                target[at:at + 1] = bytes([target[at]]).swapcase()
            elif edit == 1:
                del target[at]
            elif edit == 2:
                target.insert(at, draw.choice(visible))
            elif edit == 3:
                target[at] = draw.choice(visible)
            elif edit == 4:
                target = bytearray(b"github.com.:443")
            elif edit == 5:
                target = bytearray(b"github.com:%d" % draw.choice([p for p in range(1, 65536, 7) if p != 443]))
            else:
                target = bytearray(draw.choice([b"x.", b"user@", b"www.", b"[", b"0"])) + target
            drawn.append(bytes(target))
        drawn.insert(draw.randrange(len(drawn) + 1), exact)
        passed = [target for target in drawn if reason_of(connect_line(target)) is None]
        self.assertTrue(passed, f"seed {seed}: the true target was refused")
        self.assertEqual(set(passed), {exact}, f"seed {seed}")
        for target in drawn:
            if target != exact:
                self.assertEqual(reason_of(connect_line(target)), "target", f"seed {seed}: {target!r}")


class TestAddress(unittest.TestCase):
    """What a DNS answer may point at: a global unicast address, nothing inside a machine or a network."""

    INSIDE = ["127.0.0.1", "127.255.0.9", "10.0.0.5", "172.16.0.1", "172.17.0.1", "192.168.1.1",
              "192.168.65.254",  # Docker Desktop's host
              "169.254.169.254",  # a cloud's metadata address
              "100.64.0.1", "0.0.0.0", "255.255.255.255", "224.0.0.1", "239.255.255.250", "240.0.0.1", "198.18.0.1",
              "192.0.2.1", "::1", "::", "fe80::1", "fe80::1%eth0", "fc00::1", "fd12:3456::1", "ff02::1", "ff0e::1",
              "2001:db8::1", "::ffff:127.0.0.1", "::ffff:10.0.0.5", "::ffff:" + GITHUB, "2002:7f00:1::1",
              "2001:0:4136:e378:8000:63bf:3fff:fdd2", "64:ff9b::7f00:1", "64:ff9b::a00:5", "64:ff9b:1::a00:5",
              "github.com", "", "1.2.3", "01.2.3.4"]
    OUTSIDE = [GITHUB, "20.201.28.151", "185.199.108.133", "1.1.1.1", "2606:50c0:8000::153", "2a01:111:f400::1"]

    def test_inside_refused(self):
        for address in self.INSIDE:
            with self.subTest(address=address):
                self.assertFalse(egress.public(address))

    def test_outside_accepted(self):
        for address in self.OUTSIDE:
            with self.subTest(address=address):
                self.assertTrue(egress.public(address))

    def test_ipv4_dressed_as_ipv6_refused_whatever_python_says(self):
        """The gate's own rules for mapped, 6to4, Teredo and NAT64 addresses, on their own: even if this Python counted
        them as global, each one is refused."""
        with mock.patch.object(ipaddress.IPv6Address, "is_global", new_callable=mock.PropertyMock, return_value=True):
            self.assertTrue(egress.public("2606:50c0:8000::153"))
            for address in ["::ffff:127.0.0.1", "2002:7f00:1::1", "2001:0:4136:e378:8000:63bf:3fff:fdd2",
                            "64:ff9b::7f00:1", "64:ff9b:1::a00:5"]:
                with self.subTest(address=address):
                    self.assertFalse(egress.public(address))

    def test_multicast_refused_whatever_python_says(self):
        for kind in (ipaddress.IPv4Address, ipaddress.IPv6Address):
            with mock.patch.object(kind, "is_global", new_callable=mock.PropertyMock, return_value=True):
                for address in ["224.0.0.1", "ff0e::1"]:
                    with self.subTest(address=address):
                        self.assertFalse(egress.public(address))

    def test_the_real_resolver_on_a_name_of_the_machine(self):
        # getaddrinfo itself, without network: localhost is answered from the machine's own files.
        addresses = egress.resolve("localhost", 443)
        self.assertTrue(addresses)
        self.assertFalse(any(egress.public(address) for address in addresses))


class Upstream:
    """A stand-in for GitHub on the loopback: it records what each connection sends and echoes it back prefixed."""

    def __init__(self):
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.received = []
        self.connections = 0
        self.lock = threading.Lock()
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            with self.lock:
                self.connections += 1
            threading.Thread(target=self.echo, args=(conn,), daemon=True).start()

    def echo(self, conn):
        conn.settimeout(WAIT)
        got = b""
        try:
            while True:
                data = conn.recv(65536)
                if not data:
                    break
                got += data
                conn.sendall(b"echo:" + data)
            conn.sendall(b"bye")
        except OSError:
            pass
        finally:
            with self.lock:
                self.received.append(got)
            conn.close()

    def close(self):
        self.listener.close()


class Live(unittest.TestCase):
    """A gate on the loopback with real sockets; resolve and dial are the tests' own and record their calls."""

    answers = [GITHUB]

    def setUp(self):
        self.upstream = Upstream()
        self.resolved = []
        self.dialed = []
        self.logged = []
        self.gate = egress.Gate(resolve=self.resolve, dial=self.dial, log=self.logged.append)
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self):
        try:
            self.gate.serve(self.listener)
        except OSError:
            pass

    def tearDown(self):
        try:
            self.listener.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.listener.close()
        self.upstream.close()
        for line in self.logged:
            self.assertRegex(line, LOG_LINE)

    def resolve(self, host, port):
        self.resolved.append((host, port))
        return list(self.answers)

    def dial(self, address, port):
        """GitHub's address leads to the stand-in on the loopback; any other address is refused like a dead host."""
        self.dialed.append((address, port))
        if address == GITHUB and port == 443:
            return socket.create_connection(("127.0.0.1", self.upstream.port), timeout=WAIT)
        raise ConnectionRefusedError(address)

    def client(self):
        conn = socket.create_connection(("127.0.0.1", self.port), timeout=WAIT)
        self.addCleanup(conn.close)
        return conn

    def status(self, conn):
        """The gate's answer head, read up to its blank line."""
        data = b""
        while b"\r\n\r\n" not in data:
            got = conn.recv(1)
            if not got:
                break
            data += got
        return data.split(b"\r\n", 1)[0]

    def ask(self, request):
        """One request on a connection of its own, closed once the answer is read."""
        conn = self.client()
        conn.sendall(request)
        answer = self.status(conn)
        conn.close()
        return answer

    def read_until(self, conn, wanted):
        data = b""
        while wanted not in data:
            got = conn.recv(65536)
            if not got:
                break
            data += got
        return data

    def wait_for(self, condition):
        deadline = time.monotonic() + WAIT
        while not condition():
            if time.monotonic() > deadline:
                self.fail("not reached in time")
            time.sleep(0.01)

    def assertReachedNothing(self):
        time.sleep(0.05)
        self.assertEqual(self.resolved, [])
        self.assertEqual(self.dialed, [])
        self.assertEqual(self.upstream.connections, 0)


class TestTunnel(Live):

    def test_tunnel_carries_bytes_both_ways(self):
        conn = self.client()
        conn.sendall(ALLOWED)
        self.assertEqual(self.status(conn), b"HTTP/1.1 200 Connection established")
        conn.sendall(b"\x16\x03\x01 hello")
        self.assertEqual(self.read_until(conn, b"hello"), b"echo:\x16\x03\x01 hello")
        conn.shutdown(socket.SHUT_WR)
        self.assertEqual(self.read_until(conn, b"bye"), b"bye")  # the upstream's last word after the client's end
        self.assertEqual(self.resolved, [("github.com", 443)])
        self.assertEqual(self.dialed, [(GITHUB, 443)])  # an address, never the name again
        self.wait_for(lambda: self.upstream.received == [b"\x16\x03\x01 hello"])
        self.wait_for(lambda: "egress: ended closed 127.0.0.1" in self.logged)

    def test_a_host_header_changes_nothing(self):
        self.assertEqual(self.ask(b"CONNECT github.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n"),
                         b"HTTP/1.1 200 Connection established")
        self.assertEqual(self.resolved, [("github.com", 443)])
        self.assertEqual(self.dialed, [(GITHUB, 443)])

    def test_bytes_in_the_tunnel_are_not_read(self):
        conn = self.client()
        conn.sendall(ALLOWED)
        self.assertEqual(self.status(conn), b"HTTP/1.1 200 Connection established")
        inner = b"CONNECT example.com:443 HTTP/1.1\r\n\r\n"
        conn.sendall(inner)
        self.assertEqual(self.read_until(conn, b"\r\n\r\n"), b"echo:" + inner)
        conn.close()
        self.wait_for(lambda: self.upstream.received == [inner])
        self.assertEqual(self.dialed, [(GITHUB, 443)])

    def test_an_idle_tunnel_is_closed(self):
        with mock.patch.object(egress, "IDLE_SECONDS", 0.3):
            conn = self.client()
            conn.sendall(ALLOWED)
            self.assertEqual(self.status(conn), b"HTTP/1.1 200 Connection established")
            started = time.monotonic()
            self.assertEqual(conn.recv(10), b"")
            self.assertLess(time.monotonic() - started, WAIT - 1)
            self.wait_for(lambda: "egress: ended idle 127.0.0.1" in self.logged)

    def test_the_next_answer_is_tried_when_one_is_dead(self):
        self.answers = ["20.201.28.151", GITHUB]
        self.assertEqual(self.ask(ALLOWED), b"HTTP/1.1 200 Connection established")
        self.assertEqual(self.dialed, [("20.201.28.151", 443), (GITHUB, 443)])


class TestRefusals(Live):

    def test_another_host_reaches_nothing(self):
        for target in [b"example.com:443", b"127.0.0.1:443", b"github.com:22", b"api.github.com:443", b"github.com.:443"]:
            with self.subTest(target=target):
                self.assertEqual(self.ask(connect_line(target) + b"\r\n\r\n"), b"HTTP/1.1 403 Forbidden")
        self.assertReachedNothing()
        self.assertIn("egress: refused target 127.0.0.1", self.logged)

    def test_plain_http_reaches_nothing(self):
        self.assertEqual(self.ask(b"GET http://github.com/ HTTP/1.1\r\nHost: github.com\r\n\r\n"),
                         b"HTTP/1.1 405 Method Not Allowed")
        self.assertReachedNothing()

    def test_dns_answers_pointing_inside(self):
        for answers in [["127.0.0.1"], ["192.168.65.254"], ["169.254.169.254"], ["::1"], ["::ffff:127.0.0.1"],
                        [GITHUB, "10.0.0.5"], ["10.0.0.5", GITHUB], ["0.0.0.0"]]:
            with self.subTest(answers=answers):
                self.answers = answers
                self.assertEqual(self.ask(ALLOWED), b"HTTP/1.1 403 Forbidden")
        self.assertEqual(self.dialed, [])
        self.assertEqual(self.upstream.connections, 0)
        self.assertIn("egress: refused address 127.0.0.1", self.logged)

    def test_the_real_resolver_pointing_inside(self):
        # The real getaddrinfo, asked for a name the machine answers with its loopback.
        self.gate.resolve = lambda host, port: egress.resolve("localhost", port)
        self.assertEqual(self.ask(ALLOWED), b"HTTP/1.1 403 Forbidden")
        self.assertEqual(self.dialed, [])

    def test_no_answer(self):
        self.answers = []
        self.assertEqual(self.ask(ALLOWED), b"HTTP/1.1 502 Bad Gateway")
        self.wait_for(lambda: self.logged == ["egress: refused dns 127.0.0.1"])

        def fail(host, port):
            raise socket.gaierror(socket.EAI_NONAME, "no such name")
        self.gate.resolve = fail
        self.assertEqual(self.ask(ALLOWED), b"HTTP/1.1 502 Bad Gateway")
        self.assertEqual(self.dialed, [])
        self.assertIn("egress: refused dns 127.0.0.1", self.logged)

    def test_upstream_unreachable(self):
        self.answers = ["20.201.28.151", "185.199.108.133"]
        self.assertEqual(self.ask(ALLOWED), b"HTTP/1.1 502 Bad Gateway")
        self.assertEqual(self.dialed, [("20.201.28.151", 443), ("185.199.108.133", 443)])
        self.assertIn("egress: refused upstream 127.0.0.1", self.logged)

    def test_a_second_request_behind_the_first(self):
        self.assertEqual(self.ask(ALLOWED + b"CONNECT example.com:443 HTTP/1.1\r\n\r\n"), b"HTTP/1.1 400 Bad Request")
        self.assertEqual(self.ask(ALLOWED + b"\x16\x03\x01"), b"HTTP/1.1 400 Bad Request")
        self.assertReachedNothing()
        self.assertIn("egress: refused early-data 127.0.0.1", self.logged)

    def test_a_head_too_long(self):
        long_head = ALLOWED[:-2] + b"X-Pad: " + b"a" * egress.MAX_HEAD + b"\r\n\r\n"
        self.assertEqual(self.ask(long_head), b"HTTP/1.1 431 Request Header Fields Too Large")
        # Exactly at the bound it passes; one byte more is refused.
        line = connect_line(b"github.com:443") + b"\r\nX-Pad: "
        at_bound = line + b"a" * (egress.MAX_HEAD - len(line))
        self.assertEqual(self.ask(at_bound + b"\r\n\r\n"), b"HTTP/1.1 200 Connection established")
        self.assertEqual(self.ask(at_bound + b"a\r\n\r\n"), b"HTTP/1.1 431 Request Header Fields Too Large")
        # A head that never ends is cut at the bound, not read for ever.
        conn = self.client()
        conn.sendall(b"CONNECT github.com:443 HTTP/1.1\r\nX-Pad: " + b"a" * (egress.MAX_HEAD + 100))
        self.assertEqual(self.status(conn), b"HTTP/1.1 431 Request Header Fields Too Large")
        self.assertEqual(self.dialed, [(GITHUB, 443)])  # the one at the bound only

    def test_a_head_too_slow(self):
        with mock.patch.object(egress, "HEAD_SECONDS", 0.5):
            conn = self.client()
            started = time.monotonic()
            for piece in [b"CONNECT ", b"github.com", b":443 HTTP/1.1\r\n"]:
                conn.sendall(piece)
                time.sleep(0.2)
            # Each piece came in time; the head as a whole did not.
            self.assertEqual(self.status(conn), b"HTTP/1.1 408 Request Timeout")
            self.assertLess(time.monotonic() - started, 2)
        self.assertReachedNothing()

    def test_a_head_cut_short(self):
        conn = self.client()
        conn.sendall(b"CONNECT github.com:443 HTTP/1.1\r\n")
        conn.shutdown(socket.SHUT_WR)
        self.assertEqual(self.status(conn), b"HTTP/1.1 400 Bad Request")
        self.assertReachedNothing()

    def test_too_many_tunnels_from_one_client(self):
        with mock.patch.object(egress, "MAX_PER_CLIENT", 2):
            held = []
            for _ in range(2):
                conn = self.client()
                conn.sendall(ALLOWED)
                self.assertEqual(self.status(conn), b"HTTP/1.1 200 Connection established")
                held.append(conn)
            self.assertEqual(self.ask(ALLOWED), b"HTTP/1.1 503 Service Unavailable")
            self.assertIn("egress: refused busy 127.0.0.1", self.logged)
            self.assertEqual(self.dialed, [(GITHUB, 443)] * 2)
            # A tunnel that ends gives its place back.
            held[0].close()
            self.wait_for(lambda: self.gate.tunnels == 1)
            self.assertEqual(self.ask(ALLOWED), b"HTTP/1.1 200 Connection established")

    def test_too_many_tunnels_in_all(self):
        with mock.patch.object(egress, "MAX_TUNNELS", 1):
            conn = self.client()
            conn.sendall(ALLOWED)
            self.assertEqual(self.status(conn), b"HTTP/1.1 200 Connection established")
            self.assertEqual(self.ask(ALLOWED), b"HTTP/1.1 503 Service Unavailable")

    def test_a_refused_request_gives_its_place_back(self):
        with mock.patch.object(egress, "MAX_PER_CLIENT", 1):
            for _ in range(3):
                self.assertEqual(self.ask(b"CONNECT example.com:443 HTTP/1.1\r\n\r\n"), b"HTTP/1.1 403 Forbidden")
                self.wait_for(lambda: self.gate.tunnels == 0)
            self.assertEqual(self.ask(ALLOWED), b"HTTP/1.1 200 Connection established")

    def test_the_log_never_holds_the_request(self):
        self.ask(b"CONNECT example.com:443 HTTP/1.1\r\nX-Secret: s3cr3t\r\n\r\n")
        self.ask(b"GET http://example.org/s3cr3t HTTP/1.1\r\n\r\n")
        self.ask(b"CONNECT github.com:443 HTTP/1.1\r\nX-Secret: s3cr3t\r\nBad Name: x\r\n\r\n")
        self.wait_for(lambda: len(self.logged) == 3)
        for line in self.logged:
            self.assertNotIn("example", line)
            self.assertNotIn("s3cr3t", line)
        # tearDown checks every line against the fixed grammar.


class TestTheScript(unittest.TestCase):
    """The file as it is run: `python3 -I egress.py`, alone, standard library only."""

    def test_ports_out_of_range(self):
        for port in ["0", "65536", "-1"]:
            with self.subTest(port=port):
                with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
                    egress.main(["--port", port])

    def test_runs_isolated(self):
        with socket.create_server(("127.0.0.1", 0)) as probe:
            port = probe.getsockname()[1]
        gate = subprocess.Popen([sys.executable, "-I", str(Path(egress.__file__).resolve()), "--listen", "127.0.0.1",
                                 "--port", str(port)], stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
        try:
            self.assertEqual(gate.stderr.readline(), f"egress: listening 127.0.0.1 {port}\n".encode())
            with socket.create_connection(("127.0.0.1", port), timeout=WAIT) as conn:
                conn.sendall(b"CONNECT example.com:443 HTTP/1.1\r\n\r\n")
                self.assertEqual(conn.recv(100).split(b"\r\n")[0], b"HTTP/1.1 403 Forbidden")
            self.assertEqual(gate.stderr.readline(), b"egress: refused target 127.0.0.1\n")
        finally:
            gate.kill()
            gate.wait(WAIT)
            gate.stderr.close()


if __name__ == "__main__":
    unittest.main()
