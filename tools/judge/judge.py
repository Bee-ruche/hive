#!/usr/bin/env python3
"""Bee's common judge: run a PR's code in containers and judge it from outside, for any project.

Specification: docs/common-judge.md. The common judge does what protects and depends on no project; the project's
PLUGIN (bee/judge/project.py, read from the PR's BASE, never from the PR) says how to build, which inputs to give, how
to verify and what to measure.

What the common judge guarantees, whatever the plugin:
- this program (the host) NEVER executes a file from the PR. Compilation, execution and instruction
  counting take place in containers without network, read-only, without privilege, limited to
  two processes for execution, which see only their inputs and an outputs folder;
- each side of inputs (« f », « z »…) has its own container: a harness never sees the inputs
  of another side; each scenario has its own, with its own outputs only, frozen (SHA-256) as soon as the
  container ends: the comparison reads only what was frozen; their order is drawn at each repetition;
- the seed of the inputs drawn at random is chosen here, AFTER compilation; the plugin perturbs the
  measurements' inputs at each repetition;
- processor time and memory are measured by the kernel (wait4) in the common judge's chrono launcher,
  compiled separately; the instruction count covers the harness's whole process and is read on
  Valgrind's last line;
- the outputs are read only through reading.py (no link, no special file, bounded size);
- an analysis of the compiled objects (analysis.py) lists the suspicious constructs.

Usage:
  python3 tools/judge/judge.py --tooling BASE --image-only
  python3 tools/judge/judge.py --tooling BASE --source-a FOLDER --source-b FOLDER [--option KEY=VALUE]…
                              [--repetitions 10] [--warmup 1] [--no-instructions] [--instructions-prefix 131072]
                              [--json judge.json] [--seed HEX]
                              [--build-network host]
  --tooling: copy of the PR's BASE (its bee/judge/project.py is the plugin)
  --source-a / --source-b: repositories of the reference (A, the base) and of the candidate (B, the PR)
Output: a JSON report in ab.py's format (measurements, metrics, instructions) plus a « judge » section.
Exit code: 0 if all of B's outputs are correct, 1 if the judge refuses B, 2 if the environment
is not suitable (Docker missing, a base that does not compile, an invalid plugin, a badly set-up judge), a failure of the machine
(Docker, its runtime, the image) included. With --json, judge.json says it in every case (judge.code, judge.outcome: ISSUES); its keys
and values are English (ruche-0148).
"""

import argparse
import collections
import contextlib
import glob
import hashlib
import importlib.util
import json
import os
import platform
import random
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import analysis  # noqa: E402
import container  # noqa: E402
import inputs as inputs_module  # noqa: E402
import stats  # noqa: E402
from reading import JudgeError, MachineFailure, Outputs, Refusal, clean, freeze, log, require  # noqa: E402

COMMON_VERSION = 5   # the tag judge-v5
JUDGE_VERSION = 3      # verdict.json's numbering: 2 = minizBee's judge (miniz-0031), 3 = the common judge (its tag in « common »)
ISSUES = {0: "correct", 1: "refusal", 2: "environment_error"}  # judge.json's judge.outcome for each exit code (ruche-0136)
FAILURE = {}  # what judge.json says when the judge stops (code 1 or 2): its path and the judge's identity, set by main
# A base holds its plugin at PLUGIN_PATH; its names are those below (docs/common-judge.md), its metrics' directions DIRECTIONS.
PLUGIN_PATH = os.path.join("bee", "judge", "project.py")
DIRECTIONS = ("higher", "lower")  # a metric's direction: which value is the better
REQUIRED_ATTRIBUTES = ("NAME", "SOURCES", "REQUIRED_SOURCES", "TOOLING", "BASE_HEADERS", "BUILD",
                       "PREFIXES", "SIDES", "SCENARIOS", "INSTRUCTIONS", "METRICS")
REQUIRED_METHODS = ("corpus", "verification", "verify", "fixed", "repetition", "instructions", "scenario")
SURVEYS = (("symbols", "symbols.txt"), ("sections", "sections.txt"), ("disassembly", "disassembly.txt"))
OBJECT = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.+-]{0,127}\.o")
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")
PREFIX = re.compile(r"[A-Za-z][A-Za-z0-9]{0,30}_")  # a word followed by « _ »: an identifier boundary
ALLOWED_MAX = 64
SUSPICIOUS_MAX = 100  # judge.json lists at most this many suspicious constructs and counts the rest (suspicious_constructs_omitted)
# Kinds of suspicious construct, the most serious first: judge.json lists them in this order, and counts each kind (ruche-0117).
SEVERITY = ("incomplete_analysis", "architecture", "forbidden_call", "forbidden_symbol", "instruction", "bytes", "section", "symbol",
            "defined_symbol", "external_call", "source")
NEVER_ALLOWED = analysis.NEVER_ALLOWED
UNITS = (".c", ".S", ".s", ".cc", ".cpp", ".cxx")  # translation units: each must leave its object
ANALYSED_ARCHITECTURES = ("x86_64", "amd64")  # mnemonics and Valgrind preamble known to analysis.py
VALGRIND = ["/usr/bin/valgrind", "--tool=cachegrind", "--cache-sim=no", "--vgdb=no", "--cachegrind-out-file=/dev/null"]
COMMIT, HISTORY_MAX, REPO = re.compile(r"[0-9a-f]{40}"), 16, re.compile(r"[A-Za-z0-9-]+/(?!\.\.?$)[A-Za-z0-9_.-]+")


def common_tag(version=COMMON_VERSION):
    """The tag of this judge: judge-v<version>."""
    return f"judge-v{version}"


# ------------------------------------------------------------------ plugin

def load_plugin(tooling, options):
    """Loads the tooling's plugin (the BASE's bee/judge/project.py) and checks that it keeps the contract."""
    path, parts = os.path.join(tooling, PLUGIN_PATH), PLUGIN_PATH.split(os.sep)
    if not os.path.isfile(path):
        raise JudgeError(f"plugin not found: {PLUGIN_PATH} in {tooling}")
    if any(os.path.islink(os.path.join(tooling, *parts[:i + 1])) for i in range(len(parts))):
        raise JudgeError(f"plugin {PLUGIN_PATH}: every component of its path must be a real folder or file, not a link")
    with open(path, "rb") as f:
        fingerprint = hashlib.sha256(f.read()).hexdigest()
    spec = importlib.util.spec_from_file_location("bee_judge_plugin", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "Project"):
        raise JudgeError("the plugin defines no class Project")
    plugin = module.Project(dict(options))
    missing = [a for a in REQUIRED_ATTRIBUTES if not hasattr(plugin, a)] + \
              [m for m in REQUIRED_METHODS if not callable(getattr(plugin, m, None))]
    if missing:
        raise JudgeError("incomplete plugin: " + ", ".join(missing))
    if any(not (isinstance(m, (tuple, list)) and len(m) == 3 and m[1] in DIRECTIONS) for m in plugin.METRICS):
        raise JudgeError("plugin's METRICS: (name, direction, unit) each, the direction higher or lower")
    sides = tuple(plugin.SIDES)
    if not sides or any(not inputs_module.SIDE_ALLOWED.fullmatch(s) for s in sides) or len(set(sides)) != len(sides):
        raise JudgeError("plugin's SIDES invalid")
    for s, side in plugin.SCENARIOS.items():
        if side not in sides or not inputs_module.NAME_ALLOWED.fullmatch(s):
            raise JudgeError(f"invalid scenario in the plugin: {s}")
    if any(s not in plugin.SCENARIOS for s in plugin.INSTRUCTIONS):
        raise JudgeError("plugin's INSTRUCTIONS: unknown scenario")
    # Namespace and allowed functions: an empty or too short prefix would switch off two categories of
    # the objects' analysis (adversarial review of 28 October); the functions that deceive the measurement are never allowed.
    prefixes, allowed = tuple(plugin.PREFIXES), tuple(getattr(plugin, "ALLOWED", ()))
    if not prefixes or any(not isinstance(p, str) or not PREFIX.fullmatch(p) for p in prefixes):
        raise JudgeError("plugin's PREFIXES invalid: at least one prefix, each a word ending in « _ » (mz_, yaml_…)")
    covering = sorted(n for n in NEVER_ALLOWED if n.startswith(prefixes))
    if covering:
        raise JudgeError("plugin's PREFIXES: they would cover functions never allowed: " + ", ".join(covering))
    if len(allowed) > ALLOWED_MAX or any(not isinstance(n, str) or not IDENTIFIER.fullmatch(n) for n in allowed):
        raise JudgeError(f"plugin's ALLOWED invalid: at most {ALLOWED_MAX} function names")
    forbidden = sorted(set(allowed) & NEVER_ALLOWED)
    if forbidden:
        raise JudgeError("plugin's ALLOWED: functions never allowed: " + ", ".join(forbidden))
    if hasattr(plugin, "DIFF"):
        raise JudgeError("DIFF no longer exists: the diff analyzed is SOURCES' (adversarial review of 28 October)")
    for relative in list(plugin.TOOLING) + [plugin.BUILD]:
        if os.path.isabs(relative) or ".." in relative.split("/"):
            raise JudgeError(f"invalid tooling path in the plugin: {relative}")
    return plugin, fingerprint


# ------------------------------------------------------------------ preparation and build

def _no_link(repo, relative):
    """True if no component of repo/relative is a symbolic link and it is a regular file."""
    path = repo
    parts = relative.split(os.sep)
    for i, p in enumerate(parts):
        path = os.path.join(path, p)
        st = os.lstat(path)
        if stat.S_ISLNK(st.st_mode):
            raise Refusal(f"{relative}: symbolic link refused")
        if i < len(parts) - 1 and not stat.S_ISDIR(st.st_mode):
            return False
    return stat.S_ISREG(os.lstat(path).st_mode)


def copy_sources(repo, destination, patterns, required):
    """Copies the project's files (glob patterns relative to the root), refusing any symbolic link."""
    os.makedirs(destination, exist_ok=True)
    repo = os.path.abspath(repo)
    found = set()
    for pattern in patterns:
        if os.path.isabs(pattern) or ".." in pattern.split("/"):
            raise JudgeError(f"invalid sources pattern: {pattern}")
        for path in sorted(glob.glob(os.path.join(glob.escape(repo), pattern))):
            relative = os.path.relpath(path, repo)
            if relative in found or not _no_link(repo, relative):
                continue
            target = os.path.join(destination, relative)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(path, target)
            found.add(relative)
    for r in required:
        if r not in found:
            raise Refusal(f"{r} not found in {repo}")
    return destination


def copy_tooling(tooling, source_a, destination, plugin):
    """What the BASE gives the container: its tooling folders (TOOLING) and its headers (BASE_HEADERS).

    The base's headers are copied into /tooling/base/: the harness is compiled with them, not with
    the PR's (a macro slipped into a header of the PR cannot rewrite the harness)."""
    for relative in plugin.TOOLING:
        source = os.path.join(tooling, relative)
        if os.path.islink(source) or not os.path.isdir(source):
            raise JudgeError(f"tooling folder missing from the base: {relative}")
        shutil.copytree(source, os.path.join(destination, relative), symlinks=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    copy_sources(source_a, os.path.join(destination, "base"), plugin.BASE_HEADERS, ())
    return destination


def expected_objects(sources):
    """One object obj/<name>.o per translation unit (.c, .S, .cc…) copied from the variant's SOURCES.

    Two units of the same name in two folders cannot each leave its object: refused (listed as duplicates)."""
    seen = {}
    for folder, _, names in os.walk(sources):
        for n in names:
            root, extension = os.path.splitext(n)
            if extension in UNITS:
                seen.setdefault(root + ".o", []).append(os.path.relpath(os.path.join(folder, n), sources))
    duplicates = sorted(c for c, l in seen.items() if len(l) > 1)
    return set(seen), duplicates


def build(docker, plugin, sources, tooling, output, label, workdir):
    """Compiles a variant in the container (the base's BUILD script), then surveys its objects.

    The script's contract: the linked harness in <output>/execution, and EACH object of the project in
    <output>/obj/<name>.o (one per .c file of SOURCES). The analysis surveys (nm, objdump) are then produced
    by the common judge itself, on all these objects: a build script can neither omit
    nor empty them (adversarial review of 28 October)."""
    container.open_folder(output)
    command = ["sh", "/tooling/" + plugin.BUILD, "/sources", "/tooling", "/output"]
    r = docker.launch(command, [(sources, "/sources", True), (tooling, "/tooling", True), (output, "/output", False)],
                      pids=64, timeout_seconds=900)
    failure = JudgeError if label == "A" else Refusal
    if r.returncode != 0:
        raise failure(f"the compilation of {label} failed: " + clean(r.stderr))
    obj_folder = os.path.join(output, "obj")
    if os.path.islink(obj_folder) or not os.path.isdir(obj_folder):
        raise failure(f"{label}: no obj/ folder after the build")
    objects = []
    for n in sorted(os.listdir(obj_folder)):
        st = os.lstat(os.path.join(obj_folder, n))
        if not n.endswith(".o"):
            continue
        if not OBJECT.fullmatch(n) or not stat.S_ISREG(st.st_mode):
            raise failure(f"{label}: invalid object in obj/: {clean(n, 80)}")
        objects.append(n)
    expected, duplicates = expected_objects(sources)
    if duplicates:
        raise failure(f"{label}: translation units of the same name (only one object possible in obj/): "
                      + ", ".join(clean(d, 80) for d in duplicates[:10]))
    missing = sorted(expected - set(objects))
    if missing:
        raise failure(f"{label}: source file(s) without an object in obj/ (not compiled or not surveyable): "
                      + ", ".join(clean(m, 80) for m in missing[:10]))
    if not objects:
        raise failure(f"{label}: no object in obj/")
    surveys_folder = container.open_folder(os.path.join(workdir, f"surveys-{label}"))
    script = ('umask 000 && cd /build/obj && nm -P -A "$@" > /surveys/symbols.txt'
              ' && objdump -h "$@" > /surveys/sections.txt && objdump -d --no-show-raw-insn "$@" > /surveys/disassembly.txt')
    r = docker.launch(["sh", "-c", script, "surveys"] + objects,
                      [(output, "/build", True), (surveys_folder, "/surveys", False)], pids=64, timeout_seconds=900)
    if r.returncode != 0:
        raise failure(f"{label}: analysis surveys failed: " + clean(r.stderr))
    surveys = {key: require(surveys_folder, name, 256 << 20).decode("utf-8", "replace") for key, name in SURVEYS}
    for o in objects:  # each object is in each survey (objdump: « <object>:     file format … »)
        if not any(line.startswith(o + ":") for line in surveys["disassembly"].splitlines()) or \
           not any(line.startswith(o + ":") for line in surveys["sections"].splitlines()):
            raise JudgeError(f"{label}: {o} missing from the analysis surveys: judge badly set up")
    surveys["objects"] = [(o, require(obj_folder, o)) for o in objects]
    surveys["program"] = [("execution", require(output, "execution"))]
    return surveys


def texts_of(folder):
    """The judged files of a variant (those copied from SOURCES), whole: {relative path: text} (latin-1 keeps every byte)."""
    result = {}
    for root, _, names in os.walk(folder):
        for n in names:
            with open(os.path.join(root, n), encoding="latin-1") as f:
                result[os.path.relpath(os.path.join(root, n), folder)] = f.read()
    return result


# ------------------------------------------------------------------ execution

def prepare(workdir, name, inputs, sides):
    """Writes the inputs, one folder per side; returns {side: folder}."""
    inputs_module.check_inputs(inputs, sides)
    folders = {}
    for s in sides:
        folders[s] = os.path.join(workdir, secrets.token_hex(8))  # a neutral name, the same kind in every mode
        inputs_module.write(folders[s], [e for e in inputs if e.side == s], sides)
    return folders


def outputs_of(workdir, name, sides):
    return {s: container.open_folder(os.path.join(workdir, secrets.token_hex(8))) for s in sides}


def launch_by_side(run, variant, folders, outputs, plans, order, **options):
    """One container per scenario, in the drawn order (ruche-0036), its outputs on /outputs as in verification (a neutral
    folder, then <side>/<scenario>), frozen as soon as the container ends. Returns (measurements, an Outputs that reads only the frozen)."""
    measurements, commands, frozen = {}, {s: (side, command) for side, plan in plans.items() for s, command in plan}, {side: {} for side in outputs}
    for label in order:
        side, command = commands[label]
        folder = container.open_folder(os.path.join(os.path.dirname(outputs[side]), secrets.token_hex(8)))
        measurements.update(run.launch(variant, folders[side], folder, [(label, command)], **options))
        frozen[side][label] = "folder"
        frozen[side].update((f"{label}/{k}", e) for k, e in freeze(folder).items())
        os.rename(folder, os.path.join(outputs[side], label))
    return measurements, Outputs(outputs, frozen=frozen)


def step(name, variants, order, measurements):
    """A step of judge.json: order of the variants and of the scenarios, processor time of each scenario (wait4, chrono)."""
    return {"step": name, "variants": "".join(variants), "order": list(order), "cpu_time_s": {
        v: {s: round(m[s]["user_s"] + m[s]["system_s"], 6) for s in order} for v, m in sorted(measurements.items())}}


def rounds_of(rng, inputs):
    """The verification inputs in an order drawn from the judge's seed, round after round: each passes once per round."""
    while inputs:
        order = list(inputs)
        rng.shuffle(order)
        yield from order


def rename(rng, inputs):
    """Inputs as written in every mode, shuffled and renamed (e0000…); also the new name of each input, in the given order."""
    order, neutral = list(range(len(inputs))), [""] * len(inputs)
    rng.shuffle(order)
    for rank, i in enumerate(order):
        neutral[i] = f"e{rank:04d}"
    return [inputs[i]._replace(name=neutral[i]) for i in order], neutral


def interleave(rng, measured, rounds, how_many, names):
    """Measured inputs and `how_many[side]` verification inputs per side from `rounds[side]`, renamed together: neither name
    nor order tells them apart. Returns (inputs, {(side, name): the same input's name in verification, `names`})."""
    addition = [next(rounds[s]) for s, k in how_many.items() for _ in range(k)]
    inputs, neutral = rename(rng, list(measured) + addition)
    return inputs, {(e.side, neutral[len(measured) + j]): names[(e.side, e.name)] for j, e in enumerate(addition)}


def outputs_by_input(frozen):
    """B's verification outputs, as frozen: {(side, written name): [paths relative to the side's folder]}."""
    index = {}
    for side, fingerprint in frozen.items():
        for path, e in fingerprint.items():
            m = re.fullmatch(r"(e\d{4,})(\..*)?", path.rpartition("/")[2])
            if m and e != "folder":
                index.setdefault((side, m.group(1)), []).append(path)
    return index


def same_outputs(index, verification, outputs, mixed, scenarios):
    """B's output of each verification input mixed into a measured run is, byte for byte, its own output in verification
    (same path); each such input has at least one in each scenario of its side (ruche-0117). Returns the number compared."""
    total = 0
    for (side, name), verification_name in mixed.items():
        for s in (s for s, c in scenarios if c == side):
            seen = 0
            for relative in index.get((side, verification_name), []):
                head, bar, last = relative.rpartition("/")
                measured = outputs.written(side, f"{s}/{head}{bar}{name}{last[len(verification_name):]}")
                if measured is not None:
                    seen += 1
                    if measured != verification.written(side, relative):
                        raise Refusal(f"scenario {s}: B's output differs from its output in verification for the same input")
            if not seen:
                raise JudgeError(f"{side}/{name}, scenario {s}: no output of B comparable with verification (the same outputs expected)")
            total += seen
    return total


def variant(build_folder, folder):
    """/variant: the harness alone, copied (no link followed) into a folder of the judge, which sets its times."""
    os.makedirs(folder)
    with open(os.path.join(folder, "execution"), "wb") as f:
        f.write(require(build_folder, "execution"))
    os.chmod(os.path.join(folder, "execution"), 0o755)
    os.chmod(folder, 0o755)
    return folder


def erase(*groups):
    for group in groups:
        for folder in (group.values() if isinstance(group, dict) else group):
            shutil.rmtree(folder, ignore_errors=True)


def counted_integer(n):
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        raise JudgeError("the plugin must return a number of outputs compared (a positive integer)")
    return n


def require_coverage(outputs_b, inputs, step):
    """Each input must have had at least one output of B read by the plugin during the step."""
    forgotten = [e.name for e in inputs if not outputs_b.covers(e.side, e.name)]
    if forgotten:
        raise JudgeError(f"{step}: the plugin read no output of B for {len(forgotten)} input(s) "
                         f"({', '.join(forgotten[:5])}): judge badly set up")


# ------------------------------------------------------------------ declared history

def fetch_history(tooling, text, token=None, budget=600):
    """Fetches into the base's repository the commits its plugin reads (--history), with their trees and blobs but
    no history. Each must be in the base's ancestry, as GitHub's compare API on the calling repository
    (GITHUB_REPOSITORY) says (identical or behind), all checked before any fetch; checks and fetches share one time
    budget. A caller runs it in its own step (--history-only), the only call of judge.py given a token (GH_TOKEN,
    passed to gh alone), before anything loads the plugin and before the PR."""
    commits, repo = sorted(set(text.split())), os.environ.get("GITHUB_REPOSITORY", "")
    if len(commits) > HISTORY_MAX or not all(COMMIT.fullmatch(c) for c in commits):
        raise JudgeError(f"history: at most {HISTORY_MAX} full commit SHAs (40 hexadecimal digits), separated by blanks")
    if not commits:
        return []
    end = time.monotonic() + budget

    def launch(command, env=None):
        try:
            return subprocess.run(command, capture_output=True, text=True, errors="replace", env=env,
                                  timeout=max(0.01, end - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise JudgeError(f"history: checks and fetches exceeded their budget of {budget} s")
        except OSError as e:
            raise JudgeError(f"history: {command[0]} unavailable ({clean(str(e), 200)})")
    base = launch(["git", "-C", tooling, "rev-parse", "HEAD"]).stdout.strip()
    if not REPO.fullmatch(repo) or not COMMIT.fullmatch(base):
        raise JudgeError("history: the calling repository (GITHUB_REPOSITORY, owner/name) and the base's commit are required")
    for c in commits:
        r = launch(["gh", "api", f"repos/{repo}/compare/{base}...{c}", "--jq", ".status"],
                   {**os.environ, "GH_TOKEN": token} if token else None)
        if r.returncode != 0 or r.stdout.strip() not in ("identical", "behind"):
            raise JudgeError(f"history: {c} is not in the ancestry of the base ({clean(r.stdout.strip() or r.stderr, 300)})")
    for c in commits:
        r = launch(["git", "-C", tooling, "fetch", "--quiet", "--no-tags", "--depth=1", "origin", f"{c}:refs/bee/history/{c}"])
        if r.returncode != 0:
            raise JudgeError(f"history: commit {c} not fetched from the base's origin: " + clean(r.stderr, 500))
    return commits


# ------------------------------------------------------------------ program

def options_of(given):
    options = {}
    for o in given or []:
        if "=" not in o:
            raise JudgeError(f"invalid option (KEY=VALUE expected): {o}")
        key, value = o.split("=", 1)
        options[key.strip()] = value.strip()
    return options


def main(argv=None):
    parser = argparse.ArgumentParser(description="Bee's common judge (see the module's help).")
    parser.add_argument("--tooling", required=True, help="copy of the PR's BASE (plugin bee/judge/project.py)")
    parser.add_argument("--source-a")
    parser.add_argument("--source-b")
    parser.add_argument("--image-only", action="store_true",
                        help="builds the container's image (with network, before the PR) and prints its label")
    parser.add_argument("--history-only", action="store_true",
                        help="checks and fetches the declared history (--history) into the base, without loading the plugin")
    parser.add_argument("--history", default="", help="with --history-only: commits fetched into the base")
    parser.add_argument("--judge-source", help="REPO@COMMIT of this judge's code, recorded in judge.json")
    parser.add_argument("--base", help="commit of A, recorded in judge.json")
    parser.add_argument("--head", help="commit of B, recorded in judge.json")
    parser.add_argument("--workdir", help="folder of the work directory (a size-bounded tmpfs, for one)")
    parser.add_argument("--option", action="append", default=[], help="plugin option, KEY=VALUE (repeatable)")
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--no-instructions", action="store_true")
    parser.add_argument("--instructions-prefix", type=int, default=131072)
    parser.add_argument("--instructions-threshold", type=float, default=0.002)
    parser.add_argument("--json")
    parser.add_argument("--seed", help="hexadecimal seed (local reproduction); default: drawn at random")
    parser.add_argument("--order-seed", help="hexadecimal seed of the scenarios' order (local reproduction); default: drawn at random, separately")
    parser.add_argument("--build-network", help="docker build's network ('host' without Docker's bridge)")
    parser.add_argument("--memory", default="4g")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)
    if args.repetitions < 1 or args.warmup < 0:
        parser.error("--repetitions: at least 1; --warmup: at least 0")
    if args.history and not args.history_only:
        parser.error("--history requires --history-only")
    if any(c is not None and not COMMIT.fullmatch(c) for c in (args.base, args.head)):
        parser.error("--base, --head: full commits (40 hexadecimal digits)")
    # Defence in depth: the plugin, loaded later in this process, does not find GH_TOKEN in os.environ (the value
    # stays in /proc/<pid>/environ: a caller gives the token to the --history-only call alone).
    token = os.environ.pop("GH_TOKEN", None)
    FAILURE.update(json=args.json, judge={"version": JUDGE_VERSION, "common": common_tag(), "source": args.judge_source,
                                          "base": args.base, "head": args.head})
    if args.history_only:
        print(" ".join(fetch_history(os.path.abspath(args.tooling), args.history, token)))
        return 0

    beginning = time.time()
    if shutil.which("docker") is None:
        raise JudgeError("docker not found")
    tooling = os.path.abspath(args.tooling)
    if not args.image_only:
        os.environ["GIT_ALLOW_PROTOCOL"] = "none"  # judging: no git transport at all, the declared history is already here
    plugin, plugin_fingerprint = load_plugin(tooling, options_of(args.option))
    if args.image_only:
        print(container.build_image(getattr(plugin, "PACKAGES", ()), args.build_network))
        return 0
    if not (args.source_a and args.source_b):
        parser.error("--source-a and --source-b are required")
    sides = tuple(plugin.SIDES)
    workdir = tempfile.mkdtemp(prefix="bee-judge-", dir=args.workdir)
    os.chmod(workdir, 0o755)
    try:
        image = container.build_image(getattr(plugin, "PACKAGES", ()), args.build_network)
        docker = container.Docker(container.image_id(image), args.memory)  # every container runs the image by its id
        source_a = copy_sources(args.source_a, os.path.join(workdir, "sources-A"), plugin.SOURCES, plugin.REQUIRED_SOURCES)
        source_b = copy_sources(args.source_b, os.path.join(workdir, "sources-B"), plugin.SOURCES, plugin.REQUIRED_SOURCES)
        tools = copy_tooling(tooling, source_a, os.path.join(workdir, "tooling"), plugin)
        stopwatch = container.compile_stopwatch(docker, workdir)
        builds = {v: os.path.join(workdir, f"build-{v}") for v in "AB"}
        surveys = {"A": build(docker, plugin, source_a, tools, builds["A"], "A", workdir),
                   "B": build(docker, plugin, source_b, tools, builds["B"], "B", workdir)}
        log("A and B compiled in the container")

        suspects = analysis.analyse(surveys["A"], surveys["B"], texts_of(source_a), texts_of(source_b),
                                    prefixes=plugin.PREFIXES, allowed_set=getattr(plugin, "ALLOWED", ()))
        architecture = platform.machine().lower()
        if architecture not in ANALYSED_ARCHITECTURES:
            # analysis.py knows only x86-64 instructions: elsewhere, the disassembly is not analyzed.
            suspects.append({"type": "architecture", "detail": f"{architecture}: the objects' instructions not analyzed "
                                                               "(analysis.py covers only x86-64)"})
        by_type = dict(sorted(collections.Counter(s["type"] for s in suspects).items()))
        suspects.sort(key=lambda s: SEVERITY.index(s["type"]) if s["type"] in SEVERITY else len(SEVERITY))
        omitted, suspects = max(0, len(suspects) - SUSPICIOUS_MAX), suspects[:SUSPICIOUS_MAX]
        for s in suspects:
            log(f"suspicious construct: {clean(s['detail'], 300)}")

        # The seed is drawn now, after compilation: nothing that was compiled knows it.
        seed = bytes.fromhex(args.seed) if args.seed else secrets.token_bytes(16)
        rng = random.Random(int.from_bytes(seed, "big"))
        corpus = plugin.corpus(tooling)
        run = container.Execution(docker, stopwatch, {v: variant(builds[v], os.path.join(workdir, f"variant-{v}"))
                                                      for v in "AB"}, workdir)
        compared = 0

        # 1. Verification: the plugin chooses the inputs (corpus, drawn at random, invalid) and the rule.
        inputs = plugin.verification(rng, corpus)
        inputs_module.check_inputs(inputs, sides)
        written, neutral = rename(rng, inputs)  # the plugin keeps its names, read through `names`
        names = {(e.side, e.name): n for e, n in zip(inputs, neutral)}
        folders = prepare(workdir, "verification", written, sides)
        roots = {}
        command = [container.HARNESS, "verify", "/inputs", "/outputs"]
        for v in "AB":
            roots[v], frozen = outputs_of(workdir, f"outputs-verification-{v}", sides), {}
            for side in sides:
                run.launch(v, folders[side], roots[v][side], [("verify", command)], timeout_seconds=3600)
                frozen[side] = freeze(roots[v][side])  # as soon as the container ends: only the frozen will be read
            roots[v] = Outputs(roots[v], names, frozen)
        view_b = Outputs(roots["B"], names)
        compared += counted_integer(plugin.verify(Outputs(roots["A"], names), view_b, inputs))
        require_coverage(view_b, inputs, "verification")
        if compared == 0:
            raise JudgeError("verification: no output compared: judge badly set up")
        fixed = {v: dict(plugin.fixed(Outputs(roots[v], names), corpus)) for v in "AB"}
        for v in "AB":
            roots[v].check_unchanged()
        erase(roots["A"], folders)
        index = outputs_by_input(roots["B"].frozen)
        log(f"verification: {compared} outputs of B correct ({len(inputs)} inputs)")
        # Verification inputs mixed into every measurement (ruche-0037), spread over the repetitions.
        by_side = {s: [e for e in inputs if e.side == s] for s in set(plugin.SCENARIOS.values())}
        if not all(by_side.values()):
            raise JudgeError("a measured side has no verification input to mix into the measurements: invalid plugin")
        rounds = {s: rounds_of(rng, l) for s, l in by_side.items()}
        how_many = {s: -(-len(l) // (args.warmup + args.repetitions)) for s, l in by_side.items()}
        light = {s: [e for e in l if max(len(e.data), e.size) <= args.instructions_prefix]
                 for s, l in by_side.items() if s in {plugin.SCENARIOS[c] for c in plugin.INSTRUCTIONS}}
        without_mixing = sorted(c for c in plugin.INSTRUCTIONS if not light.get(plugin.SCENARIOS[c]))
        interleaved = 0

        # 2. Stopwatch measurements (the child's processor time, read by the kernel), A and B interleaved; the order of the
        #    scenarios is drawn at each repetition, the same for A and B, from a generator of its own whose seed (secrets,
        #    recorded in judge.scenarios.order_seed) does not depend on the inputs' seed.
        order_seed = bytes.fromhex(args.order_seed) if args.order_seed else secrets.token_bytes(16)
        measurements, draw, steps, timed = {"A": [], "B": []}, random.Random(order_seed), [], set()
        for i in range(args.warmup + args.repetitions):
            inputs, mixed = interleave(rng, plugin.repetition(rng, corpus), rounds, how_many, names)
            interleaved += len(mixed)
            folders = prepare(workdir, f"repetition-{i}", inputs, sides)
            plans = {side: [(s, [container.HARNESS, s, "/inputs", "/outputs"]) for s, ss in plugin.SCENARIOS.items() if ss == side]
                     for side in sides}
            outputs, raw, order = {}, {}, draw.sample(list(plugin.SCENARIOS), len(plugin.SCENARIOS))
            variants = ("A", "B") if i % 2 == 0 else ("B", "A")
            for v in variants:
                raw[v], outputs[v] = launch_by_side(run, v, folders, outputs_of(workdir, f"outputs-{i}-{v}", sides), plans,
                                                    order)
            for v in "AB":
                values = dict(fixed[v])  # a scenario's value of a fixed metric, read on its timed outputs, replaces it
                for s, side in plugin.SCENARIOS.items():
                    view = Outputs(outputs[v])
                    vals, n = plugin.scenario(s, Outputs(outputs["A"]), view, inputs, raw[v][s])
                    compared += counted_integer(n)
                    require_coverage(view, [e for e in inputs if e.side == side], f"scenario {s} ({v})")
                    values.update(vals)
                    timed |= set(vals)
                if i >= args.warmup:
                    measurements[v].append(values)
                outputs[v].check_unchanged()
            compared += same_outputs(index, roots["B"], outputs["B"], mixed, plugin.SCENARIOS.items())
            steps.append(step("warmup" if i < args.warmup else "measurement", variants, order, raw))
            erase(outputs["A"], outputs["B"], folders)
            log(f"repetition {i + 1}/{args.warmup + args.repetitions} ({'warmup' if i < args.warmup else 'measured'}) done")

        report = {
            "repetitions": args.repetitions, "warmup": args.warmup, "order": "A, B then B, A, alternately; scenarios: judge.scenarios",
            "machine": stats.description_machine(),
            "method": {
                "retained_value": "median of the repetitions",
                "gain": "median(B)/median(A) - 1 (higher); 1 - median(B)/median(A) (lower); positive = better",
                "beyond_noise": f"sign test on the interleaved pairs, as in ab.py (k = {stats.sign_threshold(args.repetitions)} of {args.repetitions})",
                "stopwatch": ("processor time (user + system) of the process that runs a scenario, read by the "
                              "common judge's chrono launcher with wait4; one execution per scenario and per repetition, "
                              "on inputs perturbed at each repetition"),
            },
            "metrics": {}, "measurements": {"A": {}, "B": {}},
        }
        report["method"].update(getattr(plugin, "METHOD", {}))
        # A fixed metric that no scenario computes from its timed outputs is read on verification alone (ruche-0117): flagged, and
        # never beyond the noise (its value is the same at every repetition, which the sign test would take for a sure gain).
        without_measurement = sorted((set(fixed["A"]) | set(fixed["B"])) - timed)
        for name, direction, unit in plugin.METRICS:
            values_a = [m.get(name) for m in measurements["A"]]
            values_b = [m.get(name) for m in measurements["B"]]
            a, b = stats.summary(values_a), stats.summary(values_b)
            sign = stats.sign_test(values_a, values_b, direction)
            report["metrics"][name] = {
                "direction": direction, "unit": unit, "A": a, "B": b, "gain": stats.relative_gain(a["median"], b["median"], direction),
                "beyond_noise": sign["beyond_noise"] and name not in without_measurement,
                "degradation_beyond_noise": sign["degradation_beyond_noise"], "verification_only": name in without_measurement,
                "sign_test": sign,
                "minmax_disjoint": (a["median"] is not None and b["median"] is not None and (a["max"] < b["min"] or b["max"] < a["min"])),
            }
            report["measurements"]["A"][name] = a["median"]
            report["measurements"]["B"][name] = b["median"]

        # 3. Instruction count: Valgrind in the container, the whole process, its summary read by chrono.
        if not args.no_instructions and plugin.INSTRUCTIONS:
            inputs, mixed = interleave(rng, plugin.instructions(rng, corpus, args.instructions_prefix), {s: rounds_of(rng, l) for s, l
                                       in light.items()}, {s: min(how_many[s], len(l)) for s, l in light.items()}, names)
            interleaved += len(mixed)
            folders = prepare(workdir, "instructions", inputs, sides)
            plans = {side: [(s, VALGRIND + [container.HARNESS, s, "/inputs", "/outputs"])
                            for s in plugin.INSTRUCTIONS if plugin.SCENARIOS[s] == side] for side in sides}
            counts, outputs, order = {}, {}, draw.sample(list(plugin.INSTRUCTIONS), len(plugin.INSTRUCTIONS))
            for v in "AB":
                counts[v], outputs[v] = launch_by_side(run, v, folders, outputs_of(workdir, f"outputs-instructions-{v}", sides),
                                                       plans, order, valgrind=True, timeout_seconds=3600)
            for s in plugin.INSTRUCTIONS:
                view = Outputs(outputs["B"])
                _, n = plugin.scenario(s, Outputs(outputs["A"]), view, inputs, counts["B"][s])
                compared += counted_integer(n)
                require_coverage(view, [e for e in inputs if e.side == plugin.SCENARIOS[s]], f"instructions {s}")
            for v in "AB":
                outputs[v].check_unchanged()
            compared += same_outputs(index, roots["B"], outputs["B"], mixed, [(s, plugin.SCENARIOS[s]) for s in plugin.INSTRUCTIONS])
            steps.append(step("instructions", "AB", order, counts))
            erase(outputs["A"], outputs["B"], folders)
            report["instructions"] = {}
            for s in plugin.INSTRUCTIONS:
                a, b = counts["A"][s]["instructions"], counts["B"][s]["instructions"]
                gain = stats.relative_gain(a, b, "lower")
                report["instructions"]["instructions_" + s] = {
                    "direction": "lower", "unit": "instructions", "A": a, "B": b, "gain": gain,
                    "beyond_noise": gain is not None and abs(gain) > args.instructions_threshold}
            report["method"]["instructions"] = (
                f"valgrind --tool=cachegrind in the container, the harness's whole process (nothing escapes the count), "
                f"the plugin's inputs (a prefix of {args.instructions_prefix} bytes), perturbed; summary read by "
                f"chrono on Valgrind's last line; beyond the noise if the difference exceeds {100 * args.instructions_threshold:.2f}%")

        verification = {"outputs_compared": compared, "inputs_mixed": interleaved, "mixed_per_repetition": how_many,
                        "instructions_without_mixing": without_mixing, "fixed_without_measurement": without_measurement}
        verification.update(getattr(plugin, "VERIFICATION", {}))
        report["judge"] = {
            "version": JUDGE_VERSION,
            "common": common_tag(),
            "source": args.judge_source,
            "base": args.base, "head": args.head,
            "project": plugin.NAME,
            "plugin": plugin_fingerprint,
            "code": 0, "outcome": ISSUES[0],
            "seed": seed.hex(),
            # A seed given on the command line is a local reproduction, never a judgement: report.py --verify refuses it.
            "seed_origin": {"seed": "given" if args.seed else "drawn", "order_seed": "given" if args.order_seed else "drawn"},
            "image": image,
            "image_id": docker.image,
            "suspicious_constructs_omitted": omitted, "suspicious_constructs_by_type": by_type,
            "isolation": " ".join(container.ISOLATION + container.Docker.BOUNDS) + " --pids-limit 2 (execution), 64 (compilation); "
                         f"each execution on its own tmpfs ({container.TMPFS}), filled anew",
            "verification": verification,
            "analysis": {"architecture": platform.machine().lower(), "prefixes": list(plugin.PREFIXES),
                         "allowed": list(getattr(plugin, "ALLOWED", ()))},
            "suspicious_constructs": suspects,
            "scenarios": {"separation": "one container per scenario (verification: one per side); its outputs frozen (SHA-256 of each "
                          "file, and the listing) when the container ends, the only ones read: a difference afterwards is a refusal",
                          "order": "drawn at each repetition, the same for A and B", "order_seed": order_seed.hex(),
                          "cpu_time": "user + system, wait4 in chrono (not the cgroup); under Valgrind in « instructions »",
                          "steps": steps},
        }
        report["duration_s"] = round(time.time() - beginning, 1)
    finally:
        if args.keep:
            log(f"work folder kept: {workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)

    stats.show_table(report)
    text = write_report(args.json, report)
    print(text)
    return 0


def write_report(path, report):
    """judge.json, whole or not at all (a temporary file renamed onto it); its text, every lone surrogate replaced."""
    text = re.sub("[\ud800-\udfff]", "\ufffd", json.dumps(report, ensure_ascii=False, indent=2))
    if path:
        folder = os.path.dirname(os.path.abspath(path))
        os.makedirs(folder, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=folder, prefix=".judge-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text + "\n")
            os.replace(temporary, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temporary)
            raise
    return text


def stop_it(code, message, fault=False):
    """The judge stops (1 refusal, 2 error): the message on standard error and, with --json, in judge.json (ruche-0136)."""
    print(message, file=sys.stderr)
    try:
        write_report(FAILURE.get("json"), {"judge": dict(FAILURE.get("judge", {}), code=code, outcome=ISSUES[code], machine_failure=fault,
                                                         reason=message)})
    except (OSError, ValueError):  # no report, never a stale or partial one: report.py --code keeps the exit code
        with contextlib.suppress(OSError, TypeError):
            os.unlink(FAILURE.get("json"))
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refusal as e:
        sys.exit(stop_it(1, f"judge: REFUSAL: {clean(str(e), 3000)}"))
    except JudgeError as e:
        sys.exit(stop_it(2, f"judge: error: {clean(str(e), 3000)}", isinstance(e, MachineFailure)))
    except Exception:  # noqa: BLE001 — a defect of the judge or of the plugin: never a success, never a raw traceback
        sys.exit(stop_it(2, "judge: internal error (judge or plugin): " + clean(traceback.format_exc(), 3000)))
