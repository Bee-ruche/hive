#!/usr/bin/env python3
"""Bee's judge of the third kind, « relay »: a program is run in two phases, and the second sees nothing of the
first but the message it left (docs/relay-judge.md).

  relay.py --tip TREE --candidate TREE [--task-file PATH …] --budget SECONDS [--tip-itself] [--workdir DIR]
           [--json FILE] [--keep]
  relay.py --tip TREE --image-only

Exit code: 0 correct, 1 refused (the candidate's doing), 2 failure to judge (the machine's, the project's or the
hive's own).

What is judged. A project of this kind holds DATA (one fixed file) and a PROGRAM (source files, the only paths a
candidate may change). The program is built, then run in two phases, each in a container of its own:
  encode   sees the data and leaves a MESSAGE;
  decode   sees that message, and nothing else the first phase saw or wrote, and must leave the data again.
The measure is exact: total_bytes = the message's bytes + the program's bytes, where the program is the one file the
build leaves (/out/run), read by the host: the very bytes both phases then run, and no others. A compressor and its
decompressor are one such program; so is anything whose worth is « how little must be handed over for the rest to
be rebuilt ».

Who holds what. This file, the isolation (container.py), the safe reading (reading.py), the launcher that reads the
kernel's own clock (chrono.c) and the gate that shuts a program off from the system's calls (gate.c) are the hive's. The project's part is at ITS TIP,
under paths a candidate cannot change: a manifest that is data (bee/relay/project.json), a build script and whatever
that script needs beside the program (the skeleton), and the data, or its address and fingerprint. Nothing of the tip
and nothing of the candidate runs on the host: the build and both phases run in containers without network.

The rules (docs/relay-judge.md):
  R1  a phase runs in a container whose image holds NOTHING (no system, no library, no text), on a memory file system
      made for that phase alone, which holds its own copies of the launcher, the gate, the program and the one file
      the phase reads, and is gone when the phase ends: no folder of the host is ever given to two containers. The
      decode phase's one file is the message, as bytes the host read and wrote again;
  R2  what is counted is what runs: the built program's every byte, and a phase's container holds that file and no
      other of the candidate's; a candidate's tree is the tip's everywhere but under the manifest's program paths, and
      a build is given those paths and the tip's skeleton, never the data;
  R3  the figure repeats: the tip and the candidate each encode twice, in containers of their own, and each one's two
      messages are the same bytes; the tip decodes once and the candidate twice, and each decoding is the data;
  R4  a phase is one process, which is native code and is taken for no more: once the gate has opened its two files
      it can read and write the descriptors it holds, use its own memory, and end; every other system call is refused
      before it is carried out (gate.c). Its processor time and its memory are bounded from outside it.
"""

import argparse
import contextlib
import hashlib
import http.client
import io
import json
import math
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import traceback
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import container  # noqa: E402
from reading import JudgeError, MachineFailure, Refusal, clean, log, read_output  # noqa: E402
# The reading of trees as bytes, the bounded folders and what a build's outcome means are the second kind's own
# functions, used as they are: one copy to keep right.
from reference import (GRACE, IMAGES, OVERHEAD, PATH, bounded_folder, keep_file, launch, left, megabytes,  # noqa: E402
                       paths, regular_files, same_bytes, snapshot, whole, within)

MANIFEST = "bee/relay/project.json"
BUILD = "bee/relay/build"
MANIFEST_BYTES = 256 * 1024
# Every number of the manifest lies between a floor and a cap of the kind's own: (floor, cap).
NUMBERS = {"build_seconds": (5, 900), "build_processes": (8, 256), "encode_seconds": (1, 900), "decode_seconds": (1, 900),
           "memory_mb": (64, 8192), "output_mb": (1, 1024), "program_bytes": (1, 2 << 20), "program_files": (1, 256)}
DATA_BYTES = 200 << 20       # the data, and what is fetched to get it: below reading.py's bound on one file
MESSAGE_ROOM = 1 << 20       # a message may weigh the data's bytes plus this: more is no message
SHA256 = re.compile(r"[0-9a-f]{64}")
# No credentials, no query, no port. http is taken as https is: what is fetched is held to the manifest's fingerprint, and nothing is sent.
URL = re.compile(r"https?://[a-z0-9][a-z0-9.-]{0,200}/[A-Za-z0-9._~/-]{1,300}")
MEMBER = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}")
DATA_FROM_TREE, DATA_FROM_URL = {"path", "bytes", "sha256"}, {"url", "fetched_bytes", "fetched_sha256", "member", "bytes", "sha256"}
FETCH_SECONDS = 600          # the image step's one download
DATA_SECONDS = 60            # counted in a judgement's worst case for the host's own reading and comparing of the data
LAUNCHER_SECONDS = 60        # the launcher's and the gate's own build: two small files of C
DEPTH = 32                   # folders a candidate's tree may nest: deeper is no tree the judge reads
REAPER = 15                  # seconds the launcher's own clock waits, for a build, beyond the gate's (which ends the whole build)
HERE = os.path.dirname(os.path.abspath(__file__))
GATE_SOURCE = os.path.join(HERE, "gate.c")  # the kind's own: what shuts a phase's program off from the system's calls
# The image a phase runs in: nothing but the link the hive's mounts go through (container.LINK). Its name says what
# it is made of: another content would be another name.
BARE = "bee-relay-bare:1"
PHASES = {"encode": ("data", "message"), "decode": ("message", "data")}  # phase: (the file it is given, the file it leaves)
STATE = {}                   # what the report says of a judgement that stops: the step


class TipFault(JudgeError):
    """A failure to judge that is the TIP's own doing: its build, one of its phases, its two encodings that differ,
    its decoding that does not give the data back. Still a 2 (the candidate is not judged), and said as such in the
    reason (« the tip's own doing ») and in the report (`"fault": "tip"`), so that a report can be searched for it."""


def wall_of(seconds):
    """The clock a phase is stopped at, for a bound of `seconds` of processor time: half as much again, so that a
    machine that is merely busy does not stop a program that keeps its bound."""
    return seconds + seconds // 2 + 5


def tip_bound(seconds):
    """The processor time the TIP's own program is given: a quarter more than a candidate's. A program accepted
    within the bound stays the tip's on a machine a quarter slower; beyond that the machine is what failed."""
    return seconds + seconds // 4


# ---------------------------------------------------------------- the manifest: data, every field checked

def check_manifest(raw):
    """The manifest as the kind uses it. Anything else than the fields below, in the shapes below: a failure to judge."""
    if not isinstance(raw, dict) or set(raw) != {"image", "data", "skeleton", "program", *NUMBERS}:
        raise JudgeError("the manifest: exactly the fields image, data, skeleton, program, " + ", ".join(sorted(NUMBERS)))
    if not isinstance(raw["image"], str) or raw["image"] not in IMAGES:
        raise JudgeError("the manifest's image: the name of an image the hive holds (" + ", ".join(sorted(IMAGES)) + ")")
    manifest = {"image": raw["image"], "skeleton": paths(raw["skeleton"], "skeleton"), "program": paths(raw["program"], "program")}
    for name, bounds in NUMBERS.items():
        manifest[name] = whole(raw[name], bounds, name)
    if not any(BUILD == p or BUILD.startswith(p + "/") for p in manifest["skeleton"]):
        raise JudgeError(f"the manifest's skeleton must hold {BUILD}")
    for path in manifest["program"]:
        # The program is the candidate's: never a path the skeleton is read from, never the project's own tooling or
        # its hive settings, never the manifest's own folder.
        if within(path, manifest["skeleton"]) or path.split("/")[0] in ("bee", "hive") or within(path, manifest["program"][:manifest["program"].index(path)]):
            raise JudgeError(f"the manifest's program: {path} is also the project's own, or listed under another")
    data = raw["data"]
    if not isinstance(data, dict) or set(data) not in (DATA_FROM_TREE, DATA_FROM_URL):
        raise JudgeError("the manifest's data: either path, bytes, sha256 (a file of the tip), or url, fetched_bytes, "
                         "fetched_sha256, member, bytes, sha256 (fetched once, at the image step)")
    checked = {"bytes": whole(data["bytes"], (1, DATA_BYTES), "data: bytes")}
    for key in ("sha256", "fetched_sha256"):
        if key in data:
            if not isinstance(data[key], str) or not SHA256.fullmatch(data[key]):
                raise JudgeError(f"the manifest's data: {key}: 64 hexadecimal digits")
            if set(data[key]) == {"0"}:  # as a workflow's forty zeros name no commit
                raise JudgeError(f"the manifest's data: {key}: sixty-four zeros name no data (the project has not said which data it is judged on)")
            checked[key] = data[key]
    if "path" in data:
        if not isinstance(data["path"], str) or not PATH.fullmatch(data["path"]):
            raise JudgeError("the manifest's data: path: a plain relative path")
        # The data is given to the encode phase alone: never to a build, which reads the skeleton and the program.
        if within(data["path"], manifest["skeleton"] + manifest["program"]):
            raise JudgeError("the manifest's data: its path lies in the skeleton or in the program: a build would be given the data")
        checked["path"] = data["path"]
    else:
        if not isinstance(data["url"], str) or not URL.fullmatch(data["url"]):
            raise JudgeError("the manifest's data: url: http or https, a host and a plain path, nothing else")
        if data["member"] is not None and (not isinstance(data["member"], str) or not MEMBER.fullmatch(data["member"])):
            raise JudgeError("the manifest's data: member: null (what is fetched is the data), or a plain name in the zip archive fetched")
        checked.update(url=data["url"], member=data["member"], fetched_bytes=whole(data["fetched_bytes"], (1, DATA_BYTES), "data: fetched_bytes"))
    manifest["data"] = checked
    return manifest


def budget(manifest):
    """The worst case of a candidate's whole judgement, in seconds: every container at its clock. The launcher's
    build and two more (the tip's, the candidate's), four encodings (two each) and three decodings (the tip's one,
    the candidate's two), and the host's own work on the data."""
    builds = LAUNCHER_SECONDS + OVERHEAD + 2 * (wall_of(manifest["build_seconds"]) + REAPER + OVERHEAD)
    encodings = 4 * (wall_of(manifest["encode_seconds"]) + OVERHEAD)
    decodings = 3 * (wall_of(manifest["decode_seconds"]) + OVERHEAD)
    return builds + encodings + decodings + DATA_SECONDS


def read_manifest(tip):
    try:
        data = read_output(tip, MANIFEST, MANIFEST_BYTES)
    except (Refusal, OSError) as error:
        raise JudgeError(f"the project's manifest ({MANIFEST}) cannot be read: {clean(str(error), 200)}") from None
    if data is None:
        raise JudgeError(f"the project's tip holds no manifest ({MANIFEST})")
    try:
        return check_manifest(json.loads(data.decode("utf-8")))
    except (ValueError, RecursionError) as error:
        raise JudgeError(f"the project's manifest is not JSON: {clean(str(error), 200)}") from None


# ---------------------------------------------------------------- trees on the host: read as bytes, nothing followed

def under(path, roots):
    return any(path == root or path.startswith(root + "/") for root in roots)


def tip_is_ready(tip, manifest):
    """What is asked of the tip whatever is judged: no repository of its own (a candidate's tree is plain files and
    could never equal it), and each program path there."""
    if os.path.lexists(os.path.join(tip, ".git")):
        raise JudgeError("the tip's tree is a repository (the project's file names a history): a project of this kind names none")
    for path in manifest["program"]:
        if not os.path.lexists(os.path.join(tip, path)):
            raise JudgeError(f"the tip does not hold the program's path {path}")


def only_the_program_differs(tip, candidate, program):
    """Refusal unless the candidate's tree is the tip's everywhere but under the program's paths. The hive integrates
    the whole tree a candidate gives: what this judge does not count must be what the project already holds."""
    try:
        ours = snapshot(tip)
    except (RecursionError, OSError) as error:
        raise JudgeError(f"the tip's tree cannot be read: {clean(str(error), 200)}") from None
    try:
        theirs = snapshot(candidate)
    except (JudgeError, RecursionError, OSError):  # more entries, or deeper, than the judge reads: the candidate's own tree
        raise Refusal("the candidate's tree holds too many entries, or is nested too deep, to be read") from None
    if any(relative.count("/") >= DEPTH for relative in theirs):
        raise Refusal(f"the candidate's tree is nested deeper than {DEPTH} folders")
    for seen in (ours, theirs):
        for relative in [r for r in seen if under(r, program)]:
            del seen[relative]
    if ours != theirs:
        raise Refusal("the candidate changes something else than the program's files")
    try:
        for relative, what in ours.items():
            if what[0] == "file" and not same_bytes(os.path.join(tip, relative), os.path.join(candidate, relative)):
                raise Refusal("the candidate changes something else than the program's files")
    except OSError as error:  # the trees are the base's own writing: one that cannot be read is no candidate's doing
        raise JudgeError(f"a tree the judge was given cannot be read: {clean(str(error), 200)}") from None


def program_files(tree, manifest, blame):
    """The program's files in a tree: [(relative path, bytes)], sorted. Plain files under plain folders, plain names,
    within the manifest's count and weight; anything else is `blame`'s."""
    found = []
    try:
        for relative in manifest["program"]:
            regular_files(tree, relative, found)
    except (OSError, ValueError) as error:
        raise blame(f"the program: a path that is not a plain file or folder ({clean(str(error), 200)})") from None
    if len(found) > manifest["program_files"]:
        raise blame(f"the program holds {len(found)} files, the project's bound is {manifest['program_files']}")
    files, total = [], 0
    for relative, _ in sorted(found):
        if not PATH.fullmatch(relative):
            raise blame("the program: a file's path is not a plain name")
        try:
            data = read_output(tree, relative, max(0, manifest["program_bytes"] - total))
        except Refusal:
            raise blame(f"the program's files weigh more than the project's bound ({manifest['program_bytes']} bytes), or one is no plain file") from None
        if data is None:
            raise blame(f"the program: {relative} is missing")
        total += len(data)
        files.append((relative, data))
    return files


def copy_skeleton(tip, manifest, target):
    """The tip's skeleton written under target: what a build is given beside the program, whatever is built."""
    found = []
    try:
        for relative in manifest["skeleton"]:
            regular_files(tip, relative, found)
        for relative, executable in found:
            data = read_output(tip, relative, 64 << 20)
            if data is None:
                raise ValueError(f"{relative} is missing")
            keep_file(os.path.dirname(os.path.join(target, relative)), os.path.basename(relative), data, executable)
    except (OSError, ValueError, Refusal) as error:
        raise JudgeError(f"the tip's skeleton: {clean(str(error), 200)}") from None


def sources_of(tip, manifest, files, target):
    """What one build is given, and nothing else: the tip's skeleton and one program's files, readable by the
    container's user, with fixed times and no mode of the candidate's own (a file's path and bytes are all it brings)."""
    copy_skeleton(tip, manifest, target)
    for relative, data in files:
        keep_file(os.path.dirname(os.path.join(target, relative)), os.path.basename(relative), data)
    for folder, _, _ in os.walk(target):
        os.chmod(folder, 0o755)
    container.fixed_times(target)
    return target


# ---------------------------------------------------------------- the data: a file of the tip, or fetched once and kept

def checked(blob, size, fingerprint, what):
    if len(blob) != size or hashlib.sha256(blob).hexdigest() != fingerprint:
        raise JudgeError(f"{what}: not the {size} bytes whose SHA-256 the manifest gives ({len(blob)} bytes, {hashlib.sha256(blob).hexdigest()})")
    return blob


def docker(*words, limit=600, stdin=None):
    try:
        return subprocess.run(["docker", *words], capture_output=True, input=stdin, timeout=limit)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MachineFailure(f"failure of the judge's machine: docker {words[0]}: {clean(str(error), 200)}") from None


def data_label(data):
    """The name the fetched data is kept under, in the machine's own Docker: an image that holds one file."""
    return "bee-relay-data:" + data["sha256"][:32]


def fetch(data):
    """The image step's one download: the bytes at the manifest's address, held to its size and fingerprint, then the
    data itself (what was fetched, or one member of that zip archive), held to its own."""
    end, blocks, size = time.monotonic() + FETCH_SECONDS, [], 0
    try:
        with urllib.request.urlopen(data["url"], timeout=60) as answer:
            while size <= data["fetched_bytes"]:
                block = answer.read(1 << 20)
                if not block:
                    break
                if time.monotonic() > end:
                    raise OSError(f"not fetched within {FETCH_SECONDS} s")
                blocks.append(block)
                size += len(block)
    except (OSError, ValueError, http.client.HTTPException) as error:
        raise JudgeError(f"the data could not be fetched: {clean(str(error), 300)}") from None
    fetched = checked(b"".join(blocks), data["fetched_bytes"], data["fetched_sha256"], "what was fetched")
    if data["member"] is not None:
        try:
            with zipfile.ZipFile(io.BytesIO(fetched)) as archive, archive.open(data["member"]) as member:
                fetched = member.read(data["bytes"] + 1)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, RuntimeError) as error:
            raise JudgeError(f"the archive fetched does not hold the data: {clean(str(error), 300)}") from None
    return checked(fetched, data["bytes"], data["sha256"], "the data fetched")


def keep_data(data, blob):
    """The data kept as an image of one file, made without network from a folder that holds it."""
    folder = tempfile.mkdtemp(prefix="bee-data-")
    try:
        with open(os.path.join(folder, "data"), "wb") as f:
            f.write(blob)
        with open(os.path.join(folder, "Dockerfile"), "w", encoding="ascii") as f:
            f.write("FROM scratch\nCOPY data /data\n")
        made = docker("build", "-q", "--network", "none", "-t", data_label(data), folder)
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if made.returncode != 0:
        raise JudgeError("the data could not be kept as an image: " + clean(made.stderr, 600))


def kept_data(data):
    """The data as the image step kept it, or None: read out of its image as bytes, and held to its fingerprint again."""
    label = data_label(data)
    if docker("image", "inspect", label).returncode != 0:
        return None
    made = docker("create", label, "/data")
    name = made.stdout.decode("ascii", "replace").strip()
    if made.returncode != 0 or not re.fullmatch(r"[0-9a-f]{12,64}", name):
        raise MachineFailure("failure of the judge's machine: the image that holds the data gives no container")
    try:
        archive = docker("cp", f"{name}:/data", "-")
    finally:
        docker("rm", "-f", name)
    try:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as tar:
            member = tar.next()
            blob = tar.extractfile(member).read(data["bytes"] + 1) if member is not None and member.isreg() else None
    except (tarfile.TarError, OSError, AttributeError):
        blob = None
    if archive.returncode != 0 or blob is None:
        raise MachineFailure("failure of the judge's machine: the image that holds the data could not be read")
    return checked(blob, data["bytes"], data["sha256"], "the data kept at the image step")


def the_data(tip, manifest):
    """The data of a judgement: the tip's own file, or what the image step fetched; never fetched while judging."""
    data = manifest["data"]
    if "path" in data:
        try:
            blob = read_output(tip, data["path"], data["bytes"])
        except (Refusal, OSError) as error:
            raise JudgeError(f"the project's data ({data['path']}): {clean(str(error), 200)}") from None
        if blob is None:
            raise JudgeError(f"the project's tip holds no data ({data['path']})")
        return checked(blob, data["bytes"], data["sha256"], "the tip's data")
    blob = kept_data(data)
    if blob is None:
        raise JudgeError("the project's data is fetched at the image step (--image-only), which has not run on this machine")
    return blob


def image_of(manifest):
    label = container.build_image(IMAGES[manifest["image"]], os.environ.get("BEE_JUDGE_NETWORK"))
    return container.image_id(label)


def bare_image():
    """The image every phase runs in: one link and nothing else (the link to the root that the hive's mounts go
    through). Made here, without network, from an archive of that one entry. A program finds no file of any system
    there, no library and no text: it brings all it needs in the one file that is counted (it is linked statically),
    and what it did not bring does not exist."""
    if docker("image", "inspect", BARE).returncode != 0:
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as tar:
            link = tarfile.TarInfo(container.LINK.strip("/"))
            link.type, link.linkname, link.mode = tarfile.SYMTYPE, "/", 0o777
            tar.addfile(link)
        made = docker("import", "-", BARE, stdin=archive.getvalue())
        if made.returncode != 0:
            raise MachineFailure("failure of the judge's machine: the image the phases run in could not be made")
    return container.image_id(BARE)


def launcher_of(docker_, work):
    """What stands around a program in a container: two programs of the hive, never a line of the project's or of a
    candidate's, built in the judge's image and linked statically (a phase's container holds no library). `chrono`
    (chrono.c) starts a command and reads its times from the kernel; `gate` (gate.c) opens a phase's two files, shuts
    the system's calls and starts the program. Returns {name: bytes}: each container is given copies of its own."""
    source = os.path.join(work, "launcher-source")
    for name, path in (("chrono.c", os.path.join(HERE, "chrono.c")), ("gate.c", GATE_SOURCE)):
        with open(path, "rb") as f:
            keep_file(source, name, f.read())
    compiler = "cc -O2 -std=gnu99 -Wall -Wextra -static"
    command = ["sh", "-c", f"{compiler} /source/chrono.c -o /output/chrono && {compiler} /source/gate.c -o /output/gate"]
    built = {}
    with bounded_folder(os.path.join(work, "launcher-out"), 16) as out:
        launch(docker_, command, [(source, "/source", True), (out, "/output", False)], 64, LAUNCHER_SECONDS, JudgeError, "the launcher's build")
        for name in ("chrono", "gate"):
            built[name] = left(out, name, 16 << 20, JudgeError, f"the launcher's build: /output/{name}")
            if not built[name]:
                raise JudgeError(f"the launcher's build left no /output/{name}")
    return built


def prepare(tip):
    """The image step: the image the manifest names, and the data when the manifest gives its address. The one step
    with network, before any candidate's code is on the machine."""
    manifest = read_manifest(tip)
    image = image_of(manifest)
    bare_image()
    data = manifest["data"]
    if "url" in data and kept_data(data) is None:
        log("fetching the project's data (the only download; held to the manifest's SHA-256)")
        keep_data(data, fetch(data))
        if kept_data(data) is None:
            raise JudgeError("the data was fetched and could not be kept")
    return image


# ---------------------------------------------------------------- containers: what each outcome means is said here

def measured(ran, token, label, blame, what):
    """The launcher's one line for the command it ran (chrono.c: times and memory read by the kernel, under a token
    the command never saw). Anything else is the judge's own failure: the command cannot write there. One case
    aside: a container that ended with status 137 and no line, which Docker's own record says the kernel ended for
    its memory (`oom_killed`, which container.Docker.launch hands back from that record): a host that ends a
    container's whole group when it passes its memory ended the launcher with it, and that is `blame`'s. A 137
    without that record (the host short of memory, Docker restarted, a run cancelled) is the machine's."""
    lines = [line for line in ran.stdout.decode("utf-8", "replace").splitlines() if line.strip()]
    try:
        m = json.loads(lines[0]) if ran.returncode == 0 and len(lines) == 1 else None
    except ValueError:
        m = None
    numbers = ("code", "signal", "user_s", "system_s", "wall_s", "maxrss_kb")
    if not isinstance(m, dict) or m.get("token") != token or m.get("label") != label \
            or any(type(m.get(key)) not in (int, float) for key in numbers):
        if ran.returncode == 137 and not lines and getattr(ran, "oom_killed", False) is True:
            raise blame(f"{what}: its container was ended by the kernel for its memory, the judge's launcher with it")
        raise JudgeError(f"{what}: the judge's launcher gave no measurement (its code: {ran.returncode})")
    return m


def outcome(m, cpu_most, wall, blame, what, said=b""):
    """What a measurement means, of a phase or of a build. Past its processor time, ended by a signal, or a status
    that is not 0: `blame`'s (Refusal: the candidate's doing; JudgeError: the tip's). Stopped by the clock while it
    had NOT used its processor time: behind the gate a phase has no call that waits and no signal that stops it, so
    the machine did not give it a processor; a build may also wait on its own processes. Neither is held against
    anyone: a failure to judge, after which the hive asks about the tip itself."""
    cpu, said = m["user_s"] + m["system_s"], " ".join(clean(said, 400).split())  # (what the program said: one line of it)
    if m["signal"] == signal.SIGKILL and m["wall_s"] >= wall - 1:
        if cpu > cpu_most:
            raise blame(f"{what}: stopped after {cpu:.1f} s of processor time; its bound is {cpu_most} s")
        raise JudgeError(f"{what}: stopped by the clock at {wall} s with {cpu:.1f} s of processor time used, within its bound of "
                         f"{cpu_most} s: the machine gave it no processor, or it waits for something; the judge cannot say which")
    if m["signal"]:
        killed = " (killed: past its memory bound, most likely)" if m["signal"] == signal.SIGKILL else ""
        raise blame(f"{what}: ended by signal {m['signal']}{killed}. {said}")
    if m["code"]:
        raise blame(f"{what}: exit status {m['code']}. {said}")
    if cpu > cpu_most:
        raise blame(f"{what}: took {cpu:.1f} s of processor time; its bound is {cpu_most} s")


def how_it_differs(back, data):
    if len(back) != len(data):
        return f"{len(back)} bytes where the data holds {len(data)}"
    at = next(i for i in range(0, len(data), 1 << 16) if back[i:i + (1 << 16)] != data[i:i + (1 << 16)])
    at += next(i for i, (x, y) in enumerate(zip(back[at:at + (1 << 16)], data[at:at + (1 << 16)])) if x != y)
    return f"the same length, another byte at offset {at}"


class Judgement:
    """The containers of one judgement: the image builds run in, the bare image phases run in, the manifest's
    bounds, the work folder, the launcher and the gate."""

    def __init__(self, image, manifest, work):
        memory = f"{manifest['memory_mb']}m"
        self.docker, self.bare = container.Docker(image, memory=memory), container.Docker(bare_image(), memory=memory)
        self.manifest, self.work, self.count = manifest, work, 0
        self.launcher = launcher_of(self.docker, work)

    def folder(self, name):
        self.count += 1
        return os.path.join(self.work, f"{self.count:03d}-{name}")

    def launcher_in(self, folder):
        """This container's own copy of the launcher and the gate."""
        for name, binary in sorted(self.launcher.items()):
            keep_file(folder, name, binary, executable=True)
        return folder

    def timed(self, docker_, command, mounts, processes, seconds, cpu_most, blame, what, many=False):
        """One command under the hive's launcher, alone in a container, to its end or its clock: its measurement, once
        `outcome` has let it through. `seconds` is a bound on processor time; the clock is set above it (wall_of).
        `many`: the command starts processes of its own (a build). The launcher ends its own child alone, so the gate
        stands between them (gate --build): at the clock it ends every process of the container, and the launcher,
        whose own clock waits REAPER seconds more, reads its end and all their processor time."""
        wall, token = wall_of(seconds), secrets.token_hex(16)
        if many:
            command = ["/chrono/gate", "--build", str(wall)] + command
        entry = f"{token}\n{wall + REAPER if many else wall} 0\nrun\trun\t" + "\t".join(command) + "\n"
        try:
            ran = docker_.launch(["/chrono/chrono"], mounts, pids=processes, entry=entry.encode(), timeout_seconds=wall + REAPER + GRACE)
        except MachineFailure:
            raise
        except Refusal:  # the launcher stops its command at the clock; a container that outlives both is not the command's doing
            raise JudgeError(f"{what}: its container outlived the judge's own clock ({wall} s)") from None
        m = measured(ran, token, "run", blame, what)
        outcome(m, cpu_most, wall, blame, what, ran.stderr)
        return m

    def build(self, sources, blame, what):
        """A program as the tip's own script builds it from `sources`: the bytes of /out/run, read by the host. Those
        bytes are what the program weighs and what every phase is given a copy of. The build's bound is processor
        time, all its processes together, as a phase's is."""
        launcher = self.launcher_in(self.folder("launcher"))  # (a copy of its own: no folder is given to two containers)
        container.fixed_times(launcher)
        with bounded_folder(self.folder("out"), self.manifest["output_mb"]) as out:
            self.timed(self.docker, ["/bin/sh", "/src/" + BUILD], [(launcher, "/chrono", True), (sources, "/src", True), (out, "/out", False)],
                       self.manifest["build_processes"], self.manifest["build_seconds"], self.manifest["build_seconds"], blame, what, many=True)
            binary = left(out, "run", self.manifest["output_mb"] << 20, blame, what + ": /out/run")
        if not binary:
            raise blame(what + " left no /out/run")
        return binary

    def sees(self, root):
        """What a phase's container is given, all of it on that phase's own memory file system: the launcher and the
        gate, the program, the one file it reads, a folder to write in, and the three files of /etc a container
        always has, with fixed texts."""
        return ([(os.path.join(root, name), "/" + name, name != "out") for name in ("chrono", "program", "in", "out")]
                + [(os.path.join(root, "etc", name), "/etc/" + name, True) for name in container.ETC])

    def phase(self, program, phase, given, most, seconds, cpu_most, blame, what):
        """One phase of a program (its bytes), alone in a container of its own, on a memory file system of its own:
        the gate opens /in/<name> and creates /out/<name> (PHASES), shuts the system's calls, and starts
        `/program/run <phase>` with the two as its descriptors 3 and 4. The file system holds this phase's copies of
        everything the container sees, has room for `most` bytes of output and no more, and is unmounted when the
        phase ends. Returns the bytes the phase left, read by the host, and the launcher's measurement."""
        name, wanted = PHASES[phase]
        root = self.folder("phase")
        os.mkdir(root)
        room = megabytes(most + len(given) + len(program) + sum(len(binary) for binary in self.launcher.values()))
        container.mount_point("mount", "-t", "tmpfs", "-o", f"size={room}m,nr_inodes=64,mode=0755,nosuid,nodev,uid={os.getuid()},gid={os.getgid()}",
                              "tmpfs", root)
        try:
            self.launcher_in(os.path.join(root, "chrono"))
            keep_file(os.path.join(root, "program"), "run", program, executable=True)
            keep_file(os.path.join(root, "in"), name, given)
            for file, text in container.ETC.items():
                keep_file(os.path.join(root, "etc"), file, text.encode("ascii"))
            container.open_folder(os.path.join(root, "out"))
            container.fixed_times(root)  # (access and modification times; the others are the kernel's, and the gate lets no call read any)
            m = self.timed(self.bare, ["/chrono/gate", f"/in/{name}", f"/out/{wanted}", "/program/run", phase], self.sees(root), 2,
                           seconds, cpu_most, blame, what)
            written = left(os.path.join(root, "out"), wanted, most, blame, f"{what}: /out/{wanted}")
        finally:
            container.mount_point("umount", root)
            os.rmdir(root)
        if written is None:
            raise blame(f"{what} left no /out/{wanted}")
        return written, m

    def encode(self, program, data, cpu_most, blame, what):
        return self.phase(program, "encode", data, len(data) + MESSAGE_ROOM, self.manifest["encode_seconds"], cpu_most, blame, what)

    def decode(self, program, message, size, cpu_most, blame, what):
        """The data a program gives back for a message: no more than `size` bytes and one are ever read of it."""
        return self.phase(program, "decode", message, size + 1, self.manifest["decode_seconds"], cpu_most, blame, what)


# ---------------------------------------------------------------- one judgement

def gives_back(back, size, fingerprint):
    """True if what a decoding gave back is the data, told by its length and SHA-256 alone: while a decoder runs, the
    judge holds no copy of the data, only those two (the bytes are let go, not wiped)."""
    return len(back) == size and hashlib.sha256(back).hexdigest() == fingerprint


def seconds_of(*measurements):
    return round(max(m["user_s"] + m["system_s"] for m in measurements), 2)


def judge(args, work):
    """One judgement, step by step (docs/relay-judge.md). Returns the report's figures; Refusal: code 1; JudgeError: code 2."""
    STATE["step"] = 1
    manifest = read_manifest(args.tip)
    if any(not isinstance(path, str) or not PATH.fullmatch(path.rstrip("/")) or not under(path.rstrip("/"), manifest["program"])
           for path in args.task_file or []):
        raise JudgeError("the task lists a path that is not the program's")
    needed = budget(manifest)
    if needed > args.budget:
        raise JudgeError(f"the manifest's bounds add up to {needed} s, above the {args.budget} s a judgement of this project is given")
    tip_is_ready(args.tip, manifest)

    STATE["step"] = 2  # what can be told without running anything is told first
    tip_files = program_files(args.tip, manifest, JudgeError)
    if args.tip_itself:
        files = tip_files
    else:
        only_the_program_differs(args.tip, args.candidate, manifest["program"])
        files = program_files(args.candidate, manifest, Refusal)
    data = the_data(args.tip, manifest)

    STATE["step"] = 3  # the tip's build: given the tip's skeleton and its program, and not the data
    judgement = Judgement(image_of(manifest), manifest, work)
    tip_program = judgement.build(sources_of(args.tip, manifest, tip_files, judgement.folder("tip-sources")), TipFault, "the tip's build")

    # The tip's whole figure comes first, before anything of the candidate's is built or run: a failure of the tip (TipFault)
    # is then the tip's alone, and the base may take it for that (it stops judging, and charges no candidate).
    STATE["step"] = 4  # the tip's own figure, measured in this judgement as the candidate's is
    encode_most, decode_most = manifest["encode_seconds"], manifest["decode_seconds"]
    tip_message, tip_time = judgement.encode(tip_program, data, tip_bound(encode_most), TipFault, "the tip's first encoding")
    again, tip_again = judgement.encode(tip_program, data, tip_bound(encode_most), TipFault, "the tip's second encoding")
    if again != tip_message:  # R3 holds for the tip too: a tip whose figure moved would hand the next candidate a gain it did not make
        raise TipFault(f"the tip's own two encodings of the data are not the same bytes ({len(tip_message)} and {len(again)} bytes): "
                         "the project's program does not repeat, and nothing can be measured against it")
    del again
    size, fingerprint = len(data), hashlib.sha256(data).hexdigest()
    del data  # (no copy of the data in the judge while a decoder runs: its length and fingerprint only)
    # The tip decodes once, in every judgement: a tip whose decoder stopped working (another compiler, another machine)
    # is seen at the first judgement after, not when somebody asks.
    back, back_time = judgement.decode(tip_program, tip_message, size, tip_bound(decode_most), TipFault, "the tip's decoding")
    if not gives_back(back, size, fingerprint):
        raise TipFault("the tip's own program does not give the data back: " + how_it_differs(back, the_data(args.tip, manifest)))
    del back
    tip_weight = len(tip_program)
    tip_total = len(tip_message) + tip_weight
    if args.tip_itself:  # does the machine work, and the project's own tip: that was all of it
        return {"message_bytes": len(tip_message), "program_bytes": tip_weight, "total_bytes": tip_total, "tip_total_bytes": tip_total,
                "gain_total_bytes": 0.0, "sure_total_bytes": 0, "encode_seconds": seconds_of(tip_time, tip_again), "decode_seconds": seconds_of(back_time),
                "encode_memory_kb": max(tip_time["maxrss_kb"], tip_again["maxrss_kb"]), "decode_memory_kb": back_time["maxrss_kb"], "builds": 1, "runs": 3}
    del tip_message

    STATE["step"] = 5  # the candidate's build (the tip's skeleton, its program, not the data); then R3: the same data twice
    program = judgement.build(sources_of(args.tip, manifest, files, judgement.folder("candidate-sources")), Refusal, "the candidate's build")
    data = the_data(args.tip, manifest)  # (read again, and held to its fingerprint again)
    message, first = judgement.encode(program, data, encode_most, Refusal, "the candidate's first encoding")
    again, second = judgement.encode(program, data, encode_most, Refusal, "the candidate's second encoding")
    del data
    if again != message:
        raise Refusal(f"the candidate's two encodings of the same data are not the same bytes ({len(message)} and {len(again)} bytes): "
                      "a figure that changes from one run to the next is no figure")
    del again

    STATE["step"] = 6  # R1: each decoding sees the message alone, in a container that never held the data
    times = []
    for run in ("first", "second"):
        back, m = judgement.decode(program, message, size, decode_most, Refusal, f"the candidate's {run} decoding")
        if not gives_back(back, size, fingerprint):
            raise Refusal(f"the candidate's {run} decoding does not give the data back: " + how_it_differs(back, the_data(args.tip, manifest)))
        times.append(m)
        del back

    STATE["step"] = 7
    weight = len(program)
    total = len(message) + weight
    return {"message_bytes": len(message), "program_bytes": weight, "total_bytes": total, "tip_total_bytes": tip_total,
            # (rounded DOWN to a millionth: a gain is never written larger than it is)
            "gain_total_bytes": math.floor((1.0 - total / tip_total) * 1e6) / 1e6,
            # The proof: the candidate's exact total is below the tip's, both counted here, from outside both programs, and
            # the candidate's own was the same at each of its runs. There is no noise to be beyond.
            "sure_total_bytes": 1 if total < tip_total else 0,
            "encode_seconds": seconds_of(first, second), "decode_seconds": seconds_of(*times),
            "encode_memory_kb": max(first["maxrss_kb"], second["maxrss_kb"]), "decode_memory_kb": max(m["maxrss_kb"] for m in times),
            "builds": 2, "runs": 7}


def write_report(path, report):
    """The report, whole or not at all."""
    if not path:
        return
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=folder, prefix=".relay-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(report, indent=1, sort_keys=True) + "\n")
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bee's judge of the third kind: two phases, the second with the first's message alone.")
    parser.add_argument("--tip", required=True, help="the project's tip, written out (the base's tree)")
    parser.add_argument("--candidate", help="the candidate's tree, written out")
    parser.add_argument("--task-file", action="append", help="a file the task lists (repeat)")
    parser.add_argument("--budget", type=int, default=3600, help="seconds a whole judgement of this project is given")
    parser.add_argument("--tip-itself", action="store_true", help="the commit judged is the tip's: does the machine work?")
    parser.add_argument("--workdir", help="where this judgement's folders are made")
    parser.add_argument("--json", help="where the report is written")
    parser.add_argument("--keep", action="store_true", help="keep the work folder")
    parser.add_argument("--image-only", action="store_true", help="prepare the image the tip's manifest names and the data it gives the address of, and stop")
    args = parser.parse_args(argv)
    if args.image_only:
        log("image ready: " + prepare(args.tip))
        return 0
    if not args.tip_itself and not args.candidate:
        raise JudgeError("--candidate is needed, unless --tip-itself")
    if args.workdir:
        os.makedirs(args.workdir, exist_ok=True)
    work = tempfile.mkdtemp(prefix="relay-", dir=args.workdir)
    os.chmod(work, 0o755)
    # A judgement that is told to end (a cancelled run) unmounts what it mounted and removes its folder on the way out.
    signal.signal(signal.SIGTERM, lambda number, frame: sys.exit(2))
    try:
        figures = judge(args, work)
    finally:
        if args.keep:
            log(f"work folder kept: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
    write_report(args.json, {"kind": "relay", "code": 0, **STATE, **figures})
    log(f"correct: {figures}")
    return 0


def stop(code, message, json_path, fault=None):
    """The judge stops (1 refused, 2 failure to judge): the reason on the error output, and in the report."""
    print(message, file=sys.stderr)
    try:
        write_report(json_path, {"kind": "relay", "code": code, "reason": message, **({"fault": fault} if fault else {}), **STATE})
    except (OSError, ValueError):
        pass
    return code


if __name__ == "__main__":
    where = next((sys.argv[i + 1] for i, word in enumerate(sys.argv[:-1]) if word == "--json"), None)
    try:
        sys.exit(main())
    except Refusal as refusal:
        sys.exit(stop(1, f"judge: REFUSED: {clean(str(refusal), 2000)}", where))
    except TipFault as error:
        sys.exit(stop(2, f"judge: failure to judge, the tip's own doing (not the candidate's): {clean(str(error), 2000)}", where, "tip"))
    except JudgeError as error:
        sys.exit(stop(2, f"judge: failure to judge: {clean(str(error), 2000)}", where))
    except Exception:  # noqa: BLE001 — a defect of the judge itself: never a success, never a raw trace
        sys.exit(stop(2, "judge: internal error: " + clean(traceback.format_exc(), 3000), where))
