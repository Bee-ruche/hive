#!/usr/bin/env python3
"""Tests of the Bee common judge (tools/judge/).

  python3 tools/judge/test_judge.py                      unit tests (without Docker)
  BEE_JUDGE_INTEGRATION=1 python3 tools/judge/test_judge.py
                                                        + meta-tests: the common judge against the toy project
                                                          (tools/judge/toy/), honest and MALICIOUS (Docker required)
  BEE_JUDGE_NETWORK=host                                the network of « docker build » (machines without Docker's bridge)

The malicious variants are transformations of rle.c's text, compiled and run only INSIDE the judge's
container. They are the tricks of minizBee's meta-tests (the fork's bee/juge/test_juge.py, which the common
judge came from), and others of the common judge's own:
  early_exit          the program stops « successfully » in the middle of the inputs
  fake_stopwatches    the code replaces clock_gettime to announce flattering times, and it is slower
  precomputed_table   the compressor works only on the inputs it knows in advance (the corpus)
  valgrind_request    the code suspends Valgrind's instruction count during its own work
  fake_summary        the code writes a fake « I refs » summary on the error output
  moved_work          rle_compress's work is done in advance in rle_bound, called just before
  plugin_of_the_pr    the PR brings its own plugin and its own harness, which accept everything: ignored
  symbolic_link       the PR's rle.c is a symbolic link (to a file of the host)
and, since the adversarial review of 28 October (flaws of a plugin's contract):
  empty_surveys       the base's build script writes an empty disassembly: no effect, the judge surveys
                      the objects itself, and the Valgrind request stays flagged
  forgotten_object    the build script does not leave the project's object in obj/: an error
  split_tokens        the assembler is formed by token pasting (a##sm): seen in the objects
  distracted_plugin   a plugin that does not read B's outputs of a scenario: an error, never an acceptance
and, since ruche-0037 (the judged code cannot tell whether it is verified or measured):
  same_conditions             B records everything it can observe of its process: the same record in every mode
  wrong_output_timed          B right when it is verified, wrong when it is timed (the base's harness tells it):
                              refused by the verification inputs mixed into the measurements
  same_counters               on the same /inputs, the same record in every mode, the process's counters included
  changing_output_timed       outputs free to differ: B gives, timed, another right output: refused
  side_without_mixing, instructions_without_mixing  a measured side with no input to mix in: an error; a count
                              without any: flagged

Without Docker, the analysis is also tested on objects of the toy project built on the host as the judge
builds them (DockerLocal; built, surveyed and analysed, never run): seeded constructs in every family and
variant (TestSeededObjects), constructs added anywhere in a judged file (TestSeededText), failing tools
(TestFailClosed).

ruche-0024: the declared history is checked against the base's ancestry (gh replaced by a stand-in), fetched within a
time budget, then read without any git transport (TestHistory); with Docker, declared_history and undeclared_history.

ruche-0037, without Docker: the harness is started the same way in every mode (TestSameConditions); inputs are renamed
and each verification input passes in a measurement, drawn from the seed, with the same output (TestShuffle); fixed times,
the harness alone in /variant, at least one repetition (TestFixedConditions).

ruche-0036: outputs frozen when their container ends, order drawn at each repetition, each scenario's CPU time, on a toy
with two scenarios per side (toy_with_four_scenarios). Without Docker, container.Docker is replaced by an emulation of
chrono and of the toy harness (EmulatedDocker, nothing is run): the order recorded is the order run, each scenario's CPU
time is chrono's, an output changed, added or removed after its freeze is refused (TestOrderAndFingerprints, TestFrozen).
With Docker, neighbor_scenarios: every scenario of B tries to read and to modify the others' outputs, before and after
its own work: the honest toy's verdict and comparisons, the order changing between repetitions.

ruche-0117: suspicious constructs ranked and counted, each detail cut (test_detail_cut_when_built,
test_suspicious_most_serious_first, test_job_report); report.py publishes the code once the report is checked, and --verify
wants the code 0 and the judged commits (test_a_refusal_needs_no_report, test_verify_requires_code_0_and_the_judged_commits,
test_verify_refuses_a_report_changed_after_it_was_published); a fixed metric read on verification alone is flagged
(test_fixed_metric_read_on_verification_alone); the identity check counts per scenario
(test_mixed_input_same_output_as_in_verification); each execution on its own tmpfs (test_each_execution_on_its_own_tmpfs),
unmounted at once (test_tmpfs_in_use_is_an_error); the judge's mounts in one order whatever order Docker draws for those of
equal depth (test_one_mount_order_whatever_docker_draws); with Docker, test_same_mounts: identical scenarios at different
positions, variant passes, repetitions and modes see the same thing, mount by mount (REST aside), and none sees what another
left in its outputs.

ruche-0136: a failure of the machine (Docker, its runtime) is an error of the environment, read on Docker's own record; a judged
code that mimics one stays a refusal (test_machine_failure_is_an_environment_error, test_judged_code_that_mimics_a_failure_stays_a_refusal,
test_judge_json_says_the_environment_error; with Docker, test_machine_failure, test_simulated_failure); where each seed came from
(test_where_each_seed_came_from, check_the_seeds); each folder of the judge at a depth of its own, in every container
(test_one_mount_order_whatever_docker_draws; with Docker, test_depths).

judge-v5: one plugin contract, in English (bee/judge/project.py); the toy project's base is tools/judge/toy/.
"""

import concurrent.futures
import contextlib
import glob
import hashlib
import io
import itertools
import json
import os
import random
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import tracemalloc
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
TOY = os.path.join(HERE, "toy")
sys.path.insert(0, HERE)
import analysis  # noqa: E402
import container  # noqa: E402
import inputs  # noqa: E402
import judge  # noqa: E402
import reading  # noqa: E402
import report  # noqa: E402
import stats  # noqa: E402

sys.path.insert(0, os.path.join(TOY, "bee", "judge"))
import project as toy_plugin  # noqa: E402

TOY_FILES = {"plugin": "project.py", "build": "build.sh", "harness": "execution.c"}


def toy_file(base, kind):
    """A toy base's plugin, build script or harness."""
    return os.path.join(base, "bee", "judge", TOY_FILES[kind])


# ------------------------------------------------------------------ unit tests

NM_A = """/s/obj/rle.o: rle_compress T 0000000000000100 0000000000000080
/s/obj/rle.o: memcpy U
/s/obj/rle.o: .LC0 r 0
"""
SECTIONS_A = """
Idx Name          Size      VMA               LMA               File off  Algn
  0 .text         00001000  0000000000000000  0000000000000000  00000040  2**4
"""
DISASSEMBLY_A = "0000000000000000 <rle_compress>:\n   0:\tendbr64\n   4:\tpush   %rbp\n"


def surveys(nm=NM_A, sections=SECTIONS_A, disassembly=DISASSEMBLY_A, objects_found=(), program=()):
    return {"symbols": nm, "sections": sections, "disassembly": disassembly, "objects": list(objects_found),
            "program": list(program)}


class TestAnalyse(unittest.TestCase):
    def test_base_against_itself(self):
        self.assertEqual(analysis.analyse(surveys(), surveys(), {}, {}, prefixes=("rle_",)), [])

    def test_prefixes_and_allowed_of_the_plugin(self):
        b = surveys(nm=NM_A + "/s/obj/rle.o: rle_aide T 0000000000000300 0000000000000010\n/s/obj/rle.o: qsort U\n")
        self.assertEqual([s["type"] for s in analysis.analyse(surveys(), b, {}, {}, prefixes=("rle_",))], ["external_call"])
        self.assertEqual(analysis.analyse(surveys(), b, {}, {}, prefixes=("rle_",), allowed_set=("qsort",)), [])
        # Without a namespace, a new global function is suspicious (it could replace another one).
        self.assertEqual(sorted(s["type"] for s in analysis.analyse(surveys(), b, {}, {}, allowed_set=("qsort",))), ["defined_symbol"])

    def test_symbol_that_replaces_the_libc(self):
        b = surveys(nm=NM_A + "/s/obj/rle.o: clock_gettime T 0000000000000300 0000000000000010\n"
                             "/s/obj/rle.o: memcmp T 0000000000000400 0000000000000010\n")
        self.assertEqual(sorted(s["type"] for s in analysis.analyse(surveys(), b, {}, {}, prefixes=("rle_",))),
                         ["defined_symbol", "forbidden_symbol"])

    def test_never_allowed_despite_prefix_or_allowed(self):
        """Adversarial review no. 2: a prefix « ge » or an entry of ALLOWED does not clear getenv."""
        b = surveys(nm=NM_A + "/s/obj/rle.o: getenv U\n/s/obj/rle.o: syscall U\n")
        types = [s["type"] for s in analysis.analyse(surveys(), b, {}, {}, prefixes=("rle_", "ge", "sy"), allowed_set=("getenv",))]
        self.assertEqual(types, ["forbidden_call", "forbidden_call"])
        a = surveys(nm=NM_A + "/s/obj/rle.o: getenv U\n")
        self.assertEqual([s["type"] for s in analysis.analyse(a, b, {}, {}, prefixes=("rle_",))], ["forbidden_call"])  # syscall alone

    def test_line_continuation(self):
        b = {"rle.c": "    __as\\\nm volatile(\"\");\n    int x = 1;\n"}
        self.assertEqual(list(analysis.text_constructs(b)), [("rle.c", "inline assembly", "__as" + "m volatile(\"\");")])
        self.assertEqual(len(analysis.analyse(surveys(), surveys(), {}, b, prefixes=("rle_",))), 1)

    def test_constructor_and_instructions(self):
        b = surveys(sections=SECTIONS_A + "  1 .init_array   00000008  0000000000000000  0000000000000000  00001140  2**3\n",
                    disassembly=DISASSEMBLY_A + "   9:\tsyscall\n  10:\trol    $0x3,%rdi\n")
        self.assertEqual(sorted(s["type"] for s in analysis.analyse(surveys(), b, {}, {}, prefixes=("rle_",))),
                         ["instruction", "instruction", "section"])

    def test_source(self):
        b = {"rle.c": "    __asm__ volatile(\"\");\n#include <time.h>\n    int ordinaire = 1;\n"}
        self.assertEqual(len(analysis.analyse(surveys(), surveys(), {}, b, prefixes=("rle_",))), 2)

    def test_mnemonics_any_word(self):
        instructions = {m: m for m in analysis.SUSPICIOUS_MNEMONICS if m[0].isalpha() and m not in NON_INSTRUCTIONS}
        instructions.update({"int": "int $0x80", "(bad)": "(bad)", ".byte": ".byte 0xf", "valgrind_preamble": "rol $0x3,%rdi"})
        suites = [()] + [(p,) for p in PREFIXES_X86] + [(p, q) for p in PREFIXES_X86 for q in PREFIXES_X86]
        lines = [f"  1f:\t{' '.join(suite + (text,))}" for text in instructions.values() for suite in suites]
        lines += ["   e:\tcall   13 <syscall+0x3>", "  13:\tlea    0x0(%rip),%rax        # 1a <int>"]
        self.assertEqual(analysis.mnemonics_found("\n".join(lines)), {m: len(suites) for m in instructions})

    def test_unreadable_bytes_make_the_analysis_incomplete(self):
        for data in (b"", b"\x7fELF", b"MZ" + bytes(100), b"\x7fELF\x02\x01\x01" + bytes(57)):
            b = surveys(objects_found=[("rle.o", data)])
            self.assertEqual([s["type"] for s in analysis.analyse(surveys(), b, {}, {}, prefixes=("rle_",))], ["incomplete_analysis"])

    def test_unreadable_a_object(self):
        a, b = surveys(objects_found=[("rle.o", b"\x7fELF")]), surveys(objects_found=[("rle.o", elf(1, [(".text", 6, b"\x90")]))])
        self.assertEqual([s["type"] for s in analysis.analyse(a, b, {}, {})], ["incomplete_analysis"])

    def test_texts_required(self):
        with self.assertRaises(TypeError):
            analysis.analyse(surveys(), surveys(), prefixes=("rle_",))

    def test_whole_files_compared(self):
        a = {"x.c": "#pragma once\nint a;\n", "y.c": "int b;\n"}
        self.assertEqual(analysis.analyse(surveys(), surveys(), a, {"x.c": "int c;\n  #pragma   once\n", "y.c": "int b;\n"}), [])
        b = {"x.c": "int a;\n", "y.c": "#pragma once\nint b;\n"}
        self.assertEqual([s["detail"][-5:] for s in analysis.analyse(surveys(), surveys(), a, b)], ["(y.c)"])
        b = {"x.c": "#pragma once\nint a;\n#pragma once\n", "y.c": "int b;\n"}
        self.assertEqual(len(analysis.analyse(surveys(), surveys(), a, b)), 1)

    def test_detail_cut_when_built(self):
        """ruche-0117: names and extracts come from the judged code; a symbol of 5,000 characters gives a detail of DETAIL_MAX."""
        name = "bee_" + "x" * 5000
        found_ones = analysis.analyse(surveys(), surveys(nm=NM_A + f"/s/obj/rle.o: {name} D 0000000000000000 4\n"), {}, {},
                                    prefixes=("rle_",))
        self.assertEqual([s["type"] for s in found_ones], ["defined_symbol"])
        self.assertEqual(len(found_ones[0]["detail"]), analysis.DETAIL_MAX)
        self.assertTrue(found_ones[0]["detail"].startswith(name[:200]) and found_ones[0]["detail"].endswith("…"))


# Every prefix word objdump prints before an x86-64 instruction.
PREFIXES_X86 = ["es", "cs", "ss", "ds", "fs", "gs", "data16", "addr32", "lock", "rep", "repz", "repnz", "notrack", "bnd",
                "xacquire", "xrelease"] + ["rex" + ("." + "".join(c for c, bit in zip("WRXB", (8, 4, 2, 1)) if m & bit) if m else "")
                                           for m in range(16)]
NON_INSTRUCTIONS = ("valgrind_preamble", "segment_wx", "executable_stack")
GNU_STACK = 0x6474E551


def elf(kind_of, sections=(), segments=(), shstrndx=None, tail=b""):
    """Minimal x86-64 ELF file: an object (kind 1) with sections [(name, flags, bytes)] and its name table, or a program
    (kind 3) with segments [(type, flags, bytes)]; `tail` is appended after everything."""
    names = b"\0" + b"".join(n.encode() + b"\0" for n, _, _ in sections) + b".shstrtab\0"
    beginning = 64 + 56 * len(segments)
    body, ph, sh, position = b"", b"", bytes(64), 1
    for type_, flag_bits, data in segments:
        ph += struct.pack("<IIQQQQQQ", type_, flag_bits, beginning + len(body), 0, 0, len(data), len(data), 0)
        body += data
    for name, flag_bits, data in sections:
        sh += struct.pack("<IIQQQQIIQQ", position, 1, flag_bits, 0, beginning + len(body), len(data), 0, 0, 1, 0)
        position, body = position + len(name) + 1, body + data
    sh += struct.pack("<IIQQQQIIQQ", position, 3, 0, 0, beginning + len(body), len(names), 0, 0, 1, 0)
    body += names
    number = len(sections) + 2 if sections else 0
    head = b"\x7fELF\x02\x01\x01" + bytes(9) + struct.pack(
        "<HHIQQQIHHHHHH", kind_of, 62, 1, 0, 64 if segments else 0, beginning + len(body) if sections else 0, 0, 64, 56,
        len(segments), 64, number, max(number - 1, 0) if shstrndx is None else shstrndx)
    return head + ph + body + (sh if sections else b"") + tail


class TestExecutableBytes(unittest.TestCase):
    """Executable bytes read from hand-built ELF files."""

    def test_object_sections(self):
        object_name = elf(1, [(".text", 6, b"\x90\xc3"), (".data.x", 6, b"\x90\x0f\x05\x90"), (".data", 3, b"\x0f\x05"),
                        (".text.y", 2, b"\x0f\x31")])
        self.assertEqual(analysis.executable_bytes(object_name), ([b"\x90\xc3", b"\x90\x0f\x05\x90", b"\x0f\x31"], []))
        b = surveys(objects_found=[("rle.o", object_name)])
        self.assertEqual(sorted(s["detail"].split(":")[0] for s in analysis.analyse(surveys(), b, {}, {})), ["rdtsc", "syscall"])

    def test_hit_context_and_object(self):
        def objects_found(name, bytes_count):
            return surveys(objects_found=[(name, elf(1, [(".text", 6, bytes_count)]))])
        a = objects_found("rle.o", b"\x90" * 8 + b"\x0f\x05" + b"\xc3" * 8)
        self.assertEqual(analysis.analyse(a, objects_found("rle.o", b"\x90" * 8 + b"\x0f\x05" + b"\xc3" * 8), {}, {}), [])
        for b in (objects_found("rle.o", b"\x90" * 8 + b"\x0f\x05" + b"\xc3\xcc" * 4), objects_found("rle.o", b"\x90\xcc" * 4 + b"\x0f\x05" + b"\xc3" * 8),
                  objects_found("rle2.o", b"\x90" * 8 + b"\x0f\x05" + b"\xc3" * 8)):
            with self.subTest(b=b["objects"][0][0]):
                self.assertEqual([s["detail"].split(":")[0] for s in analysis.analyse(a, b, {}, {})], ["syscall"])

    def test_compressed_executable_section(self):
        with self.assertRaises(ValueError):
            analysis.executable_bytes(elf(1, [(".text.z", 0x806, b"\x0f\x05")]))

    def test_section_name_table_index(self):
        analysis.executable_bytes(elf(1, [(".text", 6, b"\x90")], tail=bytes(256)))
        for index_hint in (3, 4):
            with self.assertRaises(ValueError):
                analysis.executable_bytes(elf(1, [(".text", 6, b"\x90")], shstrndx=index_hint, tail=bytes(256)))

    def test_program_segments_and_stack(self):
        code, stack_of = (1, 5, b"\x90\xc3"), (GNU_STACK, 6, b"")
        self.assertEqual(analysis.executable_bytes(elf(3, segments=[code, stack_of])), ([b"\x90\xc3"], []))
        self.assertEqual(analysis.executable_bytes(elf(3, segments=[code]))[1], ["executable_stack"])
        self.assertEqual(analysis.executable_bytes(elf(3, segments=[code, (GNU_STACK, 7, b"")]))[1], ["executable_stack"])
        self.assertEqual(analysis.executable_bytes(elf(3, segments=[(1, 7, b"\x90"), stack_of]))[1], ["segment_wx"])


class TestSafeReading(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "c"))

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_regular_and_absent_file(self):
        with open(os.path.join(self.root, "c", "x"), "wb") as f:
            f.write(b"abc")
        self.assertEqual(reading.read_output(self.root, "c/x"), b"abc")
        self.assertIsNone(reading.read_output(self.root, "c/absent"))

    def test_links_pipes_and_paths_refused(self):
        os.symlink("/etc/hostname", os.path.join(self.root, "c", "link"))
        os.symlink("/etc", os.path.join(self.root, "d"))
        os.mkfifo(os.path.join(self.root, "c", "pipe"))
        for relative_one in ("c/link", "d/hostname", "c/pipe", "../x", "c/../c/x", "/etc/hostname"):
            with self.assertRaises(reading.Refusal, msg=relative_one):
                reading.read_output(self.root, relative_one)

    def test_bounded_size_and_status(self):
        with open(os.path.join(self.root, "c", "x"), "wb") as f:
            f.write(b"0" * 100)
        with self.assertRaises(reading.Refusal):
            reading.read_output(self.root, "c/x", maximum=10)
        with open(os.path.join(self.root, "c", "s"), "wb") as f:
            f.write(b"-2 12\n")
        self.assertEqual(reading.Outputs({"f": self.root}).status("f", "c/s"), (-2, 12))
        with open(os.path.join(self.root, "c", "s"), "wb") as f:
            f.write(b"0 12 ; rm -rf /\n")
        with self.assertRaises(reading.Refusal):
            reading.status(self.root, "c/s")

    def test_clean(self):
        self.assertEqual(reading.clean(b"::error::x\x1b[31m"), ": :error: :x?[31m")


class TestStatistics(unittest.TestCase):
    """The same definitions as minizBee's bee/bench/ab.py (reference values computed with ab.py)."""

    def test_sign_threshold(self):
        self.assertEqual([stats.sign_threshold(n) for n in (5, 6, 10, 20)], [None, 6, 9, 16])

    def test_sign_test(self):
        t = stats.sign_test([1, 1, 1, 1, 1, 1, 1, 1, 1, 1], [2, 2, 2, 2, 2, 2, 2, 2, 2, 1], "higher")
        self.assertEqual((t["b_wins"], t["ties"], t["threshold_k"], t["beyond_noise"]), (9, 1, 8, True))
        t = stats.sign_test([2] * 10, [1] * 10, "higher")
        self.assertTrue(t["degradation_beyond_noise"])
        t = stats.sign_test([2] * 10, [1] * 10, "lower")
        self.assertTrue(t["beyond_noise"] and not t["degradation_beyond_noise"])

    def test_summary_and_gain(self):
        self.assertEqual(stats.summary([3, None, 1, 2])["median"], 2)
        self.assertAlmostEqual(stats.relative_gain(100, 98, "lower"), 0.02)
        self.assertAlmostEqual(stats.relative_gain(100, 103, "higher"), 0.03)
        self.assertIsNone(stats.relative_gain(0, 1, "higher"))


class TestInputs(unittest.TestCase):
    def test_validation(self):
        good = inputs.Input("f", "k000", b"x", 1)
        inputs.check_inputs([good], ("f", "z"))
        for bad_one in (inputs.Input("q", "k", b"", 0), inputs.Input("f", "../k", b"", 0),
                        inputs.Input("f", "k", "text", 0), inputs.Input("f", "k", b"", -1)):
            with self.assertRaises(reading.JudgeError):
                inputs.check_inputs([bad_one], ("f", "z"))
        with self.assertRaises(reading.JudgeError):
            inputs.check_inputs([good, good], ("f",))

    def test_writing(self):
        folder = tempfile.mkdtemp()
        try:
            inputs.write(folder, [inputs.Input("z", "z000", b"abc", 7)], ("f", "z"))
            self.assertEqual(open(os.path.join(folder, "list")).read(), "z z000 7\n")
            self.assertTrue(os.path.isdir(os.path.join(folder, "f")))
        finally:
            shutil.rmtree(folder)

    def test_reproducible_perturb(self):
        corpus = [("k000", bytes(200_000)), ("k001", b"")]
        a = inputs.perturb(random.Random(1), corpus)
        self.assertEqual(a, inputs.perturb(random.Random(1), corpus))
        self.assertEqual(sum(1 for x in a[0][1] if x), 3)
        self.assertEqual(a[1][1], b"")


class TestPlugin(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.base, "bee", "judge"))

    def tearDown(self):
        shutil.rmtree(self.base)

    def write_plugin(self, text):
        with open(toy_file(self.base, "plugin"), "w", encoding="utf-8") as f:
            f.write(text)

    def test_version(self):
        """Version 5 (judge-v5): the judges in English, one plugin contract; judge.json names it in judge.common."""
        self.assertEqual((judge.COMMON_VERSION, judge.common_tag(), judge.common_tag(4)), (5, "judge-v5", "judge-v4"))
        self.assertEqual(judge.PLUGIN_PATH, os.path.join("bee", "judge", "project.py"))
        self.assertFalse(hasattr(judge, "PLUGIN_NAMES") or hasattr(judge, "EnglishPlugin"))

    def test_toy_plugin(self):
        """The toy's bee/judge/project.py keeps the contract: every name, its fingerprint, its directions; an unknown option is
        refused."""
        plugin, fingerprint = judge.load_plugin(TOY, {})
        self.assertEqual((plugin.NAME, plugin.TOOLING, plugin.BUILD), ("toy", ["bee/judge"], "bee/judge/build.sh"))
        for n in judge.REQUIRED_ATTRIBUTES + ("PACKAGES", "ALLOWED", "METHOD", "VERIFICATION"):
            self.assertTrue(hasattr(plugin, n), n)
        self.assertEqual([callable(getattr(plugin, m, None)) for m in judge.REQUIRED_METHODS], [True] * len(judge.REQUIRED_METHODS))
        self.assertEqual(plugin.METRICS[3], ("max_memory_kb", "lower", "KB"))
        with open(toy_file(TOY, "plugin"), "rb") as f:
            self.assertEqual(fingerprint, hashlib.sha256(f.read()).hexdigest())
        with self.assertRaises(reading.JudgeError):
            judge.load_plugin(TOY, {"unknown": "1"})

    def test_plugin_absent_or_incomplete(self):
        """No bee/judge/project.py: refused, whatever else the base holds (judge-v5 reads no other contract, the French
        bee/juge/projet.py included); a plugin without its class Project, or with a name missing: refused."""
        with self.assertRaises(reading.JudgeError) as e:
            judge.load_plugin(self.base, {})
        self.assertIn("plugin not found: bee/judge/project.py", str(e.exception))
        os.makedirs(os.path.join(self.base, "bee", "juge"))
        shutil.copyfile(toy_file(TOY, "plugin"), os.path.join(self.base, "bee", "juge", "projet.py"))
        with self.assertRaises(reading.JudgeError) as e:
            judge.load_plugin(self.base, {})
        self.assertIn("plugin not found: bee/judge/project.py", str(e.exception))
        self.write_plugin("class Projet:\n    NAME = 'x'\n    def __init__(self, options): pass\n")
        with self.assertRaises(reading.JudgeError) as e:
            judge.load_plugin(self.base, {})
        self.assertIn("defines no class Project", str(e.exception))
        self.write_plugin("class Project:\n    NAME = 'x'\n    def __init__(self, options): pass\n")
        with self.assertRaises(reading.JudgeError) as e:
            judge.load_plugin(self.base, {})
        self.assertIn("SCENARIOS", str(e.exception))

    def test_plugin_link_refused(self):
        os.symlink(toy_file(TOY, "plugin"), toy_file(self.base, "plugin"))
        with self.assertRaises(reading.JudgeError):
            judge.load_plugin(self.base, {})

    def changed_plugin(self, old, new):
        with open(toy_file(TOY, "plugin"), encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(text.count(old), 1)
        self.write_plugin(text.replace(old, new))

    def test_empty_or_short_prefixes_refused(self):
        for value in ('("",)', '()', '("r",)', '("rle-",)', '("rle",)', '("ge",)', '("rle_", "cl")', '("sys",)'):
            self.changed_plugin('PREFIXES = ("rle_",)', f"PREFIXES = {value}")
            with self.assertRaises(reading.JudgeError, msg=value):
                judge.load_plugin(self.base, {})

    def test_allowed_never_allowed(self):
        self.changed_plugin("ALLOWED = ()", 'ALLOWED = ("qsort", "clock_gettime")')
        with self.assertRaises(reading.JudgeError) as e:
            judge.load_plugin(self.base, {})
        self.assertIn("clock_gettime", str(e.exception))
        self.changed_plugin("ALLOWED = ()", 'ALLOWED = ("qsort",)')
        judge.load_plugin(self.base, {})

    def test_diff_no_longer_exists(self):
        self.changed_plugin('\n    SOURCES = ["rle.c", "rle.h"]', '\n    SOURCES = ["rle.c", "rle.h"]\n    DIFF = ["rle.c"]')
        with self.assertRaises(reading.JudgeError):
            judge.load_plugin(self.base, {})

    def test_scenario_outside_sides(self):
        self.changed_plugin('SCENARIOS = {"compression": "f"', 'SCENARIOS = {"compression": "q"')
        with self.assertRaises(reading.JudgeError):
            judge.load_plugin(self.base, {})

    def test_every_component_of_the_plugin_path_a_real_folder_or_file(self):
        """bee, bee/judge and the plugin itself: each a real folder or file, not a link."""
        for linked in (("bee",), ("bee", "judge"), ("bee", "judge", "project.py")):
            with self.subTest(linked=linked):
                root = tempfile.mkdtemp(dir=self.base)
                real = shutil.copytree(TOY, os.path.join(root, "real"))
                base = os.path.join(root, "base")
                os.makedirs(os.path.join(base, *linked[:-1]), exist_ok=True)
                os.symlink(os.path.join(real, *linked), os.path.join(base, *linked))
                self.assertTrue(os.path.isfile(toy_file(real, "plugin")) and os.path.isfile(toy_file(base, "plugin")))
                with self.assertRaises(reading.JudgeError) as e:
                    judge.load_plugin(base, {})
                self.assertIn("every component of its path must be a real folder or file, not a link", str(e.exception))
                judge.load_plugin(real, {})

    def test_directions(self):
        """A metric's direction is higher or lower: any other value or shape is refused (before ruche-0148, anything but the
        higher one was read as lower; the French contract's plus_haut and plus_bas are read no more since judge-v5)."""
        for old, new in (('("ratio", "higher", "ratio")', '("ratio", "plus_haut", "ratio")'),
                         ('("ratio", "higher", "ratio")', '("ratio", "Higher", "ratio")'),
                         ('("ratio", "higher", "ratio")', '("ratio", "plus haut", "ratio")'),
                         ('"lower", "KB"', '"plus_bas", "KB"'), ('("ratio", "higher", "ratio")', '("ratio", "lower")'),
                         ('("ratio", "higher", "ratio")', '("ratio", ["higher"], "ratio")'), ('("ratio", "higher", "ratio")', '"ratio"')):
            with self.subTest(new=new):
                self.changed_plugin(old, new)
                with self.assertRaises(reading.JudgeError) as e:
                    judge.load_plugin(self.base, {})
                self.assertIn("higher or lower", str(e.exception))


class TestExpectedObjects(unittest.TestCase):
    def test_units_and_homonyms(self):
        root = tempfile.mkdtemp()
        try:
            for path in ("src/a.c", "src/b.S", "src/c.cc", "src/d.h", "lib/e.c"):
                os.makedirs(os.path.join(root, os.path.dirname(path)), exist_ok=True)
                open(os.path.join(root, path), "w").close()
            self.assertEqual(judge.expected_objects(root), ({"a.o", "b.o", "c.o", "e.o"}, []))
            open(os.path.join(root, "lib", "a.c"), "w").close()
            self.assertEqual(judge.expected_objects(root)[1], ["a.o"])
        finally:
            shutil.rmtree(root)


class TestCoverage(unittest.TestCase):
    def test_outputs_read_and_coverage(self):
        root = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(root, "c"))
            for name in ("k000.6", "k001"):
                with open(os.path.join(root, "c", name), "wb") as f:
                    f.write(b"x")
            view = reading.Outputs({"f": root})
            view.require("f", "c/k000.6")
            self.assertTrue(view.covers("f", "k000"))
            self.assertFalse(view.covers("f", "k00"))
            self.assertFalse(view.covers("f", "k001"))
            list_of = [inputs.Input("f", "k000", b"", 0), inputs.Input("f", "k001", b"", 0)]
            with self.assertRaises(reading.JudgeError):
                judge.require_coverage(view, list_of, "trial")
            view.read("f", "c/k001")
            judge.require_coverage(view, list_of, "trial")
        finally:
            shutil.rmtree(root)


def add_to(path, bytes_count):
    with open(path, "ab") as f:
        f.write(bytes_count)


# reading.freeze in a subprocess, as uid 65534 when started as root (reading imported first): exit 10 on Refusal, 0 without
# error, 1 on any other exception (Python's own exit code), 11 if root cannot drop its privileges.
FREEZE_WITHOUT_PRIVILEGE = """import os, sys
sys.path.insert(0, sys.argv[1])
import reading
if os.geteuid() == 0:
    try:
        os.setgroups([]); os.setgid(65534); os.setuid(65534)
    except OSError:
        sys.exit(11)
try:
    reading.freeze(sys.argv[2])
except reading.Refusal:
    sys.exit(10)
"""


class TestFrozen(unittest.TestCase):
    """ruche-0036: outputs are frozen (listing and SHA-256 of each file); only what was frozen is read."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "s", "c"))
        for name, bytes_count in (("s/c/k000", b"abc"), ("s/c/k001", b""), ("s/s.err", b"")):
            with open(os.path.join(self.root, name), "wb") as f:
                f.write(bytes_count)
        os.symlink("/etc/hostname", os.path.join(self.root, "s", "link"))
        self.frozen = {"f": reading.freeze(self.root)}

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_fingerprint(self):
        empty_one = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        self.assertEqual(self.frozen["f"], {"s": "folder", "s/c": "folder", "s/link": "other", "s/s.err": empty_one, "s/c/k001": empty_one,
                                            "s/c/k000": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"})

    def test_only_the_frozen_one_reads(self):
        view = reading.Outputs({"f": self.root}, frozen=self.frozen)
        self.assertEqual((view.require("f", "s/c/k000"), view.read("f", "s/c/absent")), (b"abc", None))
        view.check_unchanged()
        copied = reading.Outputs(view)
        self.assertEqual((copied.read_paths, list(copied)), (set(), [self.root]))

        def path(relative_one):
            return os.path.join(self.root, relative_one)
        for name, change, relative_one in (("changed", lambda: add_to(path("s/c/k000"), b"x"), "s/c/k000"),
                                      ("removed", lambda: os.remove(path("s/c/k000")), "s/c/k000"),
                                      ("added", lambda: add_to(path("s/c/absent"), b""), "s/c/absent")):
            with self.subTest(name=name):
                change()
                with self.assertRaises(reading.Refusal):
                    copied.read("f", relative_one)
                with self.assertRaises(reading.Refusal):
                    copied.check_unchanged()
                shutil.rmtree(self.root)
                self.setUp()
                copied = reading.Outputs({"f": self.root}, frozen=self.frozen)

    def test_addition_not_read(self):
        add_to(os.path.join(self.root, "s", "addition"), b"")
        view = reading.Outputs({"f": self.root}, frozen=self.frozen)
        self.assertEqual(view.require("f", "s/c/k000"), b"abc")
        with self.assertRaises(reading.Refusal):
            view.check_unchanged()

    def test_judge_without_privilege(self):
        """The judge not root (as on a hosted runner, here uid 65534 in a subprocess): any system error while freezing what
        the container left (status, listing, opening) is a refusal (Refusal, exit 1), never an error of the environment (exit 2)."""
        def freeze_without_privilege():
            r = subprocess.run([sys.executable, "-I", "-c", FREEZE_WITHOUT_PRIVILEGE, HERE, self.root], capture_output=True,
                               text=True, timeout=60)
            if r.returncode == 11:
                self.skipTest("root cannot drop to uid 65534 here: the non-root judge is not tested")
            return r.returncode, r.stderr
        for folder, _, files in os.walk(self.root):
            os.chmod(folder, 0o755)
            for path in (os.path.join(folder, name) for name in files):
                if not os.path.islink(path):  # s/link is not followed
                    os.chmod(path, 0o644)
        self.assertEqual(freeze_without_privilege(), (0, ""))  # everything readable: frozen as root freezes it
        for relative_one, mode in (("s", 0o444), ("s/c", 0o444), ("s", 0o111), ("s", 0o000), ("s/c/k000", 0o000)):
            with self.subTest(relative_one=relative_one, mode=oct(mode)):
                path = os.path.join(self.root, relative_one)
                old = 0o755 if os.path.isdir(path) else 0o644  # as set above
                os.chmod(path, mode)
                try:
                    self.assertEqual(freeze_without_privilege(), (10, ""))
                finally:
                    os.chmod(path, old)


class TestReferenceCodec(unittest.TestCase):
    def test_round_trip(self):
        rng = random.Random(5)
        plugin = toy_plugin.Project({})
        for _, d in plugin.corpus(None) + plugin.random_inputs(rng):
            self.assertEqual(toy_plugin.decompress(toy_plugin.compress(d)), d)

    def test_invalid_streams_recognized(self):
        z = toy_plugin.compress(b"abc" * 100)
        self.assertIsNone(toy_plugin.decompress(z[:-1]))
        self.assertIsNone(toy_plugin.decompress(z + b"\x00"))
        self.assertIsNone(toy_plugin.decompress(z[:-4] + bytes(4)))


class TestSourceCopy(unittest.TestCase):
    def test_links_refused(self):
        repo, destination = tempfile.mkdtemp(), tempfile.mkdtemp()
        try:
            shutil.copyfile(os.path.join(TOY, "rle.h"), os.path.join(repo, "rle.h"))
            os.symlink("/etc/hostname", os.path.join(repo, "rle.c"))
            with self.assertRaises(reading.Refusal):
                judge.copy_sources(repo, destination, ["rle.c", "rle.h"], ["rle.c", "rle.h"])
        finally:
            shutil.rmtree(repo)
            shutil.rmtree(destination)

    def test_subfolder(self):
        repo, destination = tempfile.mkdtemp(), tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(repo, "src"))
            open(os.path.join(repo, "src", "a.c"), "w").close()
            os.symlink("/etc", os.path.join(repo, "trap"))
            judge.copy_sources(repo, destination, ["src/*.c", "trap/*"], ["src/a.c"])
            self.fail("the linked folder should have been refused")
        except reading.Refusal:
            pass
        finally:
            shutil.rmtree(repo)
            shutil.rmtree(destination)


class TestImage(unittest.TestCase):
    def test_packages(self):
        self.assertIn("RUN apt-get update", container.dockerfile(["zlib1g-dev"]))
        self.assertTrue(container.dockerfile([]).rstrip().endswith("WORKDIR /"))
        for wrong_one in ("x; curl", "-y", "A"):
            with self.assertRaises(reading.JudgeError):
                container.dockerfile([wrong_one])


# ------------------------------------------------------------------ ruche-0037: the same conditions in every mode

class FakeDocker:
    """Stand-in for container.Docker: records each container (command, mounts, standard input) and answers like chrono."""

    def __init__(self):
        self.calls = []

    def launch(self, command, mounts, pids=2, entry=None, timeout_seconds=3600):
        self.calls.append((command, mounts, entry.decode()))
        token, _, *plan = entry.decode().splitlines()
        output_text = "".join(json.dumps({"token": token, "label": line_text.split("\t")[0], "code": 0, "signal": 0,
                                     "instructions": 1}) + "\n" for line_text in plan)
        return subprocess.CompletedProcess(command, 0, output_text.encode(), b"")


# A stand-in for docker that records each call (arguments, standard input) and answers as chrono would.
DOCKER_STOPWATCH = r"""#!/usr/bin/env python3
import json, os, sys
if sys.argv[1] != "run":  # ruche-0136: Docker's record of the container, read after it ends, then its removal
    print(json.dumps({"Status": "exited", "Error": "", "ExitCode": 0}) if sys.argv[1] == "inspect" else "")
    sys.exit(0)
entry = sys.stdin.read()
with open(os.environ["FAKE_DOCKER_LOG"], "a") as f:
    f.write(json.dumps([sys.argv[1:], entry]) + "\n")
token, _, *plan = entry.splitlines()
for line in plan:
    print(json.dumps({"token": token, "label": line.split("\t")[0], "code": 0, "signal": 0, "instructions": 1}))
"""


# Docker's own mounts in a container of the judge (cgroup v1 and v2, /proc and /sys masked; /dev/shm also sorted with the judge's).
DOCKER_MOUNTS = ["/proc", "/dev", "/dev/pts", "/sys", "/sys/fs/cgroup", "/sys/fs/cgroup/cpu", "/dev/mqueue", "/dev/shm",
                   "/proc/bus", "/proc/sys", "/proc/acpi", "/sys/firmware", "/sys/devices/virtual/powercap"]


class TestSameConditions(unittest.TestCase):
    """The judge starts the harness the same way in every mode (same arguments, same mounts); the mode reaches it on its
    descriptor 0 only."""

    def setUp(self):
        self.workdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.workdir)

    def test_modes_differ_only_on_the_harness_input(self):
        docker = FakeDocker()
        run = container.Execution(docker, "/c", {"B": "/b"}, self.workdir)
        harness = [container.HARNESS, "/inputs", "/outputs"]
        run.launch("B", "/e", os.path.join(self.workdir, "s"), [("verify", [container.HARNESS, "verify", "/inputs", "/outputs"])], timeout_seconds=3600)
        run.launch("B", "/e", os.path.join(self.workdir, "s"), [("compression", [container.HARNESS, "compression", "/inputs", "/outputs"])])
        run.launch("B", "/e", os.path.join(self.workdir, "s"), [("compression", judge.VALGRIND + [container.HARNESS, "compression", "/inputs", "/outputs"])],
                         valgrind=True, timeout_seconds=3600)
        seen_items = []
        for command, mounts, entry in docker.calls:
            self.assertEqual(command, ["/chrono/chrono"])
            self.assertEqual(sorted(target.replace(container.LINK, "") for _, target, _ in mounts),
                             sorted(["/chrono", "/inputs", "/outputs", "/variant"] + ["/etc/" + n for n in container.ETC]))
            _, options, line_text = entry.splitlines()
            label, parameters, *argv = line_text.split("\t")
            self.assertEqual(argv[argv.index(container.HARNESS):], [container.HARNESS])
            self.assertEqual(parameters.split(), [label] + harness[1:])
            seen_items.append((options, argv))
        self.assertEqual(seen_items, [("3600 0", [container.HARNESS]), ("1800 0", [container.HARNESS]), ("3600 1", judge.VALGRIND + [container.HARNESS])])
        for wrong_one in ([container.HARNESS], ["/bin/sh", "-c", "x"], [container.HARNESS, "a\tb"]):
            with self.assertRaises(reading.JudgeError):
                run.launch("B", "/e", os.path.join(self.workdir, "s"), [("x", wrong_one)])

    def test_same_docker_request_in_every_mode(self):
        """The Docker command is the same in every mode (bounds, isolation, mounts, their options and their order, the
        image), but for the container's name; only the standard input differs. A stand-in docker, first on PATH, records
        each call made through the real Docker.launch and answers as chrono would."""
        folder = os.path.join(self.workdir, "bin")
        os.makedirs(folder)
        with open(os.path.join(folder, "docker"), "w", encoding="utf-8") as f:
            f.write(DOCKER_STOPWATCH)
        os.chmod(os.path.join(folder, "docker"), 0o755)
        docker_log = os.path.join(self.workdir, "docker.log")
        run = container.Execution(container.Docker("sha256:" + "0" * 64), "/c", {"B": "/b"}, self.workdir)
        outputs = os.path.join(self.workdir, "s")
        with mock.patch.dict(os.environ, {"PATH": folder + os.pathsep + os.environ["PATH"], "FAKE_DOCKER_LOG": docker_log}):
            for mode, prefix_text, valgrind in (("verify", [], False), ("compression", [], False), ("compression", judge.VALGRIND, True)):
                run.launch("B", "/e", outputs, [(mode, prefix_text + [container.HARNESS, mode, "/inputs", "/outputs"])],
                                 valgrind=valgrind)
        with open(docker_log, encoding="utf-8") as f:
            calls = [json.loads(line_text) for line_text in f]
        self.assertEqual(len(calls), 3)
        commands = []
        for command, _ in calls:
            i = command.index("--name")
            self.assertRegex(command[i + 1], r"^bee-judge-[0-9a-f]{12}$")
            commands.append(command[:i + 1] + command[i + 2:])
        self.assertEqual(commands, [commands[0]] * 3)
        command = commands[0]
        self.assertEqual(command[command.index("--ulimit"):command.index("--ulimit") + 4], container.Docker.BOUNDS)
        for option in container.ISOLATION:
            self.assertIn(option, command)
        root = os.path.join(self.workdir, "execution")  # ruche-0117: each execution's own tmpfs, at the same path
        self.assertEqual([c for c in command if c.startswith("type=bind")],
                         [f"type=bind,source={root}/chrono,target={container.LINK * 7}/chrono,readonly",
                          f"type=bind,source={root}/variant,target={container.LINK * 8}/variant,readonly",
                          f"type=bind,source={root}/inputs,target={container.LINK * 9}/inputs,readonly",
                          f"type=bind,source={root}/outputs,target={container.LINK * 10}/outputs"]
                         + [f"type=bind,source={root}/etc/{n},target=/etc/{n},readonly" for n in container.ETC])
        self.assertEqual(command[-2:], ["sha256:" + "0" * 64, "/chrono/chrono"])
        self.assertEqual(len({entry for _, entry in calls}), 3)

    def docker_commands(self, *calls):
        """The docker run commands the real Docker.launch makes for these calls, a stand-in docker first on PATH."""
        folder, docker_log = os.path.join(self.workdir, "bin"), os.path.join(self.workdir, "docker.log")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "docker"), "w", encoding="utf-8") as f:
            f.write(DOCKER_STOPWATCH)
        os.chmod(os.path.join(folder, "docker"), 0o755)
        with mock.patch.dict(os.environ, {"PATH": folder + os.pathsep + os.environ["PATH"], "FAKE_DOCKER_LOG": docker_log}):
            for call in calls:
                call()
        with open(docker_log, encoding="utf-8") as f:
            return [json.loads(line_text)[0] for line_text in f]

    def test_one_mount_order_whatever_docker_draws(self):
        """ruche-0136: Docker up to 29.0 sorts the mounts it is given (binds, tmpfs, /dev/shm, /etc's files) by depth alone,
        those of equal depth in an order drawn for each container. Each folder the judge mounts, in an execution's container
        as in a build's, has a depth no other mount of the container shares, Docker's own included (DOCKER_MOUNTS;
        test_depths with Docker): whatever order Docker draws, they come out in one order, and land, through the image's
        link to its root, where they are named. The layout before ruche-0136 (/variant at /etc's depth) fails this check."""
        run = container.Execution(container.Docker("i"), "/c", {"B": "/b"}, self.workdir)
        commands = self.docker_commands(
            lambda: run.launch("B", "/e", os.path.join(self.workdir, "s"), [("verify", [container.HARNESS, "verify", "/inputs", "/outputs"])]),
            lambda: container.Docker("i").launch(["true"], [(self.workdir, n, n != "/output") for n in ("/sources", "/tooling", "/output")],
                                                entry=b"token\n0 0\n"))
        depth = lambda c: os.path.normpath(c).count("/")  # noqa: E731

        def orders(command):
            targets = [o.split("target=")[1].split(",")[0] for o in command if o.startswith("type=bind")]
            folders = [c for c in targets if not c.startswith("/etc/")]
            others = [c for c in targets if c.startswith("/etc/")] + ["/dev/shm"] + [command[i + 1].split(":")[0] for i, o
                                                                                    in enumerate(command) if o == "--tmpfs"]
            unique_ones = len({depth(c) for c in folders}) == len(folders) and \
                not {depth(c) for c in folders} & {depth(c) for c in others + DOCKER_MOUNTS}
            return unique_ones, {tuple(c if c in folders else "" for c in sorted(draw, key=depth))  # where each one comes
                             for draw in itertools.permutations(folders + others)}
        for command, names in zip(commands, (["/chrono", "/variant", "/inputs", "/outputs"], ["/sources", "/tooling", "/output"])):
            unique_ones, drawn = orders(command)
            self.assertTrue(unique_ones)
            self.assertEqual(len(drawn), 1)
            self.assertEqual([c.replace(container.LINK, "") for c in drawn.pop() if c], names)
        old = [o.replace(container.LINK * 7 + "/chrono", "/chrono").replace(container.LINK * 8, container.LINK)
                  for o in commands[0]]  # before ruche-0136: /chrono at depth 1 (/tmp's), /variant at 2 (/etc's)
        self.assertFalse(orders(old)[0])
        self.assertGreater(len(orders(old)[1]), 1)
        image = container.dockerfile([])
        self.assertLess(image.index(f"\nRUN ln -s / {container.LINK}\n"), image.index("\nUSER "))

    def test_tmpfs_in_use_is_an_error(self):
        """ruche-0117: each execution's tmpfs is unmounted at once, not detached (no --lazy): one still in use when its
        container has ended stops the judge with an error, rather than staying alive out of sight."""
        docker, held = FakeDocker(), []
        launch = docker.launch

        def hold_it(command, mounts, **options):
            held.append(os.open(os.path.dirname(mounts[0][0]), os.O_RDONLY))
            return launch(command, mounts, **options)
        docker.launch = hold_it
        root = os.path.join(self.workdir, "execution")
        try:
            with self.assertRaisesRegex(reading.JudgeError, "^umount of an execution's tmpfs failed"):
                container.Execution(docker, "/c", {"B": "/b"}, self.workdir).launch(
                    "B", "/e", os.path.join(self.workdir, "s"), [("verify", [container.HARNESS, "verify", "/inputs", "/outputs"])])
            self.assertTrue(os.path.ismount(root))
        finally:
            for fd in held:
                os.close(fd)
            if os.path.ismount(root):
                container.mount_point("umount", root)
        self.assertEqual(len(held), 1)

    def test_mounted_folders_have_neutral_names(self):
        """A scenario's outputs are mounted on /outputs, as verification's, from a neutral folder renamed afterwards."""
        plugin = toy_plugin.Project({})
        folders = judge.prepare(self.workdir, "verification", plugin.repetition(random.Random(1), plugin.corpus(TOY)), ("f", "z"))
        outputs = judge.outputs_of(self.workdir, "outputs-verification-B", ("f", "z"))
        for folder in list(folders.values()) + list(outputs.values()):
            self.assertRegex(os.path.basename(folder), r"^[0-9a-f]{16}$")
        mounted, test = [], self

        class FakeRun:
            def launch(self, variant, inputs_folder, folder, plan, **options):
                test.assertRegex(os.path.relpath(folder, test.workdir), r"^[0-9a-f]{16}$")
                test.assertEqual([c[-1] for _, c in plan], ["/outputs"])
                mounted.append(folder)
                with open(os.path.join(folder, "output"), "w", encoding="utf-8") as f:
                    f.write(plan[0][0])
                return {plan[0][0]: {}}
        plans = {c: [(s, [container.HARNESS, s, "/inputs", "/outputs"]) for s, cs in plugin.SCENARIOS.items() if cs == c] for c in "fz"}
        measurements, _ = judge.launch_by_side(FakeRun(), "B", folders, outputs, plans, list(plugin.SCENARIOS))
        self.assertEqual(set(measurements), set(plugin.SCENARIOS))
        self.assertEqual(len(set(mounted)), len(plugin.SCENARIOS))
        for s, c in plugin.SCENARIOS.items():
            self.assertEqual(reading.require(outputs[c], f"{s}/output"), s.encode())


class TestShuffle(unittest.TestCase):
    """Verification inputs are mixed into the measured inputs, drawn from the judge's seed (A and B get the same); every
    input is written shuffled and renamed, the plugin keeping its names."""

    def draw(self, seed, repetitions=3):
        plugin = toy_plugin.Project({})
        rng = random.Random(seed)
        corpus = plugin.corpus(TOY)
        verification = plugin.verification(rng, corpus)
        written_ones, neutral_ones = judge.rename(rng, verification)
        names = {(e.side, e.name): n for e, n in zip(verification, neutral_ones)}
        by_side = {c: [e for e in verification if e.side == c] for c in "fz"}
        rounds = {c: judge.rounds_of(rng, l) for c, l in by_side.items()}
        how_many = {c: -(-len(l) // repetitions) for c, l in by_side.items()}
        return verification, written_ones, names, [(judge.interleave(rng, plugin.repetition(rng, corpus), rounds, how_many, names), how_many)
                                             for _ in range(repetitions)]

    def test_verification_inputs_renamed(self):
        verification, written_ones, names, _ = self.draw(1)
        inputs.check_inputs(written_ones, ("f", "z"))
        self.assertEqual(sorted(e.name for e in written_ones), [f"e{i:04d}" for i in range(len(verification))])
        self.assertNotEqual([e.data for e in written_ones], [e.data for e in verification], "shuffled")
        by_name = {(e.side, e.name): e for e in written_ones}
        for e in verification:
            self.assertEqual(by_name[(e.side, names[(e.side, e.name)])]._replace(name=e.name), e)

    def test_each_verification_input_passes_in_a_measurement(self):
        verification, written_ones, names, draws = self.draw(1)
        written_one = {(e.side, e.name): e for e in written_ones}
        passed_ones = set()
        for (interleaved, shuffled), how_many in draws:
            inputs.check_inputs(interleaved, ("f", "z"))
            self.assertTrue(all(re.fullmatch(r"e\d{4}", e.name) for e in interleaved))
            self.assertEqual(len(shuffled), sum(how_many.values()))
            by_name = {(e.side, e.name): e for e in interleaved}
            positions = sorted(interleaved.index(by_name[key]) for key in shuffled)
            self.assertLess(positions[0], len(interleaved) - len(shuffled), "mixed in, not appended")
            for (side, name), verification_name in shuffled.items():
                self.assertEqual(by_name[(side, name)]._replace(name=verification_name), written_one[(side, verification_name)])
            for c in "fz":
                self.assertEqual(sum(1 for side, _ in shuffled if side == c), how_many[c])
            passed_ones |= set(shuffled.values())
        self.assertEqual(passed_ones, {e.name for e in written_ones})

    def test_drawn_from_the_seed(self):
        self.assertEqual(self.draw(7)[3], self.draw(7)[3])
        self.assertNotEqual(self.draw(7)[3], self.draw(8)[3])

    def test_names_translated_for_the_plugin(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        os.makedirs(os.path.join(root, "c"))
        for name in ("e0003", "e0003.6", "e0007"):
            with open(os.path.join(root, "c", name), "wb") as f:
                f.write(name.encode())
        view = reading.Outputs({"f": root}, {("f", "k000"): "e0003", ("f", "a.b"): "e0007"})
        self.assertEqual((view.require("f", "c/k000"), view.require("f", "c/k000.6"), view.read("f", "c/a.b")), (b"e0003", b"e0003.6", b"e0007"))
        self.assertTrue(view.covers("f", "k000") and view.covers("f", "a.b"))
        self.assertIsNone(view.read("f", "c/k001"))

    def test_mixed_input_same_output_as_in_verification(self):
        """B's output of a mixed-in input, in a measured run, must be its own verification output, byte for byte."""
        workdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, workdir)

        def write(path, bytes_count):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(bytes_count)
        def frozen_one(folder):  # ruche-0036: the judge compares outputs as frozen when their container ended
            return reading.Outputs({"f": os.path.join(workdir, folder)}, frozen={"f": reading.freeze(os.path.join(workdir, folder))})
        write(os.path.join(workdir, "v", "c", "e0004"), b"output")
        write(os.path.join(workdir, "v", "e", "e0004.6"), b"0 6\n")
        verification = frozen_one("v")
        index = judge.outputs_by_input(verification.frozen)
        self.assertEqual(sorted(index[("f", "e0004")]), ["c/e0004", "e/e0004.6"])
        write(os.path.join(workdir, "m", "compression", "c", "e0011"), b"output")
        write(os.path.join(workdir, "m", "compression", "e", "e0011.6"), b"0 6\n")
        self.assertEqual(judge.same_outputs(index, verification, frozen_one("m"), {("f", "e0011"): "e0004"}, [("compression", "f")]), 2)
        write(os.path.join(workdir, "m", "compression", "c", "e0011"), b"other")
        with self.assertRaisesRegex(reading.Refusal, "differs"):
            judge.same_outputs(index, verification, frozen_one("m"), {("f", "e0011"): "e0004"}, [("compression", "f")])
        with self.assertRaises(reading.JudgeError):
            judge.same_outputs(index, verification, frozen_one("m"), {("f", "e0012"): "e0004"}, [("compression", "f")])
        measured = frozen_one("m")
        write(os.path.join(workdir, "m", "compression", "c", "e0011"), b"output")
        with self.assertRaisesRegex(reading.Refusal, "fingerprint"):
            judge.same_outputs(index, verification, measured, {("f", "e0011"): "e0004"}, [("compression", "f")])
        # ruche-0117: counted per scenario, not per side: a scenario of the side without a comparable output is an error.
        two = [("compression", "f"), ("compression_bis", "f")]
        with self.assertRaisesRegex(reading.JudgeError, "compression_bis"):
            judge.same_outputs(index, verification, frozen_one("m"), {("f", "e0011"): "e0004"}, two)
        write(os.path.join(workdir, "m", "compression_bis", "e", "e0011.6"), b"0 6\n")
        self.assertEqual(judge.same_outputs(index, verification, frozen_one("m"), {("f", "e0011"): "e0004"}, two), 3)


class TestFixedConditions(unittest.TestCase):
    """Fixed times on what a container sees; /variant holds the harness alone; repetitions at least 1."""

    def test_times_and_variant(self):
        workdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, workdir)
        build_folder = os.path.join(workdir, "build")
        os.makedirs(os.path.join(build_folder, "obj"))
        for name in ("execution", "obj/rle.o"):
            with open(os.path.join(build_folder, name), "wb") as f:
                f.write(name.encode())
        variant = judge.variant(build_folder, os.path.join(workdir, "variant"))
        self.assertEqual(os.listdir(variant), ["execution"])
        container.fixed_times(variant)
        for path in (variant, os.path.join(variant, "execution")):
            st = os.stat(path)
            self.assertEqual((st.st_atime, st.st_mtime), (container.TIME, container.TIME))
        os.remove(os.path.join(build_folder, "execution"))
        os.symlink("/etc/hostname", os.path.join(build_folder, "execution"))
        with self.assertRaises(reading.Refusal):
            judge.variant(build_folder, os.path.join(workdir, "variant-2"))

    def test_repetitions_at_least_one(self):
        for options in (["--repetitions", "0", "--warmup", "0"], ["--warmup", "-1"]):
            with contextlib.redirect_stderr(io.StringIO()) as error, self.assertRaises(SystemExit) as end:
                judge.main(["--tooling", TOY, "--source-a", TOY, "--source-b", TOY] + options)
            self.assertEqual(end.exception.code, 2)
            self.assertIn("--repetitions", error.getvalue())

# ------------------------------------------------------------------ ruche-0036: frozen outputs, drawn order, CPU times

FOUR_SCENARIOS = {"compression": "f", "compression_bis": "f", "decompression": "z", "decompression_bis": "z"}


def toy_with_four_scenarios(folder, toy=TOY):
    """A copy of the toy project with two scenarios per side (the harness does the same work
    in every mode)."""
    shutil.copytree(toy, folder, ignore=shutil.ignore_patterns("__pycache__"))
    for file, old, new in (
            ("plugin", 'SCENARIOS = {"compression": "f", "decompression": "z"}', f"SCENARIOS = {FOUR_SCENARIOS!r}"),
            ("harness", '|| strcmp(mode, "decompression") == 0);',
             '|| strcmp(mode, "decompression") == 0 || strcmp(mode, "compression_bis") == 0\n'
             '         || strcmp(mode, "decompression_bis") == 0);')):
        path = toy_file(folder, file)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(replace_with(text, old, new))
    return folder


def toy_harness(inputs_folder, outputs):
    """The toy harness (toy/bee/judge/execution.c), emulated with the plugin's reference codec: the same work in every
    mode, f inputs give c/NAME, z inputs d/NAME and e/NAME."""
    def write(folder, name, bytes_count):
        os.makedirs(os.path.join(outputs, folder), exist_ok=True)
        with open(os.path.join(outputs, folder, name), "wb") as f:
            f.write(bytes_count)
    with open(os.path.join(inputs_folder, "list"), encoding="ascii") as f:
        for line_text in filter(str.strip, f):
            side, name, _ = line_text.split()
            with open(os.path.join(inputs_folder, side, name), "rb") as g:
                data = g.read()
            if side == "f":
                write("c", name, toy_plugin.compress(data))
            else:
                original = toy_plugin.decompress(data)
                write("d", name, original or b"")
                write("e", name, b"-1 0\n" if original is None else b"0 %d\n" % len(original))


class EmulatedDocker:
    """Stand-in for container.Docker: nothing is run; chrono (plan on its standard input) and the toy harness are emulated
    on the host folders of the mounts. Each container is recorded (plan labels, variant, writable mounts, whether they
    were empty, the CPU time answered); `after(self)` is called once each has ended."""

    image = "sha256:" + "0" * 64

    def __init__(self, after=None):
        self.containers, self.after = [], after

    def launch(self, command, mounts, pids=2, entry=None, timeout_seconds=3600):
        host = {target.replace(container.LINK, ""): source for source, target, _ in mounts}  # the image's link, followed
        token, _, *plan = entry.decode().splitlines()
        written_items = [source for source, _, read_only in mounts if not read_only]
        with open(os.path.join(host["/variant"], "execution"), encoding="ascii") as f:
            variant = f.read()
        c = {"labels": [p.split("\t")[0] for p in plan], "variant": variant, "written": written_items,
             "fresh": all(not os.listdir(d) for d in written_items), "tmpfs": all(os.path.ismount(os.path.dirname(d)) for d in written_items)}
        self.containers.append(c)
        lines = []
        for line_text in plan:
            label, parameters, *_ = line_text.split("\t")
            _, c_inputs, c_outputs = parameters.split()
            toy_harness(host[c_inputs], host[c_outputs])
            user, system = 0.001 * len(self.containers), 0.0005
            c["cpu"] = round(user + system, 6)
            lines.append(json.dumps({"token": token, "label": label, "code": 0, "signal": 0, "user_s": user,
                                      "system_s": system, "wall_s": 0.01, "maxrss_kb": 1000, "instructions": 1000}))
        if self.after:
            self.after(self)
        return subprocess.CompletedProcess(command, 0, ("\n".join(lines) + "\n").encode(), b"")


def empty_open_folder(workdir):
    """chrono's folder for EmulatedDocker (nothing is run): an empty folder."""
    return container.open_folder(os.path.join(workdir, "chrono"))


def emulated_variant(build_folder, folder):
    """/variant for EmulatedDocker: a harness file that names the variant (the last letter of the folder)."""
    os.makedirs(folder)
    with open(os.path.join(folder, "execution"), "w", encoding="ascii") as f:
        f.write(folder[-1])
    return folder


class TestOrderAndFingerprints(unittest.TestCase):
    """ruche-0036, without Docker: judge.main on the toy with two scenarios per side, container.Docker emulated."""

    @classmethod
    def setUpClass(cls):
        cls.workdir = tempfile.mkdtemp(prefix="bee-order-")
        cls.base = toy_with_four_scenarios(os.path.join(cls.workdir, "toy"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.workdir, ignore_errors=True)

    def run_the_judge(self, after=None, seed="00" * 16, order_seed=None, base=None):
        base, emulated, output_text = base or self.base, EmulatedDocker(after), io.StringIO()
        with mock.patch.object(judge.shutil, "which", return_value="/usr/bin/docker"), \
                mock.patch.object(judge.container, "build_image", return_value="image"), \
                mock.patch.object(judge.container, "image_id", return_value="sha256:" + "0" * 64), \
                mock.patch.object(judge, "variant", side_effect=emulated_variant), \
                mock.patch.object(judge.container, "Docker", return_value=emulated), \
                mock.patch.object(judge.container, "compile_stopwatch", side_effect=lambda docker, workdir: empty_open_folder(workdir)), \
                mock.patch.object(judge, "build", return_value=surveys()), \
                contextlib.redirect_stdout(output_text), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(judge.main(["--tooling", base, "--source-a", base, "--source-b", base, "--repetitions", "3"]
                                       + (["--seed", seed] if seed else []) + (["--order-seed", order_seed] if order_seed else [])), 0)
        return json.loads(output_text.getvalue()), emulated

    def test_drawn_order_and_processor_time(self):
        """The order is drawn at each repetition, the same for A and B, from its own seed (secrets, independent of the
        inputs' seed) recorded in judge.json, and is the order run; each scenario's CPU time is the one chrono measured; one
        command and one fresh writable folder per container."""
        report, emulated = self.run_the_judge(order_seed="00" * 16)
        self.assertEqual(len(emulated.containers), 2 * 2 + 2 * 4 * 4 + 2 * 2)  # verification, 1 + 3 repetitions, instructions
        for c in emulated.containers:  # ruche-0117: its fresh writable folder on its own tmpfs, mounted for it
            self.assertEqual((len(c["labels"]), len(c["written"]), c["fresh"], c["tmpfs"]), (1, 1, True, True))
        unfolding = report["judge"]["scenarios"]["steps"]
        self.assertEqual([e["step"] for e in unfolding], ["warmup", "measurement", "measurement", "measurement", "instructions"])
        self.assertEqual([e["variants"] for e in unfolding], ["AB", "BA", "AB", "BA", "AB"])
        instructions_given = []
        for e in unfolding:
            expected_items = toy_plugin.Project.INSTRUCTIONS if e["step"] == "instructions" else FOUR_SCENARIOS
            self.assertEqual(sorted(e["order"]), sorted(expected_items))
            instructions_given += [(v, s, e["cpu_time_s"][v][s]) for v in e["variants"] for s in e["order"]]
        runs_launched = [(c["variant"], c["labels"][0], c["cpu"]) for c in emulated.containers if c["labels"] != ["verify"]]
        self.assertEqual(runs_launched, instructions_given)
        self.assertGreater(len({tuple(e["order"]) for e in unfolding[:4]}), 1)

        def orders(r):
            return [e["order"] for e in r["judge"]["scenarios"]["steps"]]

        def drawn(order_seed):  # the orders the recorded order seed alone gives
            draw = random.Random(bytes.fromhex(order_seed))
            return [draw.sample(list(FOUR_SCENARIOS), 4) for _ in range(4)] + [draw.sample(list(toy_plugin.Project.INSTRUCTIONS), 2)]
        self.assertEqual((report["judge"]["scenarios"]["order_seed"], orders(report)), ("00" * 16, drawn("00" * 16)))
        self.assertEqual(orders(self.run_the_judge(seed="01" * 16, order_seed="00" * 16)[0]), orders(report))  # not from --seed
        seeds = {report["judge"]["scenarios"]["order_seed"]}
        for _ in range(2):  # same --seed, order seed from secrets: recorded, and it alone gives the orders
            other = self.run_the_judge()[0]
            order_seed = other["judge"]["scenarios"]["order_seed"]
            self.assertRegex(order_seed, r"\A[0-9a-f]{32}\Z")
            self.assertEqual(orders(other), drawn(order_seed))
            self.assertEqual((other["judge"]["seed"], other["judge"]["verification"]), (report["judge"]["seed"], report["judge"]["verification"]))
            seeds.add(order_seed)
        self.assertEqual(len(seeds), 3)

    def test_where_each_seed_came_from(self):
        """ruche-0136: judge.json says, for each seed (the inputs', the order's), whether the judge drew it or it was given on the
        command line (--seed, --order-seed: a local reproduction); only a report whose seeds were both drawn passes
        report.py --verify."""
        path = os.path.join(self.workdir, "seeds.json")
        for seed, order_seed, origins in ((None, None, ("drawn", "drawn")), ("00" * 16, None, ("given", "drawn")),
                                               (None, "01" * 16, ("drawn", "given")), ("00" * 16, "01" * 16, ("given", "given"))):
            with self.subTest(seed=seed, order_seed=order_seed):
                j = self.run_the_judge(seed=seed, order_seed=order_seed)[0]
                j["judge"].update(base="2" * 40, head="3" * 40)
                self.assertEqual(j["judge"]["seed_origin"], dict(zip(("seed", "order_seed"), origins)))
                self.assertEqual((j["judge"]["seed"] == seed, j["judge"]["scenarios"]["order_seed"] == order_seed),
                                 (seed is not None, order_seed is not None))
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(j, f)
                if origins == ("drawn", "drawn"):
                    self.assertEqual(report.verify(path, report.publish(path, "0"), "2" * 40, "3" * 40), j)
                else:
                    with self.assertRaisesRegex(report.Gap, "seed given"):
                        report.verify(path, report.publish(path, "0"), "2" * 40, "3" * 40)

    def test_each_execution_on_its_own_tmpfs(self):
        """ruche-0117: each container's folders are on a tmpfs mounted for it alone, of fixed bounds: whatever the containers
        before it wrote, each finds the same free space and the same device, and nothing of it remains after the judge."""
        seen_items = []

        def after(emulated):
            written = emulated.containers[-1]["written"][0]
            st, fs = os.stat(written), os.statvfs(written)
            seen_items.append((st.st_dev, fs.f_blocks * fs.f_frsize, fs.f_files, os.path.ismount(os.path.dirname(written))))
            self.assertEqual(sorted(os.listdir(os.path.dirname(written))), ["chrono", "etc", "inputs", "outputs", "variant"])
        _, emulated = self.run_the_judge(after)
        self.assertEqual(len(seen_items), len(emulated.containers))
        self.assertEqual(set(seen_items), {(seen_items[0][0], 4 << 30, 262144, True)})
        self.assertFalse(any(os.path.ismount(os.path.dirname(c["written"][0])) for c in emulated.containers))

    def test_suspicious_most_serious_first(self):
        """ruche-0117: judge.json lists the most serious constructs first (SEVERITY), SUSPICIOUS_MAX at most, and counts each kind."""
        found_ones = [{"type": "source", "detail": f"pragma {i}"} for i in range(judge.SUSPICIOUS_MAX + 20)]
        found_ones += [{"type": "symbol", "detail": "s"}, {"type": "unknown", "detail": "?"}, {"type": "forbidden_call", "detail": "g"}]
        with mock.patch.object(judge.analysis, "analyse", return_value=found_ones), \
                mock.patch.object(judge.platform, "machine", return_value="x86_64"):
            j = self.run_the_judge()[0]["judge"]
        self.assertEqual([s["type"] for s in j["suspicious_constructs"][:3]], ["forbidden_call", "symbol", "source"])
        self.assertEqual((len(j["suspicious_constructs"]), j["suspicious_constructs_omitted"]), (judge.SUSPICIOUS_MAX, 23))
        self.assertEqual(j["suspicious_constructs_by_type"], {"forbidden_call": 1, "unknown": 1, "source": 120, "symbol": 1})

    def test_fixed_metric_read_on_verification_alone(self):
        """ruche-0117: a fixed metric that no scenario computes from its timed outputs (the ratio, here the base's scenario
        returns none) is flagged in judge.json and never beyond the noise, even where the sign test says so; the toy's own
        ratio, read on its timed outputs, is not flagged."""
        base = os.path.join(self.workdir, "without-ratio")
        if not os.path.isdir(base):
            shutil.copytree(self.base, base)
            path = toy_file(base, "plugin")
            with open(path, encoding="utf-8") as f:
                text = f.read()
            with open(path, "w", encoding="utf-8") as f:
                f.write(replace_with(text, ', ratio=sum(handled) / compressed if compressed else None)', ")"))
        true_one = stats.sign_test
        with mock.patch.object(judge.stats, "sign_test", side_effect=lambda a, b, direction: dict(true_one(a, b, direction), beyond_noise=True)):
            honest_one, without_ratio = self.run_the_judge()[0], self.run_the_judge(base=base)[0]
        self.assertEqual(honest_one["judge"]["verification"]["fixed_without_measurement"], [])
        self.assertEqual(without_ratio["judge"]["verification"]["fixed_without_measurement"], ["ratio"])
        for report_, only_this in ((honest_one, False), (without_ratio, True)):
            ratio = report_["metrics"]["ratio"]
            self.assertEqual((ratio["verification_only"], ratio["beyond_noise"]), (only_this, not only_this))
            self.assertTrue(report_["metrics"]["compression_throughput"]["beyond_noise"])
            self.assertFalse(report_["metrics"]["compression_throughput"]["verification_only"])

    def test_outputs_changed_after_fingerprint(self):
        """An output changed, added or removed after its container ended (here, while the next container runs) is refused."""
        def change(action):
            def after(emulated):
                before, last = emulated.containers[-2:] if len(emulated.containers) > 1 else (None, None)
                if emulated.changed_ones or not before or "verify" in before["labels"] + last["labels"] \
                        or before["variant"] != last["variant"]:
                    return
                emulated.changed_ones = True
                workdir = os.path.dirname(os.path.dirname(before["written"][0]))  # <workdir>/execution/outputs (ruche-0117)
                found_items = glob.glob(os.path.join(workdir, "*", before["labels"][0]))
                self.assertEqual(len(found_items), 1)  # the previous scenario's frozen folder, renamed <side>/<scenario>
                action(found_items[0])
            return after
        first = lambda d: sorted(os.path.join(r, n) for r, _, names in os.walk(d) for n in names)[0]  # noqa: E731
        for name, action in (("changed", lambda d: add_to(first(d), b"x")), ("removed", lambda d: os.remove(first(d))),
                            ("added", lambda d: add_to(os.path.join(d, "addition"), b""))):
            with self.subTest(name=name), mock.patch.object(EmulatedDocker, "changed_ones", False, create=True), \
                    self.assertRaises(reading.Refusal) as e:
                self.run_the_judge(change(action))
            self.assertIn("after their fingerprint" if name == "added" else "after its fingerprint", str(e.exception))


# ------------------------------------------------------------------ a stand-in for the GitHub CLI (the declared history)

# Stand-in for the GitHub CLI (`gh api repos/O/R/compare/BASE...HEAD --jq .status`), put first on PATH as TestFailClosed
# does with its tools. It logs its arguments and whether it got a token; FAKE_GH_STATE forces the answer, FAKE_GH_CODE
# its exit code, FAKE_GH_DELAY makes it slow; otherwise it answers from the ancestry in the repository FAKE_GH_REPO.
FAKE_GH = r'''#!/usr/bin/env python3
import os, re, subprocess, sys, time
with open(os.environ["FAKE_GH_LOG"], "a") as f:
    f.write(" ".join(sys.argv[1:]) + (" +token" if os.environ.get("GH_TOKEN") else "") + "\n")
time.sleep(float(os.environ.get("FAKE_GH_DELAY", "0")))
if os.environ.get("FAKE_GH_CODE", "0") != "0":
    sys.exit(int(os.environ["FAKE_GH_CODE"]))
if "FAKE_GH_BYTES" in os.environ:  # bytes that are not UTF-8
    sys.stdout.buffer.write(b"\xff\xfebehind\n")
    sys.exit(0)
if "FAKE_GH_STATE" in os.environ:
    print(os.environ["FAKE_GH_STATE"])
    sys.exit(0)
base, head = re.fullmatch(r"repos/[^/]+/[^/]+/compare/([^.]+)\.\.\.(.+)", sys.argv[2]).groups()
repo = ["git", "-C", os.environ["FAKE_GH_REPO"], "merge-base", "--is-ancestor"]
if base == head:
    print("identical")
elif subprocess.run(repo + [head, base]).returncode == 0:
    print("behind")
elif subprocess.run(repo + [base, head]).returncode == 0:
    print("ahead")
else:
    sys.exit(1)
'''


def fake_gh(folder):
    """Writes the stand-in gh into folder/bin; returns (PATH with it first, the log of its calls)."""
    os.makedirs(os.path.join(folder, "bin"), exist_ok=True)
    with open(os.path.join(folder, "bin", "gh"), "w", encoding="utf-8") as f:
        f.write(FAKE_GH)
    os.chmod(os.path.join(folder, "bin", "gh"), 0o755)
    return os.path.join(folder, "bin") + os.pathsep + os.environ["PATH"], os.path.join(folder, "gh.log")


# A judge's report: as judge.py writes it, with 100 suspicious constructs listed and 3 left out.
REPORT = {"repetitions": 10, "metrics": {"compression_throughput": {"gain": 0.25}}, "judge": {
    "version": 3, "common": judge.common_tag(), "source": "Bee-ruche/hive@" + "1" * 40, "base": "2" * 40, "head": "3" * 40,
    "project": "toy", "plugin": "ab" * 32, "code": 0, "outcome": "correct", "seed": "cd" * 16,
    "seed_origin": {"seed": "drawn", "order_seed": "drawn"}, "image": "bee-common-judge:0123456789abcdef",
    "image_id": "sha256:" + "ef" * 32, "suspicious_constructs_omitted": 3, "verification": {"outputs_compared": 57},
    "suspicious_constructs": [{"type": "source", "detail": f"pragma {i}"} for i in range(judge.SUSPICIOUS_MAX)]}}


class TestReport(unittest.TestCase):
    """report.py (ruche-0038): the report's figures are read strictly, and the report itself within bounds."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="bee-report-")
        self.path = os.path.join(self.dir, "judge.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_figures(self):
        data = json.dumps(REPORT).encode()
        self.assertEqual(report.digits(data)["suspects"], str(judge.SUSPICIOUS_MAX + 3))
        local = dict(REPORT, judge=dict(REPORT["judge"], base=None, head=None))  # judge.py run by hand: no commits named
        self.assertEqual([report.digits(json.dumps(local).encode())[k] for k in ("base", "head")], ["", ""])
        judge_ = REPORT["judge"]
        # (the section under the key « juge », as judges before judge-v4 wrote it, is not read: no judge section)
        wrong_one = [b"[]", b"{}", b"{\"judge\": []}", json.dumps({"juge": judge_}).encode(), b"\xff", json.dumps(dict(REPORT, judge={})).encode()]
        wrong_one += [json.dumps(dict(REPORT, judge=dict(judge_, **{key: value}))).encode() for key, value in (
            ("suspicious_constructs_omitted", -1), ("suspicious_constructs_omitted", True), ("suspicious_constructs_omitted", "3"),
            ("suspicious_constructs", "abc"), ("suspicious_constructs", None), ("plugin", "x"), ("plugin", "AB" * 32),
            ("seed", ""), ("seed", 12), ("base", "main"), ("head", "3" * 39), ("verification", {"outputs_compared": -1}),
            ("verification", {"outputs_compared": 1.5}), ("verification", {"outputs_compared": True}), ("verification", {}))]
        for data in wrong_one:
            with self.subTest(data=data[:80]), self.assertRaises(ValueError):
                report.digits(data)

    def test_verify_requires_code_0_and_the_judged_commits(self):
        """ruche-0117: report.py --verify also checks the published code (0) and the report's base and head against the judged
        commits it is given; any other exit than 0 blocks the verdict."""
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(REPORT, f)
        published_ones, commits = report.publish(self.path, "0"), (REPORT["judge"]["base"], REPORT["judge"]["head"])
        self.assertEqual(report.verify(self.path, published_ones, *commits)["judge"]["plugin"], "ab" * 32)
        without_code = {k: v for k, v in published_ones.items() if k != "code"}
        for published_, base, head in ((dict(published_ones, code="1"), *commits), (dict(published_ones, code="2"), *commits), (without_code, *commits),
                                      (published_ones, commits[1], commits[0]), (published_ones, "0" * 40, commits[1]), (published_ones, commits[0], ""),
                                      (published_ones, "AB" * 20, commits[1]), (published_ones, None, commits[1]),
                                      (published_ones, commits[0], commits[1] + "\n")):
            with self.subTest(code=published_.get("code"), base=base, head=head), self.assertRaises(report.Gap):
                report.verify(self.path, published_, base, head)
        outputs = os.path.join(self.dir, "published.json")
        with open(outputs, "w") as f:
            json.dump(published_ones, f)
        command = [sys.executable, os.path.join(HERE, "report.py"), self.path, "--verify", outputs]
        self.check_the_seeds(published_ones, commits)
        for arguments, code in ((["--base", commits[0], "--head", commits[1]], 0), (["--base", commits[0], "--head", commits[0]], 1),
                                ([], 2), (["--base", commits[0]], 2), (["--head", commits[1], "--base", commits[0]], 2)):
            with self.subTest(arguments=arguments):
                self.assertEqual(subprocess.run(command + arguments, capture_output=True).returncode, code)

    def check_the_seeds(self, published_ones, commits):
        """ruche-0136: a report with a seed given on the command line (a local reproduction), or that does not say where its
        seeds came from, is never taken for a judgement: --verify refuses it, its figures and SHA-256 published or not."""
        for origins in ({"seed": "given", "order_seed": "drawn"}, {"seed": "drawn", "order_seed": "given"},
                         {"seed": "drawn"}, None, "drawn", {"seed": "drawn", "order_seed": "drawn", "x": 1}):
            reproduction = dict(REPORT, judge=dict(REPORT["judge"], seed_origin=origins))
            if origins is None:
                del reproduction["judge"]["seed_origin"]
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(reproduction, f)
            with self.subTest(origins=origins), self.assertRaisesRegex(report.Gap, "seed"):
                report.verify(self.path, report.publish(self.path, "0"), *commits)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(REPORT, f)

    def test_verify_refuses_a_report_changed_after_it_was_published(self):
        """ruche-0038: report.py --code publishes judge.json's SHA-256 and key figures; report.py --verify, given those figures,
        refuses a report changed in between (its bytes, a figure, its suspects), a published figure changed, a link, or no report."""
        data = json.dumps(REPORT, indent=2).encode()
        with open(self.path, "wb") as f:
            f.write(data)
        with contextlib.redirect_stdout(io.StringIO()) as printed:
            self.assertEqual(report.main([self.path, "--code", "0"]), 0)
        published = dict(line.split("=", 1) for line in printed.getvalue().splitlines())
        self.assertEqual(published, {"code": "0", "fingerprint": hashlib.sha256(data).hexdigest(), "suspects": "103",
                                     "outputs_compared": "57", "plugin": "ab" * 32, "seed": "cd" * 16,
                                     "base": REPORT["judge"]["base"], "head": REPORT["judge"]["head"]})
        outputs = os.path.join(self.dir, "published.json")
        with open(outputs, "w") as f:
            json.dump(published, f)
        commits = [REPORT["judge"]["base"], REPORT["judge"]["head"]]
        command = [sys.executable, os.path.join(HERE, "report.py"), self.path, "--verify", outputs, "--base", commits[0], "--head", commits[1]]
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.assertEqual(report.verify(self.path, published, *commits)["judge"]["plugin"], "ab" * 32)
        other = json.loads(json.dumps(REPORT))
        other["judge"]["verification"]["outputs_compared"] = 58
        without_suspects = dict(REPORT, judge=dict(REPORT["judge"], suspicious_constructs=[], suspicious_constructs_omitted=0))
        changed = [json.dumps(REPORT).encode(), data + b"\n", data.replace(b'"gain": 0.25', b'"gain": 0.35'),
                   json.dumps(other, indent=2).encode(), json.dumps(without_suspects, indent=2).encode(), b""]
        for changed_one in changed:
            with self.subTest(changed_one=changed_one[:60]):
                with open(self.path, "wb") as f:
                    f.write(changed_one)
                self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1 if changed_one else 2)
                with self.assertRaises((report.Gap, ValueError)):
                    report.verify(self.path, published, *commits)
        with open(self.path, "wb") as f:
            f.write(data)
        for key, value in (("fingerprint", ""), ("fingerprint", "0" * 64), ("suspects", "100"), ("head", REPORT["judge"]["base"])):
            with self.subTest(published=key), self.assertRaises(report.Gap):
                report.verify(self.path, dict(published, **{key: value}), *commits)
        os.remove(self.path)
        os.symlink(outputs, self.path)
        self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
        os.remove(self.path)
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 1)

    def test_a_refusal_needs_no_report(self):
        """ruche-0136: a refusal (code 1) is published as 1 whatever state its report is in (none, cut short, malformed, not a
        regular file), unless the report states another code; a code 0 still needs its report, whole and checked."""
        def published(code):
            with contextlib.redirect_stderr(io.StringIO()):
                return report.publish(self.path, code)["code"]
        refusal = json.dumps({"judge": dict(REPORT["judge"], code=1, outcome="refusal", reason="m")})
        for content, expected in ((None, "1"), ("", "1"), (refusal[:-7], "1"), ("[1]", "1"), ('{"judge": 3}', "1"), (refusal, "1"),
                                 ("\xff", "1"), (json.dumps(REPORT), "2"), (refusal.replace('"refusal"', '"correct"'), "2"),
                                 (refusal.replace('"code": 1', '"code": 2'), "2"), (refusal.replace('"code": 1', '"code": true'), "2")):
            with contextlib.suppress(FileNotFoundError):
                os.remove(self.path)
            if content is not None:
                with open(self.path, "w", encoding="utf-8", errors="surrogateescape") as f:
                    f.write(content.replace("\xff", "\udcff"))
            with self.subTest(content=content and content[:40]):
                self.assertEqual(published("1"), expected)
        os.remove(self.path)
        os.mkfifo(self.path)
        self.assertEqual((published("1"), published("0"), published("2")), ("1", "2", "2"))
        os.remove(self.path)
        os.symlink(self.dir, self.path)
        self.assertEqual((published("1"), published("0")), ("1", "2"))

    def test_a_code_0_or_2_is_published_only_as_its_report_says(self):
        """ruche-0117, ruche-0136: a code 0 is published as 0 only with its report, whole, checked and stating code 0; any other
        report (none, empty, cut short, unreadable, stating another code) publishes 2. A code 2 stays 2 whatever its report says;
        and a code 1 whose report states a success or no refusal publishes 2."""
        def published(code, content):
            with contextlib.suppress(FileNotFoundError):
                os.remove(self.path)
            if content is not None:
                with open(self.path, "w", encoding="utf-8") as f:
                    f.write(content)
            with contextlib.redirect_stderr(io.StringIO()):
                return report.publish(self.path, code)
        good = json.dumps(REPORT, indent=2)
        refusal, fault = (json.dumps({"judge": dict(REPORT["judge"], code=c, outcome=o, reason="m")})
                          for c, o in ((1, "refusal"), (2, "environment_error")))
        fake = json.dumps({"judge": dict(REPORT["judge"], code=1, outcome="correct")})
        for code, content, expected in (("0", good, "0"), ("0", None, "2"), ("0", "", "2"), ("0", "{}", "2"), ("0", good[:-1], "2"),
                                        ("0", fault, "2"), ("0", refusal, "2"), ("2", None, "2"), ("2", fault, "2"), ("2", refusal, "2"),
                                        ("2", good, "2"), ("1", fake, "2"), ("1", good, "2"), ("3", good, "2"), ("", None, "2")):
            with self.subTest(code=code, content=content and content[:40]):
                figures = published(code, content)
                self.assertEqual(figures["code"], expected)
                self.assertEqual(figures["fingerprint"] != "", expected == "0")
                self.assertEqual(set(figures), {"code", *report.FORMATS})

    def test_reading_bounded(self):
        self.assertIsNone(report.read(self.path))
        with contextlib.redirect_stdout(io.StringIO()) as output_text:
            self.assertEqual(report.main([self.path]), 0)
        self.assertEqual(output_text.getvalue(), "".join(f"{k}=\n" for k in report.FORMATS))
        with open(self.path, "wb") as f:
            f.write(b"x" * 101)
        with mock.patch.object(report, "REPORT_MAX", 100), self.assertRaises(ValueError):
            report.read(self.path)
        os.remove(self.path)
        os.mkfifo(self.path)
        with self.assertRaises(ValueError):  # not a regular file: never read, never waited for
            report.read(self.path)
        os.remove(self.path)
        os.symlink("/etc/hostname", self.path)
        with self.assertRaises(OSError):
            report.read(self.path)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(report.main([self.path]), 2)
            self.assertEqual(report.main([]), 2)


OCI = "docker: Error response from daemon: failed to create task for container: OCI runtime create failed: runc create failed\n"

# Stand-in for the docker client: logs its arguments; « image inspect » answers FAKE_DOCKER_ID; « run » writes FAKE_DOCKER_MIB
# MiB on each standard stream (stdout: A, B…; stderr: a, b…), then, with FAKE_DOCKER_ENDLESS, writes on without end.
FAKE_DOCKER = r"""#!/usr/bin/env python3
import os, sys
with open(os.environ["FAKE_DOCKER_LOG"], "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\n")
if sys.argv[1:3] == ["image", "inspect"]:
    print(os.environ.get("FAKE_DOCKER_ID", ""))
if sys.argv[1] == "inspect":  # ruche-0136: Docker's record of the container (FAKE_DOCKER_STATE, JSON), or none (no container)
    print(os.environ.get("FAKE_DOCKER_STATE", '{"Status": "exited", "Error": "", "ExitCode": 0}'))
    sys.exit(int(os.environ.get("FAKE_DOCKER_INSPECT", "0")))
if sys.argv[1] != "run":
    sys.exit(0)
sys.stdin.read()
for i in range(int(os.environ.get("FAKE_DOCKER_MIB", "0"))):
    sys.stdout.buffer.write(bytes([65 + i % 26]) * (1 << 20))
    sys.stderr.buffer.write(bytes([97 + i % 26]) * (1 << 20))
while os.environ.get("FAKE_DOCKER_ENDLESS"):
    sys.stderr.buffer.write(b"x" * 65536)
sys.stderr.write(os.environ.get("FAKE_DOCKER_ERROR", ""))
sys.exit(int(os.environ.get("FAKE_DOCKER_CODE", "0")))
"""


class TestBounds(unittest.TestCase):
    """ruche-0038: what a container writes is bounded (file size, no log on the host's disk) and the host reads it within
    bounds (the start of its standard output, the end of its standard error; outputs never beyond reading.OUTPUT_FILE_MAX)."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="bee-bounds-")
        os.makedirs(os.path.join(self.dir, "bin"))
        with open(os.path.join(self.dir, "bin", "docker"), "w", encoding="utf-8") as f:
            f.write(FAKE_DOCKER)
        os.chmod(os.path.join(self.dir, "bin", "docker"), 0o755)
        self.log = os.path.join(self.dir, "docker.log")
        self.env = mock.patch.dict(os.environ, {"PATH": os.path.join(self.dir, "bin") + os.pathsep + os.environ["PATH"],
                                                "FAKE_DOCKER_LOG": self.log})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_container_limits(self):
        self.assertEqual(container.Docker.BOUNDS, ["--ulimit", f"fsize={reading.OUTPUT_FILE_MAX}", "--log-driver", "none"])
        container.Docker("sha256:" + "0" * 64).launch(["true"], [(self.dir, "/outputs", False)])
        with open(self.log) as f:
            arguments = f.readline().split()  # the run (ruche-0136: then inspect and rm)
        self.assertEqual(arguments[arguments.index("--ulimit"):arguments.index("--ulimit") + 4], container.Docker.BOUNDS)
        self.assertEqual(arguments[-2:], ["sha256:" + "0" * 64, "true"])  # the image by its id

    def test_streams_read_within_bounds(self):
        tracemalloc.start()
        try:
            with mock.patch.dict(os.environ, {"FAKE_DOCKER_MIB": "40"}):
                r = container.Docker("i").launch(["x"], [], entry=b"token\n", timeout_seconds=120)
            points_to = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, b"A" * (1 << 20), bytes([97 + 39 % 26]) * (1 << 20)))
        self.assertLess(points_to, 12 << 20)  # 80 MiB written, a few MiB held

    def test_endless_writer_stopped_at_its_deadline(self):
        beginning = time.monotonic()
        with mock.patch.dict(os.environ, {"FAKE_DOCKER_ENDLESS": "1"}), self.assertRaises(reading.Refusal):
            container.Docker("i").launch(["x"], [], timeout_seconds=2)
        self.assertLess(time.monotonic() - beginning, 30)
        with open(self.log) as f:
            self.assertRegex(f.read(), r"\nkill bee-judge-[0-9a-f]{12}\n")

    def test_deadline_without_a_started_container_is_a_machine_failure(self):
        """ruche-0136: at its deadline, Docker's record is read before the container is removed: never started (no record, or
        still created) is a failure of the machine; started, the deadline stays a refusal."""
        for env, expected_one in (({"FAKE_DOCKER_INSPECT": "1"}, reading.MachineFailure), ({"FAKE_DOCKER_STATE": '{"Status": "created"}'}, reading.MachineFailure),
                              ({"FAKE_DOCKER_STATE": '{"Status": "running"}'}, reading.Refusal), ({}, reading.Refusal)):
            with self.subTest(env=env), mock.patch.dict(os.environ, dict(env, FAKE_DOCKER_ENDLESS="1")), self.assertRaises(expected_one):
                container.Docker("i").launch(["x"], [], timeout_seconds=1)
        with open(self.log) as f:
            self.assertEqual(re.findall(r"^(inspect|kill|rm) ", f.read(), re.M), ["inspect", "kill", "rm"] * 4)

    def test_machine_failure_is_an_environment_error(self):
        """ruche-0136: Docker's own record of the container decides, never its code or error stream: a daemon out of reach, a
        runtime that cannot create the container (OCI), a container whose code is not its process's or whose record is
        unreadable is a failure of the machine (MachineFailure, a JudgeError: code 2), each container removed after it ends."""
        state = lambda status, code, error="": json.dumps({"Status": status, "Error": error, "ExitCode": code})  # noqa: E731
        for env in ({"FAKE_DOCKER_CODE": "125", "FAKE_DOCKER_ERROR": OCI, "FAKE_DOCKER_INSPECT": "1", "FAKE_DOCKER_STATE": ""},
                    {"FAKE_DOCKER_CODE": "127", "FAKE_DOCKER_ERROR": OCI, "FAKE_DOCKER_STATE": state("created", 127, OCI)},
                    {"FAKE_DOCKER_CODE": "1", "FAKE_DOCKER_ERROR": "failed to connect to the docker API", "FAKE_DOCKER_INSPECT": "1"},
                    {"FAKE_DOCKER_CODE": "125", "FAKE_DOCKER_STATE": state("exited", 0)}, {"FAKE_DOCKER_STATE": "{"},
                    {"FAKE_DOCKER_STATE": state("running", 0)}):
            with self.subTest(env=env), mock.patch.dict(os.environ, env), contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaisesRegex(reading.MachineFailure, "^failure of the judge's machine") as fault:
                container.Docker("i").launch(["x"], [])
            self.assertNotRegex(str(fault.exception), "runc|daemon|API")  # what the error stream holds stays out of the reason
        with open(self.log) as f:
            self.assertEqual(len(re.findall(r"^rm -f bee-judge-[0-9a-f]{12}$", f.read(), re.M)), 6)
        self.assertTrue(issubclass(reading.MachineFailure, reading.JudgeError))

    def test_judged_code_that_mimics_a_failure_stays_a_refusal(self):
        """ruche-0136: a container that ran to its end, exiting 125 with a daemon's error on its stream (both of which the
        judged code can write), is no failure of the machine: its code is returned, and in an execution it is a refusal."""
        env = {"FAKE_DOCKER_CODE": "125", "FAKE_DOCKER_ERROR": OCI, "FAKE_DOCKER_STATE": json.dumps({"Status": "exited", "Error": "",
                                                                                                    "ExitCode": 125})}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(container.Docker("i").launch(["x"], []).returncode, 125)
            with self.assertRaises(reading.Refusal):
                container.Execution(container.Docker("i"), "/c", {"B": "/b"}, self.dir).launch(
                    "B", "/e", os.path.join(self.dir, "s"), [("verify", [container.HARNESS, "verify", "/inputs", "/outputs"])])

    def test_dockers_record_of_a_memory_kill_is_handed_back(self):
        """What launch returns says whether Docker's own record of the container says the kernel ended it for its memory
        (`OOMKilled`), and nothing else does: the code (137 either way) and the streams are the judged code's to write."""
        record = lambda **more: json.dumps({"Status": "exited", "Error": "", "ExitCode": 137, **more})  # noqa: E731
        for state, expected in ((record(OOMKilled=True), True), (record(OOMKilled=False), False), (record(), False),
                                (record(OOMKilled="true"), False), (record(OOMKilled=1), False)):
            with self.subTest(state=state), mock.patch.dict(os.environ, {"FAKE_DOCKER_CODE": "137", "FAKE_DOCKER_STATE": state,
                                                                          "FAKE_DOCKER_ERROR": "OOMKilled: true\n"}):
                ran = container.Docker("i").launch(["x"], [])
            self.assertEqual((ran.returncode, ran.oom_killed), (137, expected))
        with mock.patch.dict(os.environ, {}):
            self.assertIs(container.Docker("i").launch(["x"], []).oom_killed, False)

    def test_judge_json_says_the_environment_error(self):
        """ruche-0136: the judge stopped by a failure of the machine exits with 2, and its judge.json says so (code 2,
        environment_error, machine_failure); stopped by a refusal, 1 and refusal; report.py publishes the code only when the
        report agrees with it."""
        path = os.path.join(self.dir, "results", "judge.json")
        env = {"FAKE_DOCKER_ID": "sha256:" + "a" * 64, "FAKE_DOCKER_CODE": "125", "FAKE_DOCKER_ERROR": OCI, "FAKE_DOCKER_INSPECT": "1"}
        r = subprocess.run([sys.executable, os.path.join(HERE, "judge.py"), "--tooling", TOY, "--source-a", TOY, "--source-b",
                            TOY, "--json", path, "--workdir", self.dir, "--head", "3" * 40], env=dict(os.environ, **env),
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 2, r.stderr)
        with open(path, encoding="utf-8") as f:
            j = json.load(f)["judge"]
        self.assertEqual((j["code"], j["outcome"], j["machine_failure"], j["head"], j["common"]),
                         (2, "environment_error", True, "3" * 40, judge.common_tag()))
        self.assertIn("failure of the judge's machine", j["reason"])
        self.assertEqual([report.publish(path, c)["code"] for c in "012"], ["2", "2", "2"])
        with mock.patch.dict(judge.FAILURE, json=path, judge={}), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(judge.stop_it(1, "judge: REFUSAL: B"), 1)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["judge"], {"code": 1, "outcome": "refusal", "machine_failure": False, "reason": "judge: REFUSAL: B"})
        self.assertEqual([report.publish(path, c)["code"] for c in "012"], ["2", "1", "2"])

    def test_a_refusal_stays_a_refusal_whatever_its_message_holds(self):
        """ruche-0136: a refusal quoting a name that is not UTF-8 exits with 1, its judge.json whole and saying refusal, and
        report.py publishes 1; a report that cannot be written leaves none, neither partial nor stale."""
        self.assertEqual(reading.clean("a\udcffb\ud800"), "a?b?")
        path, source_b = os.path.join(self.dir, "results", "judge.json"), os.path.join(os.fsencode(self.dir), b"B\xff")
        os.mkdir(source_b)
        r = subprocess.run([sys.executable, os.path.join(HERE, "judge.py"), "--tooling", TOY, "--source-a", TOY, "--source-b",
                            source_b, "--json", path, "--workdir", self.dir], capture_output=True, timeout=300,
                           env=dict(os.environ, FAKE_DOCKER_ID="sha256:" + "a" * 64))
        self.assertEqual(r.returncode, 1, r.stderr)
        with open(path, encoding="utf-8") as f:
            self.assertEqual((lambda j: (j["code"], j["outcome"], j["machine_failure"]))(json.load(f)["judge"]), (1, "refusal", False))
        output_text = subprocess.run([sys.executable, os.path.join(HERE, "report.py"), path, "--code", "1"], capture_output=True, text=True)
        self.assertEqual(output_text.stdout.splitlines()[0], "code=1")
        with mock.patch.dict(judge.FAILURE, json=path, judge={}), contextlib.redirect_stderr(io.StringIO()), \
                mock.patch.object(os, "replace", side_effect=OSError("disk full")):
            self.assertEqual(judge.stop_it(1, "judge: REFUSAL: B\udcff"), 1)
        self.assertEqual(os.listdir(os.path.dirname(path)), [])

    def test_image_id(self):
        with mock.patch.dict(os.environ, {"FAKE_DOCKER_ID": "sha256:" + "a" * 64}):
            self.assertEqual(container.image_id("bee-common-judge:x"), "sha256:" + "a" * 64)
        for wrong_one in ("", "a" * 64, "sha256:" + "A" * 64, "sha256:" + "a" * 63, "sha256:" + "a" * 64 + "\nx"):
            with self.subTest(wrong_one=wrong_one), mock.patch.dict(os.environ, {"FAKE_DOCKER_ID": wrong_one}), \
                    self.assertRaises(reading.JudgeError):
                container.image_id("bee-common-judge:x")

    def test_outputs_never_read_beyond_the_bound(self):
        with open(os.path.join(self.dir, "output"), "wb") as f:
            f.write(b"x" * 101)
        with mock.patch.object(reading, "OUTPUT_FILE_MAX", 100), self.assertRaises(reading.Refusal):
            reading.read_output(self.dir, "output", maximum=1 << 30)
        self.assertEqual(reading.read_output(self.dir, "output", maximum=1 << 30), b"x" * 101)

    def test_commits_named_in_full(self):
        for value in ("abc", "2" * 39, "2" * 40 + "\n", "main", "A" * 40):
            for option in ("--base", "--head"):
                with self.subTest(option=option, value=value), contextlib.redirect_stderr(io.StringIO()), \
                        self.assertRaises(SystemExit):
                    judge.main(["--tooling", TOY, option, value])


def git_test(repo, *args):
    return subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", "-c", "protocol.file.allow=always"]
                          + list(args), capture_output=True, text=True, check=True).stdout.strip()


def toy_repo_with_history(workdir, toy=TOY):
    """An origin whose older commit X has another rle.c, and a base cloned from it without history (as actions/checkout
    does): X's objects are not in the base. Returns (origin, base, X, rle.c at X, full repository, a commit off the
    base's ancestry)."""
    source, origin_of, base = (os.path.join(workdir, n) for n in ("source", "origin.git", "base"))
    shutil.copytree(toy, source, ignore=shutil.ignore_patterns("__pycache__"))
    with open(os.path.join(source, "rle.c"), "a", encoding="utf-8") as f:
        f.write("/* rle.c as it was at the corpus commit */\n")
    subprocess.run(["git", "init", "-q", "-b", "main", source], check=True)
    git_test(source, "add", "-A")
    git_test(source, "commit", "-qm", "X")
    commit = git_test(source, "rev-parse", "HEAD")
    with open(os.path.join(source, "rle.c"), "rb") as f:
        old = f.read()
    git_test(source, "checkout", "-qb", "elsewhere")
    git_test(source, "commit", "-qm", "off the base's ancestry", "--allow-empty")
    elsewhere = git_test(source, "rev-parse", "HEAD")
    git_test(source, "checkout", "-q", "main")
    shutil.copyfile(os.path.join(TOY, "rle.c"), os.path.join(source, "rle.c"))
    git_test(source, "commit", "-qam", "Y")
    subprocess.run(["git", "clone", "-q", "--bare", source, origin_of], check=True)
    subprocess.run(["git", "clone", "-q", "--depth", "1", "file://" + origin_of, base], check=True)
    return origin_of, base, commit, old, source, elsewhere


@unittest.skipUnless(shutil.which("git"), "git required")
class TestHistory(unittest.TestCase):
    """The declared history (--history-only --history): commits of the base's ancestry only (compare API, gh replaced by a stand-in),
    checked before any fetch and before the plugin is loaded, fetched within one time budget; judging then runs
    without any git transport (ruche-0024)."""

    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="bee-history-")
        self.origin_of, self.base, self.commit, self.old, source, self.elsewhere = toy_repo_with_history(self.workdir)
        path, self.gh_log = fake_gh(self.workdir)
        self.env = mock.patch.dict(os.environ, {"PATH": path, "FAKE_GH_LOG": self.gh_log, "FAKE_GH_REPO": source,
                                                "GITHUB_REPOSITORY": "Bee-ruche/toyBee"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shutil.rmtree(self.workdir, ignore_errors=True)

    def present(self, commit):
        return subprocess.run(["git", "-C", self.base, "cat-file", "-e", commit + "^{commit}"], capture_output=True).returncode == 0

    def test_declared_commit_is_read_without_network(self):
        self.assertEqual(judge.fetch_history(self.base, f" {self.commit}\n{self.commit} ", "token"), [self.commit])
        base = git_test(self.base, "rev-parse", "HEAD")
        with open(self.gh_log) as f:
            self.assertEqual(f.read(), f"api repos/Bee-ruche/toyBee/compare/{base}...{self.commit} --jq .status +token\n")
        os.rename(self.origin_of, self.origin_of + ".gone")  # from now on, no origin to fetch from
        plugin = toy_plugin.Project({"corpus_commit": self.commit})
        with mock.patch.dict(os.environ, {"GIT_ALLOW_PROTOCOL": "none"}):
            corpus = plugin.corpus(self.base)
        self.assertEqual(corpus[-1][1], self.old)
        self.assertEqual(plugin.VERIFICATION["history"], f"{self.commit}:rle.c ({len(self.old)} bytes)")

    def test_undeclared_commit_fails_cleanly(self):
        with self.assertRaises(reading.JudgeError) as e:
            toy_plugin.Project({"corpus_commit": self.commit}).corpus(self.base)
        self.assertIn("history", str(e.exception))
        with self.assertRaises(reading.JudgeError):
            toy_plugin.Project({"corpus_commit": "HEAD"})

    def test_only_the_base_ancestry_is_fetched(self):
        """S3: a commit off the base's ancestry, a commit of another repository, an API error: refused before any fetch."""
        for commits, env in (([self.elsewhere], {}), ([self.commit, self.elsewhere], {}),
                             (["0123456789abcdef0123456789abcdef01234567"], {}), ([self.commit], {"FAKE_GH_CODE": "1"}),
                             ([self.commit], {"FAKE_GH_STATE": "ahead"}), ([self.commit], {"FAKE_GH_STATE": "diverged"}),
                             ([self.commit], {"FAKE_GH_STATE": ""}), ([self.commit], {"GITHUB_REPOSITORY": ""}),
                             ([self.commit], {"GITHUB_REPOSITORY": "a/.."}), ([self.commit], {"GITHUB_REPOSITORY": "../x/y"})):
            with self.subTest(commits=commits, env=env), mock.patch.dict(os.environ, env):
                with self.assertRaises(reading.JudgeError) as e:
                    judge.fetch_history(self.base, " ".join(commits))
                self.assertIn("history:", str(e.exception))
                self.assertFalse(any(self.present(c) for c in commits))

    def test_declared_history_is_checked(self):
        for text in ("abc", self.commit[:39], self.commit.upper(), "--upload-pack=touch /tmp/x", f"{self.commit}:refs/x",
                      " ".join(f"{i:040x}" for i in range(judge.HISTORY_MAX + 1))):
            with self.subTest(text=text):
                with mock.patch.object(judge.subprocess, "run") as run, self.assertRaises(reading.JudgeError):
                    judge.fetch_history(self.base, text)
                run.assert_not_called()
        with mock.patch.object(judge.subprocess, "run") as run:
            self.assertEqual(judge.fetch_history(self.base, ""), [])
        run.assert_not_called()

    def test_output_that_is_not_utf8(self):
        """A byte that is not UTF-8 from gh (or git) gives a clean judge error, not a decoding traceback."""
        with mock.patch.dict(os.environ, {"FAKE_GH_BYTES": "1"}), self.assertRaises(reading.JudgeError) as e:
            judge.fetch_history(self.base, self.commit)
        self.assertIn("not in the ancestry", str(e.exception))
        self.assertFalse(self.present(self.commit))

    def test_time_budget(self):
        """One budget for every check and fetch: exceeded, a clean judge error, nothing fetched."""
        with mock.patch.dict(os.environ, {"FAKE_GH_DELAY": "5"}), self.assertRaises(reading.JudgeError) as e:
            judge.fetch_history(self.base, self.commit, budget=1)
        self.assertIn("budget of 1 s", str(e.exception))
        self.assertFalse(self.present(self.commit))
        with mock.patch.object(judge.subprocess, "run", side_effect=FileNotFoundError("gh")), self.assertRaises(reading.JudgeError):
            judge.fetch_history(self.base, self.commit)

    def test_history_step_from_the_command_line(self):
        """--history-only checks and fetches, without Docker and without loading the plugin; a refusal is a
        judge error (code 2) without traceback."""
        judge_py = [sys.executable, os.path.join(HERE, "judge.py"), "--tooling", self.base, "--history-only"]
        r = subprocess.run(judge_py + ["--history", self.elsewhere], capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 2)
        self.assertTrue(r.stderr.startswith("judge: error: history: "), r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        with open(toy_file(self.base, "plugin"), "a", encoding="utf-8") as f:
            f.write("\nraise SystemExit('the plugin was loaded')\n")
        r = subprocess.run(judge_py + ["--history", self.commit], capture_output=True, text=True, timeout=120)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, self.commit + "\n", ""))
        self.assertTrue(self.present(self.commit))

    def test_modes_history_image_judging(self):
        """--history-only checks and fetches the history with the token and never loads the plugin;
        --image-only neither reads the history nor needs a token, and refuses --history; judging refuses every
        git transport before the plugin is loaded. GH_TOKEN is out of os.environ before any plugin load (defence in
        depth: a caller gives the token to the history step alone)."""
        seen_items = []

        def load(tooling, options):
            seen_items.append(("plugin", os.environ.get("GIT_ALLOW_PROTOCOL"), os.environ.get("GH_TOKEN")))
            return toy_plugin.Project({}), "fingerprint"

        def history(tooling, text, token=None):
            seen_items.append(("history", text, token))
            return text.split()
        case_of = [(["--history-only", "--history", self.commit], {"GH_TOKEN": "secret"},
                [("history", self.commit, "secret")]),
               (["--image-only"], {}, [("plugin", None, None), ("image",)]),
               (["--image-only"], {"GH_TOKEN": "secret"}, [("plugin", None, None), ("image",)]),
               (["--source-a", "a", "--source-b", "b"], {"GH_TOKEN": "secret"}, [("plugin", "none", None)])]
        for options, env, expected in case_of:
            with self.subTest(options=options, env=env):
                seen_items.clear()
                with mock.patch.dict(os.environ, env), mock.patch.object(judge.shutil, "which", return_value="/usr/bin/docker"), \
                        mock.patch.object(judge, "load_plugin", side_effect=load), \
                        mock.patch.object(judge, "fetch_history", side_effect=history), \
                        mock.patch.object(judge.container, "build_image", side_effect=lambda *a: seen_items.append(("image",)) or "i"), \
                        mock.patch.object(judge.tempfile, "mkdtemp", side_effect=reading.JudgeError("stop")), \
                        contextlib.redirect_stdout(io.StringIO()):
                    os.environ.pop("GIT_ALLOW_PROTOCOL", None)
                    try:
                        judge.main(["--tooling", self.base] + options)
                    except reading.JudgeError:
                        pass
                self.assertEqual(seen_items, expected)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            judge.main(["--tooling", self.base, "--image-only", "--history", self.commit])
        with mock.patch.object(judge.shutil, "which", return_value=None), contextlib.redirect_stdout(io.StringIO()), \
                mock.patch.object(judge, "fetch_history", return_value=[]) as call:  # no Docker needed for it
            self.assertEqual(judge.main(["--tooling", self.base, "--history-only"]), 0)
        call.assert_called_once()
        with mock.patch.dict(os.environ, {"GIT_ALLOW_PROTOCOL": "none"}), self.assertRaises(reading.JudgeError):
            judge.fetch_history(self.base, self.commit)


# ------------------------------------------------------------------ meta-tests of the analysis (built on the host, no Docker)

LOCAL_TOOLS = all(shutil.which(o) for o in ("sh", "cc", "nm", "objdump"))


class DockerLocal:
    """Stand-in for container.Docker: runs the judge's build and analysis commands on the host, each mount target
    replaced by its host path. Only the toy project and the fixtures below are built this way; nothing built is run."""

    def __init__(self, tools=None):
        self.tools = tools

    def launch(self, command, mounts, pids=2, entry=None, timeout_seconds=3600):
        targets = {target: host for host, target, _ in mounts}
        reason = re.compile("|".join(re.escape(c) for c in sorted(targets, key=len, reverse=True)))
        env = dict(os.environ)
        if self.tools:
            env["PATH"] = self.tools + os.pathsep + env["PATH"]
        return subprocess.run([reason.sub(lambda m: targets[m.group(0)], c) for c in command], capture_output=True,
                              env=env, timeout=timeout_seconds)


def build_toy(workdir, label="B", addition="", docker=None):
    """The toy project, `addition` appended to rle.c, built and surveyed as the judge does; returns (surveys, sources)."""
    plugin = toy_plugin.Project({})
    os.makedirs(workdir)
    repo = os.path.join(workdir, "repo")
    shutil.copytree(TOY, repo, ignore=shutil.ignore_patterns("bee", "__pycache__"))
    with open(os.path.join(repo, "rle.c"), "a", encoding="utf-8") as f:
        f.write(addition)
    sources = judge.copy_sources(repo, os.path.join(workdir, "sources"), plugin.SOURCES, plugin.REQUIRED_SOURCES)
    tools = judge.copy_tooling(TOY, TOY, os.path.join(workdir, "tooling"), plugin)
    surveys = judge.build(docker or DockerLocal(), plugin, sources, tools, os.path.join(workdir, "build"),
                              label, workdir)
    return surveys, sources


def asm_bytes(hex_digits, section=".text", end="ret"):
    return '__asm__("%s\\n.p2align 4\\nrle_seeded_%s:\\n.byte %s\\n%s\\n.previous\\n");\n' % (
        section, hex_digits, ", ".join("0x" + hex_digits[i:i + 2] for i in range(0, len(hex_digits), 2)), end)


SEEDED_CONSTRUCTS = {
    "syscall": "0f05", "sysenter": "0f34", "int": "cd80", "rdtsc": "0f31", "rdtscp": "0f01f9", "rdpmc": "0f33",
    "cpuid": "0fa2", "xgetbv": "0f01d0", "rdrand": "0fc7f0", "rdseed": "0fc7f8", "rdpid": "f30fc7f8",
    "valgrind_preamble": "48c1c70348c1c70d48c1c73d48c1c733",
}
# Every x86-64 prefix byte: legacy prefixes, then REX.
BYTE_PREFIXES = ["26", "2e", "36", "3e", "64", "65", "66", "67", "f0", "f2", "f3"] + [f"{r:02x}" for r in range(0x40, 0x50)]
# variant: (bytes before the construct, length it is padded to, bytes after it, ending its own section)
VARIANTS = {"variant_a": ("", 0, None), "variant_b": ("06", 0, None), "variant_c": ("48b8", 8, None),
            "variant_d": ("b8", 4, None), "variant_e": ("", 0, "0f")}
VARIANTS.update({f"variant_{i:02d}": (p, 0, None) for i, p in enumerate(BYTE_PREFIXES)})
# f2 and f3 select other instructions for some of these opcodes.
SHOWN_BY_DISASSEMBLY = ["variant_a"] + [f"variant_{i:02d}" for i, p in enumerate(BYTE_PREFIXES) if p not in ("f2", "f3")]


@unittest.skipUnless(LOCAL_TOOLS, "sh, cc, nm and objdump required")
class TestSeededObjects(unittest.TestCase):
    """Constructs seeded into the object of the toy project, built and surveyed as the judge does; analysed, never run."""

    @classmethod
    def setUpClass(cls):
        cls.workdir = tempfile.mkdtemp(prefix="bee-seeded-")
        cls.a, cls.sources_a = build_toy(os.path.join(cls.workdir, "A"), "A")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.workdir, ignore_errors=True)

    def analysis_of(self, name, addition):
        b, sources_b = build_toy(os.path.join(self.workdir, name), "B", addition)
        return analysis.analyse(self.a, b, judge.texts_of(self.sources_a), judge.texts_of(sources_b), prefixes=("rle_",))

    def test_honest(self):
        self.assertEqual(self.analysis_of("honest", ""), [])

    def test_every_family_seeded(self):
        self.assertEqual(set(SEEDED_CONSTRUCTS), set(analysis.SEQUENCES))

    def test_seeded_constructs_found(self):
        def case_of(c, v):
            before, length, after = VARIANTS[v]
            hex_digits = before + SEEDED_CONSTRUCTS[c] + "90" * max(0, length - len(SEEDED_CONSTRUCTS[c]) // 2)
            if after is None:
                return self.analysis_of(f"{c}-{v}", asm_bytes(hex_digits))
            return self.analysis_of(f"{c}-{v}", asm_bytes(hex_digits + after, '.section .text.rle_e,\\"ax\\",@progbits', ""))
        list_of = [(c, v) for c in SEEDED_CONSTRUCTS for v in VARIANTS]
        with concurrent.futures.ThreadPoolExecutor(max(2, os.cpu_count() or 2)) as pool:
            results = dict(zip(list_of, pool.map(lambda cv: case_of(*cv), list_of)))
        for (c, v), suspects in results.items():
            with self.subTest(construct=c, variant=v):
                bytes_count = [s["detail"] for s in suspects if s["type"] == "bytes"]
                self.assertTrue(any(d.startswith(c + ":") and "objects'" in d for d in bytes_count), bytes_count)
                self.assertTrue(any(d.startswith(c + ":") and "program's" in d for d in bytes_count), bytes_count)
                instructions = [s["detail"].split(":")[0] for s in suspects if s["type"] == "instruction"]
                if v in SHOWN_BY_DISASSEMBLY:
                    self.assertIn(c, instructions)
                if v == "variant_b":
                    self.assertIn("(bad)", instructions)
                if v == "variant_e":
                    self.assertIn(".byte", instructions)
                self.assertEqual({s["type"] for s in suspects} - {"bytes", "instruction", "source"}, set())

    def test_seeded_construct_int3(self):
        self.assertIn("int3", [s["detail"].split(":")[0] for s in self.analysis_of("int3", asm_bytes("cc"))
                               if s["type"] == "instruction"])

    def test_bytes_read_independently(self):
        b, _ = build_toy(os.path.join(self.workdir, "independent"), "B", asm_bytes("0f05"))
        b["disassembly"] = self.a["disassembly"]
        self.assertEqual({s["type"] for s in analysis.analyse(self.a, b, {}, {}, prefixes=("rle_",))}, {"bytes"})

    def test_variant_f(self):
        suspects = self.analysis_of("variant_f", asm_bytes("900f0590", '.section .data.rle_x,\\"ax\\",@progbits'))
        self.assertTrue(any(s["detail"].startswith("syscall:") and "objects'" in s["detail"] for s in suspects), suspects)

    def test_variant_t(self):
        """Each new hit is reported by its place and context."""
        workdir = os.path.join(self.workdir, "variant_t")
        a, sources_a = build_toy(os.path.join(workdir, "A"), "A", asm_bytes("48b80f31909090909090"))
        for name, addition in (("same", asm_bytes("48b80f31909090909090")), ("other", asm_bytes("b80f319090"))):
            b, sources_b = build_toy(os.path.join(workdir, name), "B", addition)
            suspects = analysis.analyse(a, b, judge.texts_of(sources_a), judge.texts_of(sources_b), prefixes=("rle_",))
            bytes_count = [s["detail"] for s in suspects if s["type"] == "bytes"]
            if name == "same":
                self.assertEqual(suspects, [])
            else:
                self.assertTrue(any(d.startswith("rdtsc:") and "objects'" in d for d in bytes_count), bytes_count)
                self.assertTrue(any(d.startswith("rdtsc:") and "program's" in d for d in bytes_count), bytes_count)

    def test_memory_flags(self):
        for name, addition, flag in (
                ("variant_r", '__asm__(".section .note.GNU-stack,\\"x\\",@progbits\\n.previous\\n");\n', "executable_stack"),
                ("variant_s", '__asm__(".section .data.rle_x,\\"awx\\",@progbits\\n.byte 0\\n.previous\\n");\n', "segment_wx")):
            with self.subTest(variant=name):
                bytes_count = [s["detail"] for s in self.analysis_of(name, addition) if s["type"] == "bytes"]
                self.assertTrue(any(d.startswith(flag + ":") for d in bytes_count), bytes_count)

    def test_unreadable_object(self):
        b, _ = build_toy(os.path.join(self.workdir, "unreadable"), "B")
        b["objects"] = [(name, data[:len(data) // 2]) for name, data in b["objects"]]
        self.assertIn("incomplete_analysis", {s["type"] for s in analysis.analyse(self.a, b, {}, {}, prefixes=("rle_",))})


SEEDED_LINES = [
    '__asm__ volatile("");', 'static void rle_h(void) { asm(""); }',
    '#include <time.h>', '%:include <sys/syscall.h>', '#include "time.h"', '#  include_next <unistd.h>',
    '__attribute__((used, constructor)) static void rle_f(void) {}', '__as\\\nm volatile("");', '__as\\  \r\nm("");',
    '__attribute__ ((\nconstructor)) static void rle_g(void) {}', 'static unsigned long rle_t(void) { return __rdtsc(); }',
    '#define RLE_C(a, b) a %:%: b', '_Pragma("GCC optimize(0)")',
]


class TestSeededText(unittest.TestCase):
    """A construct added anywhere in a judged file is found: each file of B is read whole, against A's."""

    def test_seeded_line_found_anywhere(self):
        a = {}
        for name in ("rle.c", "rle.h"):
            with open(os.path.join(TOY, name), encoding="latin-1") as f:
                a[name] = f.read()
        self.assertEqual(analysis.analyse(surveys(), surveys(), a, dict(a)), [])
        for name, text in a.items():
            lines = text.split("\n")
            for seeded in SEEDED_LINES:
                for i in range(len(lines) + 1):
                    b = dict(a, **{name: "\n".join(lines[:i] + [seeded] + lines[i:])})
                    types = [s["type"] for s in analysis.analyse(surveys(), surveys(), a, b)]
                    if "source" not in types:
                        self.fail(f"{name}, line {i + 1}: {seeded!r} not found")


@unittest.skipUnless(LOCAL_TOOLS, "sh, cc, nm and objdump required")
class TestFailClosed(unittest.TestCase):
    """A failing tool never leaves the judge complete."""

    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix="bee-tools-")
        self.tools = os.path.join(self.workdir, "tools")
        os.makedirs(self.tools)

    def tearDown(self):
        shutil.rmtree(self.workdir, ignore_errors=True)

    def tool(self, name, script):
        path = os.path.join(self.tools, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n" + script + "\n")
        os.chmod(path, 0o755)

    def test_disassembler_or_nm_failure(self):
        objdump, nm = shutil.which("objdump"), shutil.which("nm")
        scenarios = [("objdump", "exit 1"), ("objdump", f'"{objdump}" "$@"; exit 1'), ("objdump", "exit 0"),
                     ("objdump", f'case "$1" in -d) exit 2;; esac; exec "{objdump}" "$@"'), ("nm", f'"{nm}" "$@"; exit 1')]
        for i, (name, script) in enumerate(scenarios):
            for f in os.listdir(self.tools):
                os.remove(os.path.join(self.tools, f))
            self.tool(name, script)
            for label in "AB":
                with self.subTest(tool=name, script=script, label=label):
                    with self.assertRaises((reading.Refusal, reading.JudgeError)):
                        build_toy(os.path.join(self.workdir, f"{i}{label}"), label, docker=DockerLocal(self.tools))

    def test_git_failure(self):
        marker = os.path.join(self.workdir, "git-called")
        self.tool("git", f'touch "{marker}"; exit 1')
        with mock.patch.dict(os.environ, {"PATH": self.tools + os.pathsep + os.environ["PATH"]}):
            a, sources_a = build_toy(os.path.join(self.workdir, "A"), "A")
            b, sources_b = build_toy(os.path.join(self.workdir, "B"), "B", "#include <time.h>\n")
            suspects = analysis.analyse(a, b, judge.texts_of(sources_a), judge.texts_of(sources_b), prefixes=("rle_",))
        self.assertEqual([s["type"] for s in suspects], ["source"])
        self.assertFalse(os.path.exists(marker))


# ------------------------------------------------------------------ meta-tests (Docker)

COMPRESS_START = """size_t rle_compress(const unsigned char *src, size_t n, unsigned char *dst)
{
    unsigned long table[256];
    size_t i = 0, start = 0, o = 4;
    rle_crc_table(table);
"""
INCLUDE = '#include "rle.h"\n'


def replace_with(text, old, new):
    if text.count(old) != 1:
        raise AssertionError(f"marker missing or ambiguous: {old[:60]!r}")
    return text.replace(old, new)


def early_exit(text, corpus):
    text = replace_with(text, INCLUDE, INCLUDE + "#include <stdlib.h>\nstatic int rle_calls = 0;\n")
    return replace_with(text, COMPRESS_START, COMPRESS_START + "    if (++rle_calls > 3)\n        exit(0);\n")


def fake_stopwatches(text, corpus):
    text = replace_with(text, INCLUDE, INCLUDE + "#include <time.h>\n"
                      "int clock_gettime(clockid_t c, struct timespec *t) { (void)c; t->tv_sec = 0; t->tv_nsec = 1; return 0; }\n")
    return replace_with(text, COMPRESS_START, COMPRESS_START +
                     "    { volatile unsigned long rle_k; for (rle_k = 0; rle_k < (unsigned long)n * 200; rle_k++) ; }\n")


def precomputed_table(text, corpus):
    sizes_of = ", ".join(str(len(d)) for _, d in corpus)
    text = replace_with(text, INCLUDE, INCLUDE + f"static const unsigned long rle_known[] = {{ {sizes_of} }};\n")
    return replace_with(text, COMPRESS_START, COMPRESS_START +
                     "    { size_t k; int seen = 0;\n"
                     "      for (k = 0; k < sizeof(rle_known) / sizeof(rle_known[0]); k++) seen |= rle_known[k] == n;\n"
                     "      if (!seen) return 0; }\n")


def valgrind_request(text, corpus):
    text = replace_with(text, INCLUDE, INCLUDE + "#include <valgrind/cachegrind.h>\n")
    text = replace_with(text, COMPRESS_START, COMPRESS_START + "    CACHEGRIND_STOP_INSTRUMENTATION;\n")
    return replace_with(text, "    rle_write32(dst + o, rle_crc(table, src, n));\n    return o + 4;\n",
                     "    rle_write32(dst + o, rle_crc(table, src, n));\n    CACHEGRIND_START_INSTRUMENTATION;\n    return o + 4;\n")


def fake_summary(text, corpus):
    text = replace_with(text, INCLUDE, INCLUDE + "#include <stdio.h>\n")
    return replace_with(text, COMPRESS_START, COMPRESS_START + '    fputs("==1== I   refs:        1\\n", stderr);\n')


def split_tokens(text, corpus):
    """The preamble of Valgrind's client requests in assembler, the word « asm » formed by token pasting."""
    text = replace_with(text, INCLUDE, INCLUDE + "#define RLE_PASTE(a, b) a##b\n#define RLE_Z RLE_PASTE(a, sm)\n")
    return replace_with(text, COMPRESS_START, COMPRESS_START +
                     '    RLE_Z volatile("rol $3, %%rdi\\n\\trol $13, %%rdi\\n\\trol $61, %%rdi\\n\\trol $51, %%rdi" ::: "rdi");\n')


def call_laundered_by_prefix(text, corpus):
    text = replace_with(text, INCLUDE, INCLUDE + "#include <stdlib.h>\n")
    return replace_with(text, COMPRESS_START, COMPRESS_START + '    { char *volatile e = getenv("BEE_SECRET"); (void)e; }\n')


def moved_work(text, corpus):
    """The CRC table is built in advance in rle_bound, which the harness calls just before compressing."""
    text = replace_with(text, INCLUDE, INCLUDE + "#include <stdlib.h>\n")
    text = replace_with(text, """size_t rle_bound(size_t n)
{
""", """static unsigned long **rle_reserve = NULL;
static size_t rle_capacity = 0, rle_stored = 0, rle_taken = 0;

size_t rle_bound(size_t n)
{
    unsigned long *t = (unsigned long *)malloc(256 * sizeof(unsigned long));
    if (t)
        rle_crc_table(t);
    if (rle_stored == rle_capacity) {
        rle_capacity = rle_capacity ? 2 * rle_capacity : 64;
        rle_reserve = (unsigned long **)realloc(rle_reserve, rle_capacity * sizeof(*rle_reserve));
    }
    rle_reserve[rle_stored++] = t;
""")
    return replace_with(text, COMPRESS_START, """size_t rle_compress(const unsigned char *src, size_t n, unsigned char *dst)
{
    unsigned long local_table[256], *table = (rle_reserve && rle_taken < rle_stored) ? rle_reserve[rle_taken++] : NULL;
    size_t i = 0, start = 0, o = 4;
    if (!table) {
        rle_crc_table(local_table);
        table = local_table;
    }
""")


# ruche-0037: a library that records what it observes of its process at its first call; the meta-tests compare digests.
SPY = r'''
#include <dirent.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/auxv.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/utsname.h>
#include <unistd.h>

extern char **environ;
static int rle_seen = 0;
static char rle_buffer[65536], rle_counters[8][4096];

static size_t rle_read(const char *path, char *buffer, size_t size)
{
    size_t n = 0;
    ssize_t got;
    int fd = open(path, O_RDONLY);
    if (fd < 0)
        return 0;
    while (n < size - 1 && (got = read(fd, buffer + n, size - 1 - n)) > 0)
        n += (size_t)got;
    close(fd);
    buffer[n] = 0;
    return n;
}

static void rle_text(const char *key, const char *p, size_t n)
{
    size_t i;
    fprintf(stderr, "%s=", key);
    for (i = 0; i < n; i++)
        if (p[i] >= 32 && p[i] < 127 && p[i] != '\\')
            fputc(p[i], stderr);
        else
            fprintf(stderr, "\\x%02x", (unsigned char)p[i]);
    fputc('\n', stderr);
}

static int rle_compare(const void *a, const void *b)
{
    return strcmp(*(char *const *)a, *(char *const *)b);
}

static void rle_folder(const char *path)
{
    char *names[512];
    int n = 0, i;
    struct dirent *d;
    DIR *r = opendir(path);
    while (r && n < 512 && (d = readdir(r)))
        names[n++] = strdup(d->d_name);
    if (r)
        closedir(r);
    qsort(names, (size_t)n, sizeof(char *), rle_compare);
    fprintf(stderr, "ls:%s=", path);
    for (i = 0; i < n; i++)
        fprintf(stderr, "%s ", names[i]);
    fputc('\n', stderr);
}

static void rle_spy(void)
{
    static const char *const counters[] = {"/proc/self/io", "/proc/self/stat", "/proc/self/statm", "/proc/self/schedstat"};
    static const char *const files[] = {"/proc/self/cmdline", "/proc/self/environ", "/proc/1/cmdline", "/proc/self/status",
        "/proc/self/mountinfo", "/proc/self/cgroup", "/proc/self/limits", "/etc/hosts", "/etc/hostname"};
    static const char *const folders[] = {"/", "/chrono", "/inputs", "/outputs", "/tmp", "/variant", "/proc/self/fd"};
    static const char *const dates[] = {"/chrono", "/chrono/chrono", "/inputs", "/inputs/list", "/outputs", "/variant",
        "/variant/execution"};
    char line[4096], *p;
    size_t k, lengths[4];
    int i, fd;
    struct rusage ru;
    struct stat st;
    struct utsname u;
    if (rle_seen++)
        return;
    for (k = 0; k < 4; k++)
        lengths[k] = rle_read(counters[k], rle_counters[k], sizeof(rle_counters[k]));
    getrusage(RUSAGE_SELF, &ru);
    fputs("SPY-START\n", stderr);
    for (k = 0; k < 4; k++)
        rle_text(counters[k], rle_counters[k], lengths[k]);
    fprintf(stderr, "rusage=%ld %ld %ld %ld %ld %ld %ld %ld %ld\n", (long)(ru.ru_utime.tv_sec * 1000000 + ru.ru_utime.tv_usec),
            (long)(ru.ru_stime.tv_sec * 1000000 + ru.ru_stime.tv_usec), ru.ru_maxrss, ru.ru_minflt, ru.ru_majflt,
            ru.ru_inblock, ru.ru_oublock, ru.ru_nvcsw, ru.ru_nivcsw);
    for (k = 0; k < sizeof(files) / sizeof(files[0]); k++)
        rle_text(files[k], rle_buffer, rle_read(files[k], rle_buffer, sizeof(rle_buffer)));
    for (k = 0; k < sizeof(dates) / sizeof(dates[0]); k++)
        if (lstat(dates[k], &st) == 0)
            fprintf(stderr, "date:%s=%o %ld %ld\n", dates[k], (unsigned)st.st_mode, (long)st.st_atime, (long)st.st_mtime);
    for (k = 0; k < sizeof(folders) / sizeof(folders[0]); k++)
        rle_folder(folders[k]);
    fputs("environ=", stderr);
    for (i = 0; environ && environ[i]; i++)
        fprintf(stderr, "%s;", environ[i]);
    fputc('\n', stderr);
    p = (char *)getauxval(AT_EXECFN);
    fprintf(stderr, "auxv=%s %lu %lu %lu %lu %lu %lx %lx %lu %lu\n", p ? p : "-", getauxval(AT_SECURE), getauxval(AT_UID),
            getauxval(AT_EUID), getauxval(AT_GID), getauxval(AT_EGID), getauxval(AT_HWCAP), getauxval(AT_HWCAP2),
            getauxval(AT_PAGESZ), getauxval(AT_CLKTCK));
    fputs("descriptors=", stderr);
    for (fd = 0; fd < 1024; fd++) {
        char target[256];
        ssize_t n;
        if (fcntl(fd, F_GETFD) < 0)
            continue;
        snprintf(line, sizeof(line), "/proc/self/fd/%d", fd);
        n = readlink(line, target, sizeof(target) - 1);
        target[n > 0 ? n : 0] = 0;
        if (strncmp(target, "pipe:[", 6) == 0)
            target[5] = 0;
        fstat(fd, &st);
        fprintf(stderr, "%d:%s:%o:%x:%x;", fd, target, (unsigned)(st.st_mode & S_IFMT), (unsigned)fcntl(fd, F_GETFL),
                (unsigned)fcntl(fd, F_GETFD));
    }
    fputc('\n', stderr);
    fprintf(stderr, "cwd=%s\n", getcwd(line, sizeof(line)) ? line : "-");
    i = (int)readlink("/proc/self/exe", line, sizeof(line) - 1);
    fprintf(stderr, "exe=%.*s\n", i > 0 ? i : 0, line);
    fprintf(stderr, "ids=%d %d %d %d %d %d %d\n", (int)getppid(), (int)getuid(), (int)geteuid(), (int)getgid(), (int)getegid(),
            (int)getpgrp(), (int)getsid(0));
    i = (int)umask(022);
    umask((mode_t)i);
    uname(&u);
    fprintf(stderr, "umask=%o\nuname=%s %s %s\n", i, u.nodename, u.sysname, u.machine);
    fputs("SPY-END\n", stderr);
}
'''


def spy(text, corpus):
    text = "#define _GNU_SOURCE\n" + replace_with(text, INCLUDE, INCLUDE + SPY)
    text = replace_with(text, COMPRESS_START, COMPRESS_START + "    rle_spy();\n")
    return replace_with(text, "    *produced = 0;\n    if (n < 8)", "    rle_spy();\n    *produced = 0;\n    if (n < 8)")


# Values that differ between any two containers, replaced before the records are compared.
VARIABLE = [(re.compile(p), r) for p, r in (
    (r"(^|\\x0a)\d+ \d+ \d+:\d+ ", r"\1"), (r"[0-9a-f]{64}", "<container>"), (r"overlay2/l/[A-Z0-9]+", "<layer>"),
    (r"io\.containerd\.snapshotter\.v1\.overlayfs/snapshots/\d+", "<layer>"),
    (r"bee-judge-[A-Za-z0-9_]+", "bee-judge-*"), (r"(?<![0-9a-f])[0-9a-f]{16}(?![0-9a-f])", "<neutral>"),
    (r"\\x0a(?:Tgid|Pid|NStgid|NSpid|Vm[A-Za-z]+|Rss[A-Za-z]+|(?:non)?voluntary_ctxt_switches):(?:\\x09|[^\\])*", ""))]
# Counters (they depend on the inputs: compared only when the inputs are the same, test_same_counters).
COUNTERS = ("/proc/self/io", "/proc/self/stat", "/proc/self/statm", "/proc/self/schedstat", "rusage")
# Counters that vary from one run to the next in the same mode (time, scheduling, resident memory): compared within these
# bounds, the others exactly.
NOISE = {"stat_utime": 20, "stat_stime": 20, "stat_minflt": 40, "stat_rss": 100, "statm_1": 100, "statm_2": 100,
         "schedstat_0": 2e8, "schedstat_1": 2e8, "schedstat_2": 20, "ru_utime": 2e5, "ru_stime": 2e5, "ru_maxrss": 400,
         "ru_minflt": 40, "ru_nvcsw": 20, "ru_nivcsw": 20, "ru_inblock": 1000}
# Keys allowed to differ under the instruction counter.
EXCEPTIONS_INSTRUCTIONS = {"/proc/self/cmdline", "/proc/self/environ", "/proc/self/status", "auxv", "ls:/proc/self/fd"}


def spy_reading(text):
    beginning, end = text.rindex("SPY-START\n"), text.rindex("SPY-END\n")
    survey = {}
    for line_text in text[beginning:end].splitlines()[1:]:
        key, _, value = line_text.partition("=")
        for pattern, replacement in VARIABLE:
            value = pattern.sub(replacement, value)
        survey[key] = value
    # The mount table is compared line by line, in its order: each of the judge's mounts at its own depth, Docker creates
    # them in the same order whatever its version (test_one_mount_order_whatever_docker_draws).
    return survey


def fingerprints(survey, except_for=()):
    """The record as one digest per key (counters and `except_for` aside)."""
    return {k: hashlib.sha256(v.encode()).hexdigest()[:16] for k, v in survey.items() if k not in COUNTERS and k not in except_for}


def counters(survey):
    """The counters of a record: {name: integer}."""
    result = {}
    for line_text in survey["/proc/self/io"].split("\\x0a"):
        if ": " in line_text:
            result["io_" + line_text.split(": ")[0]] = int(line_text.split(": ")[1])
    stat = survey["/proc/self/stat"].rpartition(")")[2].split()
    for name, rank in (("minflt", 10), ("majflt", 12), ("utime", 14), ("stime", 15), ("threads", 20), ("vsize", 23), ("rss", 24)):
        result["stat_" + name] = int(stat[rank - 3])
    result.update(("statm_" + str(i), int(x)) for i, x in enumerate(survey["/proc/self/statm"].replace("\\x0a", "").split()))
    result.update(("schedstat_" + str(i), int(x)) for i, x in enumerate(survey["/proc/self/schedstat"].replace("\\x0a", "").split()))
    result.update(zip(("ru_utime", "ru_stime", "ru_maxrss", "ru_minflt", "ru_majflt", "ru_inblock", "ru_oublock", "ru_nvcsw",
                       "ru_nivcsw"), map(int, survey["rusage"].split())))
    return result


def wrong_output_timed(text, corpus):
    """Wrong only when timed: it compresses the corpus's sizes (the measured inputs) right, anything else wrong.
    The mode comes from the base's harness (made to tell it, test_wrong_output_timed)."""
    sizes_of = ", ".join(str(len(d)) for _, d in corpus)
    text = replace_with(text, INCLUDE, INCLUDE + f"extern int rle_measured;\nstatic const unsigned long rle_known[] = {{ {sizes_of} }};\n")
    return replace_with(text, COMPRESS_START, COMPRESS_START +
                        "    if (rle_measured) { size_t k; int seen = 0;\n"
                        "      for (k = 0; k < sizeof(rle_known) / sizeof(rle_known[0]); k++) seen |= rle_known[k] == n;\n"
                        "      if (!seen) return 0; }\n")


# ruche-0036: a library each of whose scenarios tries, before its own work and again when it exits, to read and to
# modify any other scenario's outputs it can reach (and to leave something for the next one in its inputs or /tmp).
# Any file it finds there makes its own outputs wrong; any it can modify it overwrites.
NEIGHBORS = r"""
#include <dirent.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static int rle_neighbor_seen = 0;

static void rle_touch(const char *path, int depth)
{
    char p[1024];
    struct dirent *e;
    DIR *d = opendir(path);
    FILE *f;
    if (!d) {
        if ((f = fopen(path, "r+b")) == NULL)
            f = fopen(path, "rb");
        if (f) {
            rle_neighbor_seen = 1;
            if (fgetc(f) != EOF && fseek(f, 0, SEEK_SET) == 0)
                fputs("intruder", f);
            fclose(f);
        }
        return;
    }
    while (depth < 4 && (e = readdir(d)) != NULL)
        if (e->d_name[0] != '.') {
            snprintf(p, sizeof(p), "%s/%s", path, e->d_name);
            rle_touch(p, depth + 1);
        }
    closedir(d);
}

static void rle_neighbors(int before)
{
    static const char *const names[] = {"compression", "compression_bis", "decompression", "decompression_bis", "verify"};
    char p[512];
    size_t k;
    FILE *f;
    if (before)
        rle_touch("/outputs", 0);
    for (k = 0; k < sizeof(names) / sizeof(names[0]); k++) {
        snprintf(p, sizeof(p), "/outputs/%s", names[k]);
        rle_touch(p, 0);
        snprintf(p, sizeof(p), "/outputs/../%s", names[k]);
        rle_touch(p, 0);
    }
    if ((f = fopen("/inputs/list", "r+b")) != NULL || (f = fopen("/inputs/intruder", "wb")) != NULL) {
        rle_neighbor_seen = 1;
        fclose(f);
    }
    if (before && (f = fopen("/tmp/rle_trace", "rb")) != NULL) {
        rle_neighbor_seen = 1;
        fclose(f);
    } else if (!before && (f = fopen("/tmp/rle_trace", "wb")) != NULL)
        fclose(f);
}

static void rle_neighbors_after(void)
{
    rle_neighbors(0);
}

static void rle_neighbors_before(void)
{
    static int done = 0;
    if (done++)
        return;
    rle_neighbors(1);
    atexit(rle_neighbors_after);
}
"""


def neighbor_scenarios(text, corpus):
    """Each scenario of B tries to read and to modify the other scenarios' outputs, before its own work and when it exits."""
    text = replace_with(text, INCLUDE, INCLUDE + NEIGHBORS)
    text = replace_with(text, COMPRESS_START, COMPRESS_START + "    rle_neighbors_before();\n")
    text = replace_with(text, "    return o + 4;\n", "    if (rle_neighbor_seen)\n        dst[0] ^= 1;\n    return o + 4;\n")
    return replace_with(text, "    *produced = 0;\n    if (n < 8)",
                        "    *produced = 0;\n    rle_neighbors_before();\n    if (rle_neighbor_seen)\n        return RLE_INVALID;\n    if (n < 8)")


# ruche-0117: a library that records, at its first call, what it can see of every mount (from /proc/self/mountinfo): its line,
# statx of the mount point (inode, device, links, mode, owner, size, access and modification times, the age of its change and
# birth times, the mount id) and statfs; for the judge's mounts, the same for every entry, and each folder's entries in the order
# readdir gives them (as ranks among their sorted names: the inputs' names are data). Then it fills part of its outputs folder.
MOUNTS = r"""
#include <dirent.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <time.h>
#ifndef STATX_MNT_ID_UNIQUE
#define STATX_MNT_ID_UNIQUE 0x4000U
#endif
static int rle_mounts_seen = 0;

static long long rle_age(struct statx_timestamp t, struct timespec n)
{
    return (long long)(n.tv_sec - t.tv_sec) * 1000 + ((long)n.tv_nsec - (long)t.tv_nsec) / 1000000;
}

static void rle_look(const char *path, const char *key)
{
    struct statx s;
    struct statfs f;
    struct timespec n;
    clock_gettime(CLOCK_REALTIME, &n);
    if (statx(AT_FDCWD, path, AT_SYMLINK_NOFOLLOW, STATX_BASIC_STATS | STATX_BTIME | STATX_MNT_ID_UNIQUE, &s) != 0) {
        fprintf(stderr, "stat:%s=absent\n", key);
        return;
    }
    fprintf(stderr, "stat:%s=%llu %u:%u %u %o %u %u %llu\n", key, (unsigned long long)s.stx_ino, s.stx_dev_major,
            s.stx_dev_minor, s.stx_nlink, s.stx_mode, s.stx_uid, s.stx_gid, (unsigned long long)s.stx_size);
    fprintf(stderr, "times:%s=%lld.%09u %lld.%09u\n", key, (long long)s.stx_atime.tv_sec, s.stx_atime.tv_nsec,
            (long long)s.stx_mtime.tv_sec, s.stx_mtime.tv_nsec);
    fprintf(stderr, "age:%s=%lld %lld\n", key, rle_age(s.stx_ctime, n), (s.stx_mask & STATX_BTIME) ? rle_age(s.stx_btime, n) : -1LL);
    fprintf(stderr, "mnt:%s=%llu\n", key, (unsigned long long)s.stx_mnt_id);
    if (statfs(path, &f) == 0) {
        fprintf(stderr, "statfs:%s=%lx %ld %llu %llu %llu %llu %llu\n", key, (long)f.f_type, (long)f.f_bsize,
                (unsigned long long)f.f_blocks, (unsigned long long)f.f_bfree, (unsigned long long)f.f_bavail,
                (unsigned long long)f.f_files, (unsigned long long)f.f_ffree);
        fprintf(stderr, "fsid:%s=%x:%x\n", key, (unsigned)f.f_fsid.__val[0], (unsigned)f.f_fsid.__val[1]);
    }
}

static int rle_compare_names(const void *a, const void *b)
{
    return strcmp(*(char *const *)a, *(char *const *)b);
}

static void rle_tree(const char *path, const char *key, int depth)
{
    char *names[256], *sorted[256], sub[1024], sub_key[1024];
    int n = 0, i, j;
    struct dirent *e;
    DIR *d;
    rle_look(path, key);
    if (depth > 3 || !(d = opendir(path)))
        return;
    while (n < 256 && (e = readdir(d)))
        if (strcmp(e->d_name, ".") && strcmp(e->d_name, ".."))
            names[n++] = strdup(e->d_name);
    closedir(d);
    memcpy(sorted, names, sizeof(char *) * (size_t)n);
    qsort(sorted, (size_t)n, sizeof(char *), rle_compare_names);
    fprintf(stderr, "order:%s=", key);
    for (i = 0; i < n; i++)
        for (j = 0; j < n; j++)
            if (names[i] == sorted[j])
                fprintf(stderr, "%d ", j);
    fputc('\n', stderr);
    for (j = 0; j < n; j++) {
        snprintf(sub, sizeof(sub), "%s/%s", path, sorted[j]);
        snprintf(sub_key, sizeof(sub_key), "%s/#%d", key, j);
        rle_tree(sub, sub_key, depth + 1);
    }
}

static void rle_mounts(void)
{
    static const char *const judge[] = {"/chrono", "/variant", "/inputs", "/outputs", "/tmp"};
    static char buffer[1 << 16];
    char *line, *rest, point[1024];
    size_t k, n = 0;
    ssize_t got;
    int fd;
    FILE *f;
    struct timespec now;
    if (rle_mounts_seen++)
        return;
    clock_gettime(CLOCK_REALTIME, &now);
    fprintf(stderr, "MOUNTS-START\nnow=%lld.%09ld\n", (long long)now.tv_sec, now.tv_nsec);
    if ((fd = open("/proc/self/mountinfo", O_RDONLY)) >= 0) {
        while (n < sizeof(buffer) - 1 && (got = read(fd, buffer + n, sizeof(buffer) - 1 - n)) > 0)
            n += (size_t)got;
        close(fd);
    }
    buffer[n] = 0;
    for (line = strtok_r(buffer, "\n", &rest); line; line = strtok_r(NULL, "\n", &rest)) {
        if (sscanf(line, "%*s %*s %*s %*s %1023s", point) != 1)
            continue;
        fprintf(stderr, "mount:%s=%s\n", point, line);
        rle_look(point, point);
    }
    for (k = 0; k < sizeof(judge) / sizeof(judge[0]); k++)
        rle_tree(judge[k], judge[k], 0);
    fputs("MOUNTS-END\n", stderr);
    if ((f = fopen("/outputs/rle_ballast", "wb")) != NULL) {  /* 8 MiB left in its outputs: no other container may see them */
        static char ballast[1 << 20];
        for (k = 0; k < 8; k++)
            fwrite(ballast, 1, sizeof(ballast), f);
        fclose(f);
    }
}
"""


def mounts_spy(text, corpus):
    text = "#define _GNU_SOURCE\n" + replace_with(text, INCLUDE, INCLUDE + MOUNTS)
    text = replace_with(text, COMPRESS_START, COMPRESS_START + "    rle_mounts();\n")
    return replace_with(text, "    *produced = 0;\n    if (n < 8)", "    rle_mounts();\n    *produced = 0;\n    if (n < 8)")


def mounts_reading(text):
    """The record of MOUNTS: {key: value}, a container's id (in cgroup paths, drawn by Docker) replaced."""
    beginning, end = text.rindex("MOUNTS-START\n"), text.rindex("MOUNTS-END\n")
    return {key: re.sub(r"[0-9a-f]{64}", "<container>", value)
            for key, _, value in (line_text.partition("=") for line_text in text[beginning:end].splitlines()[1:])}


# Every container of a side gets the same inputs, whatever the step, repetition or mode (test_same_mounts): four verification
# inputs per side, two measured inputs and two mixed-in ones per repetition, as many in the instruction count.
SAME_INPUTS = """

_DATA = bytes(range(64)) * 8
Project.corpus = lambda self, tooling: [(f"k{i:03d}", _DATA) for i in range(4)]
Project.verification = lambda self, rng, corpus: self.make_inputs(corpus, [(f"z{i:03d}", compress(_DATA), 512, _DATA) for i in range(4)])
Project.repetition = lambda self, rng, corpus: self.make_inputs(corpus[:2], [(f"z{i:03d}", compress(_DATA), 512, _DATA) for i in range(2)])
"""
AGE_MAX_MS = 5000  # spread allowed between the ages of a time (container start-up, Valgrind's included)
# The judge's mounts: fixed access and modification times. Docker's own mounts are made with the container: their times are
# compared as ages, from the record's « now ».
JUDGE_MOUNTS = ("/chrono", "/variant", "/inputs", "/outputs", "/etc/hostname", "/etc/hosts", "/etc/resolv.conf")
# What remains visible of the run's progress, outside the judge's mounts (docs/common-judge.md): the container's root (Docker's
# overlay on the host's disk: its inode, its free blocks and files, and, with the containerd image store, its layers' numbers
# in its mount line), and kernel-wide counters: unique mount ids (statx), the host's process count (link count of /proc), the
# inode numbers the kernel gives each container's cgroup and message queue file system.
REST = {"stat:/", "statfs:/", "mount:/", "fsid:/", "stat:/proc", "stat:/dev/mqueue"}
REST_PREFIXES = ("mnt:", "stat:/sys/fs/cgroup")
REST_INSTRUCTIONS = {"statfs:/tmp"}  # Valgrind keeps files of its own, unlinked, in /tmp (the instruction count is detectable)


# ruche-0136: the real docker client, but the FAILURE_RANK-th « docker run » gets FAILURE_OPTIONS (a runtime that fails).
BROKEN_DOCKER = r"""#!/usr/bin/env python3
import os, sys
arguments = sys.argv[1:]
if arguments[:1] == ["run"]:
    with open(os.environ["FAILURE_COUNT"], "a+") as f:
        f.seek(0)
        rank = int(f.read() or 0) + 1
        f.seek(0)
        f.truncate()
        f.write(str(rank))
    if rank == int(os.environ["FAILURE_RANK"]):
        arguments[1:1] = os.environ["FAILURE_OPTIONS"].split()
os.execv(DOCKER, [DOCKER] + arguments)
"""


@unittest.skipUnless(os.environ.get("BEE_JUDGE_INTEGRATION") == "1" and shutil.which("docker"),
                     "meta-tests: BEE_JUDGE_INTEGRATION=1 and Docker required")
class TestJudgeAgainstVariants(unittest.TestCase):
    """The whole common judge, in containers, against the toy project and malicious variants."""

    toy = TOY  # the base

    @classmethod
    def setUpClass(cls):
        cls.workdir = tempfile.mkdtemp(prefix="bee-meta-common-")
        cls.corpus = toy_plugin.Project({}).corpus(TOY)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.workdir, ignore_errors=True)

    def prepare(self, name, transformation=None):
        source_b = os.path.join(self.workdir, name)
        os.makedirs(source_b)
        for file in ("rle.c", "rle.h"):
            shutil.copyfile(os.path.join(self.toy, file), os.path.join(source_b, file))
        if transformation:
            with open(os.path.join(source_b, "rle.c"), encoding="utf-8") as f:
                text = f.read()
            with open(os.path.join(source_b, "rle.c"), "w", encoding="utf-8") as f:
                f.write(transformation(text, self.corpus))
        return source_b

    def changed_base(self, name, file, old, new):
        """A copy of the toy (the BASE) with one of its tooling files changed (file: plugin, build or harness)."""
        base = os.path.join(self.workdir, "base-" + name)
        shutil.copytree(self.toy, base, ignore=shutil.ignore_patterns("__pycache__"))
        path = toy_file(base, file)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace(old, new) if text.count(old) >= 1 else replace_with(text, old, new))
        return base

    def run_the_judge(self, name, source_b, no_instructions=False, base=None, repetitions=2, options=(), extra=()):
        base = base or self.toy
        command = [sys.executable, os.path.join(HERE, "judge.py"), "--tooling", base, "--source-a", base,
                    "--source-b", source_b, "--repetitions", str(repetitions), "--warmup", "0"] + list(extra)
        for o in options:
            command += ["--option", o]
        if no_instructions:
            command.append("--no-instructions")
        if os.environ.get("BEE_JUDGE_NETWORK"):
            command += ["--build-network", os.environ["BEE_JUDGE_NETWORK"]]
        r = subprocess.run(command, capture_output=True, text=True, timeout=1800)
        report = json.loads(r.stdout) if r.returncode == 0 else None
        print(f"\n[{name}] code {r.returncode} : {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ''}", file=sys.stderr)
        return r.returncode, report, r.stderr

    def spied_judge_run(self, source_b, base=None, extra=(), report_=None):
        """judge.py in this process; for each container that runs B: its standard input (options, plan) and error."""
        base = base or self.toy
        containers, launch, execute, variants_of = [], container.Docker.launch, container.Execution.launch, []

        def spy_on(docker, command, mounts, pids=2, entry=None, timeout_seconds=3600):
            r = launch(docker, command, mounts, pids, entry, timeout_seconds)
            if command == ["/chrono/chrono"] and variants_of[-1:] == ["B"]:  # ruche-0117: /variant is a copy, on its own tmpfs
                containers.append((entry.decode(), r.stderr.decode("utf-8", "replace")))
            return r

        def run(self, variant, *arguments, **options):
            variants_of.append(variant)
            try:
                return execute(self, variant, *arguments, **options)
            finally:
                variants_of.pop()
        argv = ["--tooling", base, "--source-a", base, "--source-b", source_b, "--repetitions", "2", "--warmup", "0", *extra]
        if os.environ.get("BEE_JUDGE_NETWORK"):
            argv += ["--build-network", os.environ["BEE_JUDGE_NETWORK"]]
        with mock.patch.object(container.Docker, "launch", spy_on), mock.patch.object(container.Execution, "launch", run), \
                mock.patch.dict(os.environ), contextlib.redirect_stdout(report_ or io.StringIO()):
            return judge.main(argv), containers

    def types_suspects(self, report):
        return {s["type"] for s in report["judge"]["suspicious_constructs"]}

    def test_measured_through_the_base(self):
        """hive.py measure's own steps on the toy, the common judge as the run makes it (judge_of): the tip against itself,
        twice; each gain the judge gives measured; a floor proposed for each, twice the largest gain seen between the tip
        and itself, with what the judge's own proof said of it; no bound of a phase proposed (they are the plug-in's);
        a time of a judgement proposed."""
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "hive"))
        import hive
        if not hasattr(hive, "measure_runs"):
            self.skipTest("this hive does not hold the measure yet")
        judge = hive.judge_of(os.path.dirname(os.path.dirname(HERE)), {"kind": "common", "repetitions": 3, "timeout_seconds": 1800}, self.workdir)
        made = iter(range(10))

        def ask(task):
            n = next(made)
            base = os.path.join(self.workdir, f"measure-base-{n}")  # (a copy: the judge writes its report beside the tree it is given)
            shutil.copytree(self.toy, base, ignore=shutil.ignore_patterns("__pycache__"))
            return judge(base, self.prepare(f"measure-{n}"), task, "T" * 40, "T" * 40)

        runs = hive.measure_runs(ask, hive.measure_tasks("common", None, {"project": "toy"}, {}), 2)
        self.assertEqual([code for _, code, _, _, _ in runs], [0, 0], runs)
        answered = [figures for _, _, figures, _, _ in runs]
        gains = sorted(name for name in answered[0] if name.startswith("gain_"))
        self.assertTrue(gains, answered)
        floors = hive.measure_floors("common", gains, {}, answered)
        self.assertEqual(len(floors), len(gains))
        for line in floors:
            self.assertRegex(line, r"\Acutter\.floors\.gain_\w+: propose \d\.\d{4}\. Rule: 2 times the largest gain the judge measured between the tip "
                                   r"and itself")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            lines = hive.measure_bounds(hive.Doctor(), "common", None, None, {"timeout_seconds": 1800}, runs, 2)
        self.assertIn("CANNOT phases: the common judge's plug-in", out.getvalue())
        self.assertTrue(any(line.startswith("judge.timeout_seconds: propose ") for line in lines), lines)

    def test_honest(self):
        code, report, _ = self.run_the_judge("honest", self.prepare("honest"))
        self.assertEqual(code, 0)
        self.assertEqual(report["judge"]["suspicious_constructs"], [])
        self.assertEqual(report["judge"]["project"], "toy")
        self.assertGreater(report["judge"]["verification"]["outputs_compared"], 30)
        for m in report["instructions"].values():
            self.assertEqual(m["A"], m["B"])
        self.assertEqual(set(report["metrics"]), {"compression_throughput", "decompression_throughput", "ratio", "max_memory_kb"})
        self.assertIsNone(report["judge"]["source"])  # named by a caller (--judge-source), not by a local run
        self.assertEqual(report["judge"]["seed_origin"], {"seed": "drawn", "order_seed": "drawn"})  # ruche-0136
        verification = report["judge"]["verification"]  # ruche-0037: 20 f and 30 z verification inputs, over 2 repetitions
        self.assertEqual(verification["mixed_per_repetition"], {"f": 10, "z": 15})
        self.assertEqual(verification["inputs_mixed"], 3 * 25)  # 2 repetitions and the instruction count
        self.assertEqual(verification["instructions_without_mixing"], [])
        unfolding = report["judge"]["scenarios"]["steps"]  # ruche-0036: order and CPU time of each scenario
        self.assertEqual([e["step"] for e in unfolding], ["measurement", "measurement", "instructions"])
        for e in unfolding:
            expected_items = toy_plugin.Project.INSTRUCTIONS if e["step"] == "instructions" else toy_plugin.Project.SCENARIOS
            self.assertEqual(sorted(e["order"]), sorted(expected_items))
            for v in "AB":
                self.assertEqual(sorted(e["cpu_time_s"][v]), sorted(expected_items))
                self.assertTrue(all(isinstance(x, (int, float)) and x >= 0 for x in e["cpu_time_s"][v].values()))

    def test_neighbor_scenarios(self):
        """ruche-0036, on the toy with two scenarios per side: a candidate each of whose scenarios tries to read and to
        modify the others' outputs, before and after its own work, gets the honest toy's verdict and comparisons at the
        same seeds; the order changes between repetitions (each scenario of a side running before and after the other,
        at this order seed) and is recorded in judge.json with each scenario's CPU time."""
        base, seeds = toy_with_four_scenarios(os.path.join(self.workdir, "base-four-scenarios"), self.toy), ["--seed", "00" * 16,
                                                                                                      "--order-seed", "01" * 16]
        code_h, honest_one, header_output = self.run_the_judge("neighbors_reference", self.prepare("neighbors_reference"), base=base,
                                               repetitions=3, extra=seeds)
        code, report, output_text = self.run_the_judge("neighbor_scenarios", self.prepare("neighbor_scenarios", neighbor_scenarios), base=base,
                                           repetitions=3, extra=seeds)
        self.assertEqual((code_h, code), (0, 0), header_output + output_text)
        self.assertEqual(report["judge"]["verification"], honest_one["judge"]["verification"])
        self.assertEqual(report["judge"]["seed_origin"], {"seed": "given", "order_seed": "given"})  # ruche-0136
        self.assertIn("external_call", self.types_suspects(report))  # its attempts are compiled in (opendir, fopen…)
        unfolding = report["judge"]["scenarios"]["steps"]
        self.assertEqual([e["order"] for e in unfolding], [e["order"] for e in honest_one["judge"]["scenarios"]["steps"]])
        orders = [e["order"] for e in unfolding if e["step"] == "measurement"]
        self.assertEqual(len(orders), 3)
        self.assertGreater(len({tuple(o) for o in orders}), 1)
        for a, b in (("compression", "compression_bis"), ("decompression", "decompression_bis")):
            self.assertEqual({o.index(a) < o.index(b) for o in orders}, {True, False})
        for e in unfolding:
            for v in "AB":
                self.assertEqual(sorted(e["cpu_time_s"][v]), sorted(e["order"]))

    def test_declared_history(self):
        """ruche-0024: the toy plugin reads rle.c at a commit the base does not have; declared, it is fetched in its own
        step (before the plugin and the PR), once the compare API (a stand-in for gh here) puts it in the base's ancestry; then the
        judge runs with the origin gone and every git transport refused."""
        workdir = os.path.join(self.workdir, "declared-history")
        origin_of, base, commit, old, source, _ = toy_repo_with_history(workdir, self.toy)
        path, gh_log = fake_gh(workdir)
        env = dict(os.environ, PATH=path, FAKE_GH_LOG=gh_log, FAKE_GH_REPO=source, GITHUB_REPOSITORY="Bee-ruche/toyBee")
        r = subprocess.run([sys.executable, os.path.join(HERE, "judge.py"), "--tooling", base, "--history-only",
                            "--history", commit], capture_output=True, text=True, timeout=600, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        r = subprocess.run([sys.executable, os.path.join(HERE, "judge.py"), "--tooling", base, "--image-only"]
                           + (["--build-network", os.environ["BEE_JUDGE_NETWORK"]] if os.environ.get("BEE_JUDGE_NETWORK") else []),
                           capture_output=True, text=True, timeout=1800)
        self.assertEqual(r.returncode, 0, r.stderr)
        shutil.rmtree(origin_of)
        code, report, output_text = self.run_the_judge("declared_history", self.prepare("declared_history"), True, base=base,
                                          options=[f"corpus_commit={commit}"])
        self.assertEqual(code, 0, output_text)
        self.assertEqual(report["judge"]["verification"]["history"], f"{commit}:rle.c ({len(old)} bytes)")

    def test_undeclared_history(self):
        """Not declared: a clean environment error (code 2), even for a plugin that tries to fetch it itself from an
        origin that is still there (minizBee's former workaround): judging has no git transport."""
        _, base, commit, _, _, _ = toy_repo_with_history(os.path.join(self.workdir, "undeclared-history"), self.toy)
        path = toy_file(base, "plugin")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(replace_with(text, '        r = subprocess.run(["git", "-C", tooling, "cat-file"',
                              '        subprocess.run(["git", "-C", tooling, "fetch", "-q", "--depth=1", "origin", '
                              'self.corpus_commit], capture_output=True, timeout=60)\n'
                              '        r = subprocess.run(["git", "-C", tooling, "cat-file"'))
        code, _, output_text = self.run_the_judge("undeclared_history", self.prepare("undeclared_history"), True, base=base,
                                     options=[f"corpus_commit={commit}"])
        self.assertEqual(code, 2)
        self.assertIn("history", output_text)

    def test_depths(self):
        """ruche-0136, with Docker: every mount Docker makes itself in a container of the judge (/proc, /dev, /sys and cgroups,
        /dev/shm, /tmp, /etc's files, masked paths) is shallower than container.DEPTH, from which each folder of the judge
        is given (test_one_mount_order_whatever_docker_draws), and each folder lands where it is named."""
        image = container.build_image([], os.environ.get("BEE_JUDGE_NETWORK"))
        folders = [container.open_folder(os.path.join(self.workdir, "depth-" + n)) for n in ("a", "b")]
        r = container.Docker(container.image_id(image)).launch(
            ["cat", "/proc/self/mountinfo"], [(folders[0], "/sources", True), (folders[1], "/output", False)], pids=8, timeout_seconds=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        points = [line_text.split()[4] for line_text in r.stdout.decode().splitlines()]
        self.assertTrue({"/sources", "/output", "/tmp", "/dev/shm", "/etc/hosts"} <= set(points), points)
        self.assertLess(max(p.count("/") for p in points if p not in ("/sources", "/output")), container.DEPTH)
        self.assertFalse(set(points) - set(DOCKER_MOUNTS) - {"/", "/sources", "/output", "/tmp", "/etc/hostname", "/etc/hosts",
                                                                 "/etc/resolv.conf", "/proc/fs", "/proc/irq", "/proc/sysrq-trigger",
                                                                 "/proc/interrupts", "/proc/keys", "/proc/timer_list",
                                                                 "/proc/kcore", "/proc/latency_stats", "/proc/timer_stats",
                                                                 "/proc/sched_debug", "/proc/scsi"}
                         - {p for p in points if p.startswith("/sys/fs/cgroup/")})

    def test_machine_failure(self):
        """ruche-0136, with Docker: the container of B's build created with a runtime Docker does not have, then the one of
        B's verification that the runtime fails to start (OCI): each time the judge ends with code 2, and its judge.json says
        an error of the environment, a failure of the machine; before ruche-0136, both were refusals of B."""
        folder = os.path.join(self.workdir, "broken-docker")
        os.makedirs(folder)
        with open(os.path.join(folder, "docker"), "w", encoding="utf-8") as f:
            f.write(BROKEN_DOCKER.replace("DOCKER", repr(shutil.which("docker"))))
        os.chmod(os.path.join(folder, "docker"), 0o755)
        for rank, options in ((4, "--runtime bee-broken"), (8, "--entrypoint /bee-broken")):
            path, account = (os.path.join(folder, f"{n}-{rank}") for n in ("judge.json", "count"))
            with self.subTest(rank=rank), mock.patch.dict(os.environ, {"PATH": folder + os.pathsep + os.environ["PATH"],
                                                                      "FAILURE_RANK": str(rank), "FAILURE_OPTIONS": options, "FAILURE_COUNT": account}):
                code, _, output_text = self.run_the_judge(f"failure-{rank}", self.prepare(f"failure-{rank}"), True, extra=["--json", path])
                self.assertEqual(code, 2, output_text)
                with open(path, encoding="utf-8") as f:
                    j = json.load(f)["judge"]
                self.assertEqual((j["code"], j["outcome"], j["machine_failure"]), (2, "environment_error", True))
                with open(account) as f:
                    self.assertEqual(f.read(), str(rank))

    def test_simulated_failure(self):
        """ruche-0136, with Docker: B's code writes a daemon's error and exits with 125, as a failing runtime would: the
        container ran to its end, so it is a refusal of B (code 1, « refusal » in judge.json), never an error of the environment."""
        def simulate(text, corpus):
            text = replace_with(text, INCLUDE, INCLUDE + "#include <stdio.h>\n#include <stdlib.h>\n")
            return replace_with(text, COMPRESS_START, COMPRESS_START + f"    fputs({json.dumps(OCI)}, stderr); exit(125);\n")
        path = os.path.join(self.workdir, "simulated_failure.json")
        code, _, output_text = self.run_the_judge("simulated_failure", self.prepare("simulated_failure", simulate), True, extra=["--json", path])
        self.assertEqual(code, 1, output_text)
        with open(path, encoding="utf-8") as f:
            j = json.load(f)["judge"]
        self.assertEqual((j["code"], j["outcome"], j["machine_failure"]), (1, "refusal", False))

    def test_early_exit(self):
        code, _, output_text = self.run_the_judge("early_exit", self.prepare("early_exit", early_exit), True)
        self.assertEqual(code, 1)
        self.assertIn("REFUSAL", output_text)

    def test_fake_stopwatches(self):
        code, report, _ = self.run_the_judge("fake_stopwatches", self.prepare("fake_stopwatches", fake_stopwatches), True)
        self.assertEqual(code, 0)
        self.assertIn("forbidden_symbol", self.types_suspects(report))
        m = report["metrics"]["compression_throughput"]
        self.assertLess(m["B"]["median"], m["A"]["median"])

    def test_precomputed_table(self):
        code, _, output_text = self.run_the_judge("precomputed_table", self.prepare("precomputed_table", precomputed_table), True)
        self.assertEqual(code, 1)
        self.assertIn("REFUSAL", output_text)

    def test_valgrind_request(self):
        code, report, _ = self.run_the_judge("valgrind_request", self.prepare("valgrind_request", valgrind_request))
        self.assertEqual(code, 0)
        self.assertIn("valgrind_preamble", " ".join(s["detail"] for s in report["judge"]["suspicious_constructs"]))

    def test_fake_summary(self):
        code, report, _ = self.run_the_judge("fake_summary", self.prepare("fake_summary", fake_summary))
        self.assertEqual(code, 0)
        self.assertIn("external_call", self.types_suspects(report))
        m = report["instructions"]["instructions_compression"]
        self.assertGreater(m["B"], 0.99 * m["A"])

    def test_moved_work(self):
        code, report, _ = self.run_the_judge("moved_work", self.prepare("moved_work", moved_work))
        self.assertEqual(code, 0)
        self.assertEqual(report["judge"]["suspicious_constructs"], [])
        m = report["instructions"]["instructions_compression"]
        self.assertLess(m["gain"], 0.002, "the work moved into rle_bound must stay counted")

    def test_plugin_of_the_pr(self):
        """B is wrong (its compressed output cut short) but brings a plugin and a harness that accept everything."""
        source_b = self.prepare("plugin_of_the_pr", lambda t, c: replace_with(t, "    return o + 4;\n", "    return o > 8 ? o - 1 : o + 4;\n"))
        shutil.copytree(os.path.join(self.toy, "bee"), os.path.join(source_b, "bee"))
        with open(toy_file(source_b, "plugin"), "a", encoding="utf-8") as f:
            f.write("\nProject.verify = lambda self, a, b, e: 1\nProject.compressed = lambda self, a, b, r, o: 0\n")
        code, _, output_text = self.run_the_judge("plugin_of_the_pr", source_b, True)
        self.assertEqual(code, 1)
        self.assertIn("REFUSAL", output_text)

    def test_empty_surveys(self):
        base = self.changed_base("empty_surveys", "build", 'echo "build done"',
                                 ': > "$output/disassembly.txt"\necho "build done"')
        code, report, _ = self.run_the_judge("empty_surveys", self.prepare("empty_surveys", valgrind_request), True, base=base)
        self.assertEqual(code, 0)
        self.assertIn("valgrind_preamble", " ".join(s["detail"] for s in report["judge"]["suspicious_constructs"]))

    def test_forgotten_object(self):
        """The project's object is compiled outside obj/: it would escape the analysis, the judge stops."""
        base = self.changed_base("forgotten_object", "build", '"$output/obj/rle.o"', '"$output/rle.o"')
        code, _, output_text = self.run_the_judge("forgotten_object", self.prepare("forgotten_object"), True, base=base)
        self.assertEqual(code, 2)
        self.assertIn("without an object", output_text)

    def test_split_tokens(self):
        code, report, _ = self.run_the_judge("split_tokens", self.prepare("split_tokens", split_tokens), True)
        self.assertEqual(code, 0)
        self.assertIn("valgrind_preamble", " ".join(s["detail"] for s in report["judge"]["suspicious_constructs"]))

    def test_distracted_plugin(self):
        """The base's plugin forgets to read B's outputs of a scenario: an error, never an acceptance."""
        base = self.changed_base("distracted_plugin", "plugin",
                                 'self.correct(a, b, e, f"{s}/")', 'self.correct(a, a, e, f"{s}/")')
        code, _, output_text = self.run_the_judge("distracted_plugin", self.prepare("distracted_plugin"), True, base=base)
        self.assertEqual(code, 2)
        self.assertIn("no output of B", output_text)

    def test_forbidden_call(self):
        """Adversarial review no. 2: getenv is flagged by its name, whatever namespace is declared."""
        code, report, _ = self.run_the_judge("forbidden_call", self.prepare("forbidden_call", call_laundered_by_prefix), True)
        self.assertEqual(code, 0)
        self.assertIn("getenv", " ".join(s["detail"] for s in report["judge"]["suspicious_constructs"]))

    def test_seeded_bytes(self):
        code, report, _ = self.run_the_judge("seeded_bytes", self.prepare("seeded_bytes", lambda t, c: t + asm_bytes("48b80f05909090909090")), True)
        self.assertEqual(code, 0)
        self.assertIn("bytes", self.types_suspects(report))

    def test_same_conditions(self):
        """ruche-0037: B records everything it can observe of its process at its first call: the same digests in every
        mode (counters aside, the inputs differing; EXCEPTIONS_INSTRUCTIONS aside under the instruction counter)."""
        code, containers = self.spied_judge_run(self.prepare("same_conditions", spy))
        self.assertEqual(code, 0)
        surveys = {}
        for entry, error in containers:
            _, options, line_text = entry.splitlines()
            surveys.setdefault((options.split()[1] == "1", line_text.split("\t")[0]), []).append(spy_reading(error))
        self.assertEqual(sorted(surveys), [(False, "compression"), (False, "decompression"), (False, "verify"),
                                           (True, "compression"), (True, "decompression")])
        natives = [r for (valgrind, _), list_of in sorted(surveys.items()) if not valgrind for r in list_of]
        self.assertEqual(len(natives), 6)  # verification (2 sides), 2 repetitions × 2 scenarios
        for r in natives:
            self.assertEqual(fingerprints(r), fingerprints(natives[0]))
        for r in surveys[(True, "compression")] + surveys[(True, "decompression")]:
            self.assertEqual(fingerprints(r, EXCEPTIONS_INSTRUCTIONS), fingerprints(natives[0], EXCEPTIONS_INSTRUCTIONS))

    def test_same_mounts(self):
        """ruche-0117 (points 3, 6 and 7): every container of a side gets the same inputs; B, run at different positions (orders
        drawn so that each scenario changes place), in both variant passes (A first, then B first), at both repetitions and in
        every mode (verification, timed, instruction count), sees the same thing, mount by mount: mount lines, inode, device,
        links, mode, owner, size, access and modification times, directory order, statfs; the ages of its change and birth
        times within AGE_MAX_MS; each tmpfs's f_fsid the same or drawn anew; REST aside (outside the judge's mounts). The
        8 MiB each container leaves in its outputs are seen by none of the others."""
        base = toy_with_four_scenarios(os.path.join(self.workdir, "base-same-mounts"), self.toy)
        with open(toy_file(base, "plugin"), "a", encoding="utf-8") as f:
            f.write(SAME_INPUTS)
        seed = next(g for g in (f"{i:02x}" * 16 for i in range(256)) if (lambda t: (lambda o, p: all(
            o.index(s) != p.index(s) for s in FOUR_SCENARIOS))(t.sample(list(FOUR_SCENARIOS), 4), t.sample(list(FOUR_SCENARIOS), 4)))(
            random.Random(bytes.fromhex(g))))
        output_text = io.StringIO()
        code, containers = self.spied_judge_run(self.prepare("same_mounts", mounts_spy), base,
                                               ["--order-seed", seed], output_text)
        self.assertEqual(code, 0)
        unfolding = json.loads(output_text.getvalue())["judge"]["scenarios"]["steps"]
        self.assertEqual([(e["step"], e["variants"]) for e in unfolding], [("measurement", "AB"), ("measurement", "BA"), ("instructions", "AB")])
        by_side = {}
        for entry, error in containers:
            survey = mounts_reading(error)
            if entry.splitlines()[1].split()[1] == "1":
                survey = {k: v for k, v in survey.items() if k not in REST_INSTRUCTIONS}
            now_instant = float(survey.pop("now"))
            for key in [k for k in survey if k.startswith("times:") and not k[6:].startswith(JUDGE_MOUNTS)]:
                survey["age" + key] = " ".join(str(round(1000 * (now_instant - float(x)))) for x in survey.pop(key).split())
            by_side.setdefault("f" if "stat:/inputs/#0/#0" in survey else "z", []).append(survey)
        self.assertEqual({c: len(l) for c, l in by_side.items()}, {"f": 6, "z": 6})  # verification, 2 × 2 timed, instructions
        for side, list_of in by_side.items():
            self.assertIn(f"stat:/inputs/#{'0' if side == 'f' else '2'}/#3", list_of[0])  # four inputs on the side's folder
            for key in sorted(set().union(*list_of)):
                values_of = [r.get(key) for r in list_of if key in r or key not in REST_INSTRUCTIONS]
                with self.subTest(side=side, key=key):
                    if key in REST or key.startswith(REST_PREFIXES):
                        continue
                    if key.startswith(("age:", "agetimes:")):
                        for ages in zip(*(map(int, v.split()) for v in values_of)):
                            self.assertLessEqual(max(ages) - min(ages), AGE_MAX_MS, values_of)
                    elif key.startswith("fsid:"):
                        self.assertIn(len(set(values_of)), (1, len(values_of)), values_of)
                    else:
                        self.assertEqual(len(set(values_of)), 1, values_of)

    def run_modes(self, source_b, modes):
        """B built and run by the judge's own containers on one /inputs (the f side of a repetition), once per mode:
        [(mode, valgrind)]. Returns its records, in order."""
        plugin, workdir = judge.load_plugin(self.toy, {})[0], tempfile.mkdtemp(dir=self.workdir)
        os.chmod(workdir, 0o755)
        docker = container.Docker(container.build_image(plugin.PACKAGES, os.environ.get("BEE_JUDGE_NETWORK")))
        sources = judge.copy_sources(source_b, os.path.join(workdir, "sources-B"), plugin.SOURCES, plugin.REQUIRED_SOURCES)
        tools = judge.copy_tooling(self.toy, self.toy, os.path.join(workdir, "tooling"), plugin)
        judge.build(docker, plugin, sources, tools, os.path.join(workdir, "build-B"), "B", workdir)
        run = container.Execution(docker, container.compile_stopwatch(docker, workdir),
                                        {"B": judge.variant(os.path.join(workdir, "build-B"), os.path.join(workdir, "variant-B"))},
                                        workdir)
        given = [e for e in plugin.repetition(random.Random(1), plugin.corpus(self.toy)) if e.side == "f"]
        folder = judge.prepare(workdir, "", judge.rename(random.Random(1), given)[0], ("f", "z"))["f"]
        errors, launch = [], docker.launch

        def spy_on(*a, **k):
            r = launch(*a, **k)
            errors.append(r.stderr.decode("utf-8", "replace"))
            return r
        docker.launch = spy_on
        for mode, valgrind in modes:
            command = (judge.VALGRIND if valgrind else []) + [container.HARNESS, mode, "/inputs", "/outputs"]
            run.launch("B", folder, judge.outputs_of(workdir, "", ("f",))["f"], [(mode, command)], valgrind=valgrind, timeout_seconds=600)
        return [spy_reading(e) for e in errors]

    def test_same_counters(self):
        """ruche-0037: on the same /inputs, B observes the same thing in every mode, the counters it can read about itself
        included (exactly, or within NOISE); under the instruction counter, EXCEPTIONS_INSTRUCTIONS and the counters aside."""
        modes = [("verify", False), ("compression", False), ("decompression", False), ("compression", True)]
        surveys = self.run_modes(self.prepare("same_counters", spy), modes)
        natives, under_valgrind = surveys[:3], surveys[3]
        values_of = [counters(r) for r in natives]
        for r, c in zip(natives[1:], values_of[1:]):
            self.assertEqual(fingerprints(r), fingerprints(natives[0]))
            self.assertEqual({k: v for k, v in c.items() if k not in NOISE}, {k: v for k, v in values_of[0].items() if k not in NOISE})
        for name, gap in NOISE.items():
            self.assertLessEqual(max(c[name] for c in values_of) - min(c[name] for c in values_of), gap, name)
        self.assertEqual(fingerprints(under_valgrind, EXCEPTIONS_INSTRUCTIONS), fingerprints(natives[0], EXCEPTIONS_INSTRUCTIONS))

    def base_that_states_the_mode(self, name):
        """A copy of the toy whose harness tells the library the mode (int rle_measured): the case mixing must catch."""
        base = os.path.join(self.workdir, "base-" + name)
        shutil.copytree(self.toy, base, ignore=shutil.ignore_patterns("__pycache__"))
        path = toy_file(base, "harness")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        text = replace_with(text, "static char inputs[256], outputs[256];\n", "static char inputs[256], outputs[256];\nint rle_measured = 0;\n")
        text = replace_with(text, "    explicit_bzero(mode, sizeof(mode));\n",
                          '    rle_measured = strcmp(mode, "verify") != 0;\n    explicit_bzero(mode, sizeof(mode));\n')
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return base

    def test_wrong_output_timed(self):
        """ruche-0037: B is right whenever it is verified, and wrong when timed on inputs other than the corpus's (the
        base's harness is made to tell it the mode): the verification inputs mixed into the timed inputs refuse it."""
        code, report, output_text = self.run_the_judge("wrong_output_timed",
                                           self.prepare("wrong_output_timed", wrong_output_timed), True,
                                           base=self.base_that_states_the_mode("wrong_output_timed"))
        self.assertEqual(code, 1, output_text)
        self.assertIn("REFUSAL", output_text)
        self.assertIn("compression/c/e", output_text)  # a timed output of a mixed-in input, not the verification step

    def test_changing_output_timed(self):
        """ruche-0037: with outputs allowed to differ from the base's, B gives a valid but different output when timed:
        its output of a mixed-in input differs from its own in verification, refused."""
        source_b = self.prepare("changing_output_timed", lambda t, c: replace_with(
            replace_with(t, INCLUDE, INCLUDE + "extern int rle_measured;\n"), "        if (run >= 3) {", "        if (run >= 3 && !rle_measured) {"))
        code, _, output_text = self.run_the_judge("changing_output_timed", source_b, True, options=["compressed_output=may_change"],
                                     base=self.base_that_states_the_mode("changing_output_timed"))
        self.assertEqual(code, 1, output_text)
        self.assertIn("differs from its output in verification", output_text)

    def test_side_without_mixing(self):
        """ruche-0037: a measured side without verification inputs to mix in is an error of the plugin, never a pass."""
        base = self.changed_base("side_without_mixing", "plugin", "return self.make_inputs(files, self.streams(rng, files))",
                                 "return self.make_inputs(files, [])")
        code, _, output_text = self.run_the_judge("side_without_mixing", self.prepare("side_without_mixing"), True, base=base)
        self.assertEqual(code, 2, output_text)
        self.assertIn("no verification input", output_text)

    def test_instructions_without_mixing(self):
        """ruche-0037: an instruction-count scenario that got no verification input (none within the prefix) is flagged."""
        code, report, output_text = self.run_the_judge("instructions_without_mixing", self.prepare("instructions_without_mixing"),
                                           extra=["--instructions-prefix", "1"])
        self.assertEqual(code, 0, output_text)
        self.assertEqual(report["judge"]["verification"]["instructions_without_mixing"], ["decompression"])

    def test_symbolic_link(self):
        source_b = self.prepare("symbolic_link")
        os.remove(os.path.join(source_b, "rle.c"))
        os.symlink(os.path.join(self.toy, "rle.c"), os.path.join(source_b, "rle.c"))
        code, _, output_text = self.run_the_judge("symbolic_link", source_b, True)
        self.assertEqual(code, 1)
        self.assertIn("symbolic link", output_text)

    def bounded_judge(self, name, source_b, *options):
        """judge.py against the toy base, with the options given (ruche-0038); returns (code, report, log, seconds)."""
        command = [sys.executable, os.path.join(HERE, "judge.py"), "--tooling", self.toy, "--source-a", self.toy, "--source-b", source_b,
                    "--repetitions", "2", "--warmup", "0", "--no-instructions", *options]
        command += ["--build-network", os.environ["BEE_JUDGE_NETWORK"]] if os.environ.get("BEE_JUDGE_NETWORK") else []
        beginning = time.monotonic()
        r = subprocess.run(command, capture_output=True, text=True, timeout=1800)
        print(f"\n[{name}] code {r.returncode} : {r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ''}", file=sys.stderr)
        return r.returncode, json.loads(r.stdout) if r.returncode == 0 else None, r.stderr, time.monotonic() - beginning

    def test_job_report(self):
        """ruche-0038: judge.json names the commits judged and the image's id, lists SUSPICIOUS_MAX suspicious constructs and
        counts the rest; its figures are those report.py publishes, and a report changed afterwards is refused. ruche-0117: the
        most serious first, a forbidden call and a global symbol of 2,000 characters added after 125 pragmas, each kind counted,
        each detail cut to DETAIL_MAX; report.py --verify wants the code 0 and the judged commits."""
        lines = "".join(f"#pragma rle_mark_{i:03d}\n" for i in range(judge.SUSPICIOUS_MAX + 25))
        lines += '#include <stdlib.h>\nchar *rle_env(void) { return getenv("BEE"); }\nint bee_' + "x" * 2000 + " = 1;\n"
        path, base, head = os.path.join(self.workdir, "job_report.json"), "4" * 40, "5" * 40
        code, report_, log_, _ = self.bounded_judge("job_report", self.prepare("job_report", lambda t, c: t + lines),
                                                       "--base", base, "--head", head, "--json", path)
        self.assertEqual(code, 0, log_)
        j = report_["judge"]
        self.assertEqual((j["base"], j["head"], len(j["suspicious_constructs"]), j["suspicious_constructs_omitted"]),
                         (base, head, judge.SUSPICIOUS_MAX, 28))
        self.assertEqual([s["type"] for s in j["suspicious_constructs"][:3]], ["forbidden_call", "defined_symbol", "source"])
        self.assertEqual(j["suspicious_constructs_by_type"], {"forbidden_call": 1, "source": 126, "defined_symbol": 1})
        self.assertLessEqual(max(len(s["detail"]) for s in j["suspicious_constructs"]), analysis.DETAIL_MAX)
        self.assertEqual(log_.count("suspicious construct:"), judge.SUSPICIOUS_MAX)
        self.assertRegex(j["image_id"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(j["image_id"], container.image_id(j["image"]))
        published_ones = report.digits(report.read(path))
        self.assertEqual((published_ones["suspects"], published_ones["outputs_compared"], published_ones["base"], published_ones["head"]),
                         (str(judge.SUSPICIOUS_MAX + 28), str(j["verification"]["outputs_compared"]), base, head))
        published_ones = report.publish(path, "0")
        self.assertEqual(report.verify(path, published_ones, base, head), report_)
        for others in ((head, base), (base, "6" * 40)):
            with self.assertRaises(report.Gap):
                report.verify(path, published_ones, *others)
        j["suspicious_constructs"].pop()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report_, f, ensure_ascii=False, indent=2)
        with self.assertRaises(report.Gap):
            report.verify(path, published_ones, base, head)

    def test_endless_writing(self):
        """ruche-0038: a judged code that writes without end is stopped at the file size bound of every container (SIGXFSZ):
        a refusal, in bounded time."""
        def endless(text, corpus):
            text = replace_with(text, INCLUDE, INCLUDE + "#include <stdio.h>\n")
            return replace_with(text, COMPRESS_START, COMPRESS_START +
                             '    { static unsigned char rle_block[1 << 16]; FILE *rle_f = fopen("/outputs/rle_endless", "wb");\n'
                             "      while (rle_f) fwrite(rle_block, 1, sizeof rle_block, rle_f); }\n")
        code, _, log_, duration = self.bounded_judge("endless_writing", self.prepare("endless_writing", endless))
        self.assertEqual(code, 1, log_)
        self.assertIn("signal 25", log_)
        self.assertLess(duration, 600)

    def test_full_disk(self):
        """ruche-0038: a judged code that fills the work folder (a small tmpfs here, given as --workdir): a
        refusal, in bounded time, and the folder left empty."""
        folder, sudo = os.path.join(self.workdir, "bounded-tmpfs"), ([] if os.geteuid() == 0 else ["sudo", "-n"])
        os.makedirs(folder)
        options = f"size=96m,nr_inodes=4096,mode=0755,nosuid,nodev,uid={os.getuid()},gid={os.getgid()}"
        if subprocess.run(sudo + ["mount", "-t", "tmpfs", "-o", options, "tmpfs", folder], capture_output=True).returncode != 0:
            self.skipTest("mounting a tmpfs needs root or sudo without a password")
        self.addCleanup(subprocess.run, sudo + ["umount", folder], capture_output=True)

        def fill_in(text, corpus):  # files of 32 MiB, 2 GiB at most, until the folder is full
            text = replace_with(text, INCLUDE, INCLUDE + "#include <stdio.h>\n")
            return replace_with(text, COMPRESS_START, COMPRESS_START +
                             "    { static unsigned char rle_block[1 << 16]; static int rle_done; char rle_p[64]; int k, j = 512;\n"
                             "      for (k = 0; !rle_done && k < 64 && j == 512; k++) {\n"
                             '        FILE *rle_f; snprintf(rle_p, sizeof rle_p, "/outputs/rle_full_%d", k);\n'
                             '        if (!(rle_f = fopen(rle_p, "wb"))) break;\n'
                             "        for (j = 0; j < 512 && fwrite(rle_block, 1, sizeof rle_block, rle_f) == sizeof rle_block; j++) ;\n"
                             "        if (fclose(rle_f) != 0) j = 0; }\n"
                             "      rle_done = 1; }\n")
        code, _, log_, duration = self.bounded_judge("full_disk", self.prepare("full_disk", fill_in), "--workdir", folder)
        self.assertEqual(code, 1, log_)
        self.assertLess(duration, 600)
        self.assertEqual(os.listdir(folder), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
