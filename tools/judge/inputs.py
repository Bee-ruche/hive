"""Bee's common judge: inputs given to a project's harness.

An input has a side (« f », « z »…), a name, bytes, an integer passed to the harness (often the
size, or the size of the buffer to provide) and what the host expects of it (known to the plugin alone).
Each side has its own container: a harness never sees the inputs of another side (for
miniz, a decompression never sees the originals it could copy).

Format read by the harness (folder mounted on /inputs):
  list             one line per input: « <side> <name> <integer> »
  <side>/<name>    the input's bytes
"""

import collections
import os
import re
import subprocess
import sys

from reading import JudgeError

Input = collections.namedtuple("Input", "side name data size expected")
Input.__new__.__defaults__ = (None,)

NAME_ALLOWED = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,62}")  # 63 characters at most: the harnesses' « %63s »
SIDE_ALLOWED = re.compile(r"[a-z]")


def check_inputs(inputs, sides):
    names = set()
    for e in inputs:
        if e.side not in sides or not SIDE_ALLOWED.fullmatch(e.side):
            raise JudgeError(f"unknown side for {e.name!r}: {e.side!r}")
        if not NAME_ALLOWED.fullmatch(e.name) or (e.side, e.name) in names:
            raise JudgeError(f"invalid or duplicate input name: {e.name!r}")
        if not isinstance(e.data, bytes) or not isinstance(e.size, int) or e.size < 0:
            raise JudgeError(f"malformed input: {e.name!r}")
        names.add((e.side, e.name))


def write(folder, inputs, sides):
    """Writes the inputs of ONE side (already filtered); every side's subfolder exists, even empty."""
    for s in sides:
        os.makedirs(os.path.join(folder, s), exist_ok=True)
    lines = []
    for e in inputs:
        with open(os.path.join(folder, e.side, e.name), "wb") as f:
            f.write(e.data)
        lines.append(f"{e.side} {e.name} {e.size}")
    with open(os.path.join(folder, "list"), "w", encoding="ascii") as f:
        f.write("\n".join(lines) + "\n")


def perturb(rng, files, prefix=None):
    """Copy of files [(name, bytes)] with a few bytes changed at random (one per 64 KiB, at least one).

    The same shapes as the corpus, unpredictable answers: nothing can be cached from one repetition to the next."""
    result = []
    for name, d in files:
        b = bytearray(d[:prefix] if prefix else d)
        for _ in range(max(1, len(b) // 65536) if b else 0):
            b[rng.randrange(len(b))] ^= rng.randrange(1, 256)
        result.append((name, bytes(b)))
    return result


def load_corpus(tooling, generator, folder, name_prefix="k"):
    """Runs the BASE's corpus generator (python, on the host), then reads the files produced, sorted.

    Returns [(name, bytes)] with neutral names (k000, k001…): the harness does not see the original names."""
    if generator:
        r = subprocess.run([sys.executable, os.path.join(tooling, generator)], capture_output=True, text=True, cwd=tooling)
        if r.returncode != 0:
            raise JudgeError("corpus generator failed: " + r.stderr[-1000:])
    root = os.path.join(tooling, folder)
    files = []
    for path, folders, names in os.walk(root):
        folders.sort()
        for n in sorted(names):
            with open(os.path.join(path, n), "rb") as f:
                files.append((f"{name_prefix}{len(files):03d}", f.read()))
    if not files:
        raise JudgeError("empty corpus")
    return files
