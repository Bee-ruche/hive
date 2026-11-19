"""The toy project's (rle) plugin for the Bee common judge: a model of a plugin and the meta-tests' subject.

The common judge reads a plugin from the PR's BASE, never from the PR. It sees the container's outputs
only through reading.Outputs and runs nothing the container produced. It trusts only the base (A) and
itself (here, a reference codec written in Python).
"""

import re
import subprocess
import zlib

from inputs import Input, perturb
from reading import JudgeError, Refusal

RLE_OK, RLE_INVALID, RLE_BUFFER_TOO_SMALL = 0, -1, -2


def compress(d):
    """The reference codec, byte for byte the base's rle.c (otherwise: judge badly set up)."""
    output = bytearray(len(d).to_bytes(4, "little"))

    def literals(start, end):
        while start < end:
            k = min(128, end - start)
            output.append(k - 1)
            output.extend(d[start:start + k])
            start += k

    i = start = 0
    while i < len(d):
        run = 1
        while i + run < len(d) and run < 130 and d[i + run] == d[i]:
            run += 1
        if run >= 3:
            literals(start, i)
            output += bytes([run + 125, d[i]])
            i += run
            start = i
        else:
            i += run
    literals(start, len(d))
    return bytes(output) + zlib.crc32(d).to_bytes(4, "little")


def decompress(z):
    """The reference decompression; None if the stream is invalid."""
    if len(z) < 8:
        return None
    length, i, output = int.from_bytes(z[:4], "little"), 4, bytearray()
    while i < len(z) - 4 and len(output) < length:
        c = z[i]
        i += 1
        if c < 128:
            if i + c + 1 > len(z) - 4:
                return None
            output += z[i:i + c + 1]
            i += c + 1
        else:
            if i >= len(z) - 4:
                return None
            output += bytes([z[i]]) * (c - 125)
            i += 1
    if len(output) != length or i != len(z) - 4 or zlib.crc32(bytes(output)) != int.from_bytes(z[-4:], "little"):
        return None
    return bytes(output)


class Project:
    NAME = "toy"
    PACKAGES = []                       # the common image is enough
    SOURCES = ["rle.c", "rle.h"]
    REQUIRED_SOURCES = ["rle.c", "rle.h"]
    TOOLING = ["bee/judge"]
    BASE_HEADERS = ["rle.h"]
    BUILD = "bee/judge/build.sh"
    PREFIXES = ("rle_",)
    ALLOWED = ()
    SIDES = ("f", "z")
    SCENARIOS = {"compression": "f", "decompression": "z"}
    INSTRUCTIONS = ("compression", "decompression")
    METRICS = [
        ("compression_throughput", "higher", "MB/s"),
        ("decompression_throughput", "higher", "MB/s"),
        ("ratio", "higher", "ratio"),
        ("max_memory_kb", "lower", "KB"),
    ]
    METHOD = {"max_memory_kb": "ru_maxrss of the process of the scenario « compression », read by wait4"}

    def __init__(self, options):
        self.identical = options.pop("compressed_output", "identical") == "identical"
        # A commit of the base whose rle.c joins the corpus, read from its git objects: the judge's --history-only step
        # fetches them when the project declares the commit (its history), before the PR; judging itself has no git transport.
        self.corpus_commit = options.pop("corpus_commit", None)
        if self.corpus_commit is not None and not re.fullmatch(r"[0-9a-f]{40}", self.corpus_commit):
            raise JudgeError("corpus_commit: a full commit (40 hexadecimal digits)")
        if options:
            raise JudgeError("unknown options: " + ", ".join(sorted(options)))
        self.VERIFICATION = {"compressed_output": "identical" if self.identical else "may_change"}

    # -------------------------------------------------------------- inputs

    def corpus(self, tooling):
        """A fixed corpus, written here (a real project reads it in the base's bee/corpus/)."""
        text = ("the common judge reads the outputs without believing them; " * 40).encode()
        files = [text, bytes(range(256)) * 16, b"\x00" * 5000 + b"\x01" * 3, b"ab" * 3000, bytes(300) + text]
        files += [bytes((i * 7) % 251 for i in range(n)) for n in (1, 2, 127, 128, 129, 130, 131, 4096)]
        if self.corpus_commit:
            files.append(self.git_object(tooling, f"{self.corpus_commit}:rle.c"))
        return [(f"k{i:03d}", d) for i, d in enumerate(files)]

    def git_object(self, tooling, name):
        """A git object of the base, read on the host (never fetched here): missing, a clean environment error."""
        r = subprocess.run(["git", "-C", tooling, "cat-file", "blob", name], capture_output=True, timeout=60)
        if r.returncode != 0:
            raise JudgeError(f"corpus: git object {name} missing from the base; declare its commit in the history the judge "
                             "fetches (judge.py --history-only --history)")
        self.VERIFICATION["history"] = f"{name} ({len(r.stdout)} bytes)"
        return r.stdout

    def random_inputs(self, rng):
        e = [b"", rng.randbytes(1), rng.randbytes(rng.randint(2, 300))]
        for _ in range(3):
            block = bytearray()
            while len(block) < rng.randint(1000, 60000):
                block += bytes([rng.randrange(4)]) * rng.choice([1, 2, 3, 129, 130, 131, rng.randint(1, 400)])
            e.append(bytes(block))
        e.append(rng.randbytes(rng.randint(10000, 50000)))
        return [(f"a{i:03d}", d) for i, d in enumerate(e)]

    def streams(self, rng, originals):
        """Streams made HERE by the reference codec, valid and invalid: (name, stream, buffer, original or None)."""
        result = [(f"z{i:03d}", compress(d), len(d), d) for i, (_, d) in enumerate(originals)]
        valid = [r for r in result if r[2] > 0]
        for k in range(min(10, len(valid))):
            _, z, size, _ = valid[(k * 3) % len(valid)]
            kind, name = k % 5, f"y{k:03d}"
            if kind == 0:
                result.append((name, z[:rng.randrange(1, len(z))], size, None))
            elif kind == 1:
                b = bytearray(z)
                b[rng.randrange(4, len(z))] ^= 1 << rng.randrange(8)
                result.append((name, bytes(b), size, None))
            elif kind == 2:
                result.append((name, z, size - 1, None))
            elif kind == 3:
                result.append((name, z + rng.randbytes(3), size, None))
            else:
                result.append((name, rng.randbytes(rng.randint(8, 500)), 1000, None))
        return result

    def make_inputs(self, files, streams):
        return [Input("f", name, d, len(d), d) for name, d in files] + \
               [Input("z", name, z, size, original) for name, z, size, original in streams]

    def verification(self, rng, corpus):
        files = corpus + self.random_inputs(rng)
        return self.make_inputs(files, self.streams(rng, files))

    def repetition(self, rng, corpus):
        perturbed = perturb(rng, corpus)
        return self.make_inputs(perturbed, [(name, compress(d), len(d), d) for name, d in perturbed])

    def instructions(self, rng, corpus, prefix):
        return self.repetition(rng, [(name, d[:prefix]) for name, d in corpus])

    # -------------------------------------------------------------- verification

    def compressed(self, a, b, relative, original):
        output_b = b.require("f", relative)
        if self.identical:
            if output_b != a.require("f", relative):
                raise Refusal(f"compressed output differs from the base: {relative}")
        elif decompress(output_b) != original:
            raise Refusal(f"the compressed output does not give back the original: {relative}")
        return len(output_b)

    def correct(self, a, b, e, root=""):
        """An input's rule of correctness, the same whatever the mode it passes in (verification or measurement: the
        common judge mixes verification inputs into the measured ones). Returns the bytes handled."""
        if e.side == "f":
            self.compressed(a, b, f"{root}c/{e.name}", e.data)
            return len(e.data)
        code_a, _ = a.status("z", f"{root}e/{e.name}")
        code_b, _ = b.status("z", f"{root}e/{e.name}")
        if code_a != code_b:
            raise Refusal(f"decompression of {e.name}: code {code_b}, the base gives {code_a}")
        sa, sb = a.require("z", f"{root}d/{e.name}"), b.require("z", f"{root}d/{e.name}")
        if code_a == RLE_OK:
            if sa != sb:
                raise Refusal(f"decompression of {e.name} differs from the base")
            if e.expected is not None and sa != e.expected:
                raise JudgeError(f"the base does not give back the original of {e.name}: judge badly set up")
        elif sa[:min(len(sa), len(sb))] != sb[:min(len(sa), len(sb))]:
            raise Refusal(f"decompression of {e.name} in error: bytes produced differ from the base")
        return len(sa)

    def verify(self, a, b, inputs):
        for e in inputs:
            if e.side == "f" and a.require("f", f"c/{e.name}") != compress(e.data):
                raise JudgeError(f"the base does not give the reference output for {e.name}: judge badly set up")
            self.correct(a, b, e)
        return len(inputs)

    def fixed(self, outputs, corpus):
        total = sum(len(d) for _, d in corpus)
        compressed = sum(len(outputs.require("f", f"c/{name}")) for name, _ in corpus)
        return {"ratio": total / compressed if compressed else None}

    def scenario(self, s, a, b, inputs, measurement):
        """Each output of the scenario is checked by the rule of correctness, whatever its input; the ratio is read
        again on the timed outputs (it replaces fixed()'s, read on verification)."""
        cpu = measurement["user_s"] + measurement["system_s"]
        handled = [self.correct(a, b, e, f"{s}/") for e in inputs if e.side == self.SCENARIOS[s]]
        values = {f"{s}_throughput": sum(handled) / 1e6 / cpu if cpu > 0 else None}
        if s == "compression":
            compressed = sum(len(b.require("f", f"compression/c/{e.name}")) for e in inputs if e.side == "f")
            values.update(max_memory_kb=measurement["maxrss_kb"], ratio=sum(handled) / compressed if compressed else None)
        return values, len(handled)
