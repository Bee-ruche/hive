# Common judge: one isolated judge for every project (specification)

Status: version 5, tag `judge-v5` (the judges entirely in English, one plugin contract), for the founder to tag. Version 4,
tag `judge-v4` (ruche-0148), read a plugin in English or in French; versions 1 to 3 (from 28 October 2026) carry the
registry's earlier tag names, `juge-v1` to `juge-v3`.

*In this text, « the registry » is `Bee-ruche/registre`, where the common judge was written. This repository holds its
`tools/judge/`, extracted at commit 2baa4d2 and put entirely in English in version 5. The hive calls the judge through its
judging step alone ([protocol.md](protocol.md)). A label `ruche-NNNN` names the registry's task under which a change was
made.*

## The problem

minizBee's isolated judge (the fork's first judge) mixed two things:
- **what protects** and depends on no project: the image and the isolation in a container, the
  `chrono` launcher (times read by the kernel, Valgrind's summary), the safe reading of outputs, the analysis of
  compiled objects, the seed drawn after the build, the A/B statistics, the report;
- **what judges miniz**: the harness that calls the library, the inputs (corpus, randomly drawn
  data, zlib streams), the verification rule (outputs identical to the base, round trip through
  the host's zlib), the scenarios and their metrics.

Copying the whole into each project would make as many copies to fix as there are projects. The adversarial
review of 27 October showed it: a flaw in the judge is fixed once, or it stays open elsewhere.

## The split

| In this repository (`tools/judge/`) | In each project (`bee/judge/`, at its tip) |
| --- | --- |
| `Dockerfile.base` (pinned image, common packages) and the isolation (`isolate.sh`) | The project's own packages (one `RUN` line added to the common image) |
| `chrono.c`: launcher, measurements through `wait4`, token, reading of Valgrind's summary | `execution.c`: the harness, which reads `/inputs/list` and writes in `/outputs` |
| `reading.py`: safe reading of outputs (no link, no special file, bounded size); `inputs.py`: the inputs and their helpers | `project.py`: the plugin described below; `build.sh`: its build script |
| `analysis.py`: suspicious constructs (list of allowed functions supplied by the plugin) | The corpus and its generator (`bee/corpus/`, for one) |
| `judge.py`: the orchestration (build A and B, analyze, draw the seed, verify, measure, instructions, report in `ab.py`'s format + a `judge` section); `report.py`: the report's figures and their check | The project's own tests of its plugin |
| The common judge's tests and meta-tests on a toy project (`tools/judge/toy/`, `test_judge.py`; workflow `tests.yml`) | |

## A project's plugin (`bee/judge/project.py`)

A `Project` class with no state of its own (it receives the options `--option KEY=VALUE` when it is created), read by
the common judge **from the PR's base** (never from the PR), at `bee/judge/project.py` and nowhere else: every component
of that path is a real folder or file, never a link. A full, commented model, the meta-tests' toy project:
`tools/judge/toy/bee/judge/project.py`.

| Element | Role |
| --- | --- |
| `NAME`, `PACKAGES` | the project's name; packages added to the common image (one `RUN` line, names checked) |
| `SOURCES`, `REQUIRED_SOURCES` | glob patterns of the project's files copied into the container and compiled (`miniz.c`, `src/*.c`…); any symbolic link is refused; the text analysis reads these same files, whole |
| `TOOLING`, `BASE_HEADERS`, `BUILD` | folders of the base mounted on `/tooling`; headers of the base copied into `/tooling/base/` (the harness is compiled with them); build script, run as `sh /tooling/<BUILD> /sources /tooling /output`, which must produce `/output/execution` and leave **each object of the project in `/output/obj/`**, one `obj/<name>.o` per translation unit of `SOURCES` (`.c`, `.S`, `.cc`…), two units with the same name being refused (otherwise the judge stops) |
| `PREFIXES`, `ALLOWED` | the project's namespace (at least one prefix, each a word ending in `_`: `mz_`, `yaml_`) and external functions allowed on top of the common list (64 at most). The functions that serve to fool the measurement (clock, processes, environment, signals, system calls: `analysis.NEVER_ALLOWED`) are never allowed and are flagged by their exact name, before any exemption |
| `SIDES` | input sides (`f`, `z`…, one lower-case letter each): never two sides mounted together; in verification, one container per side; in the measurements, one per scenario (below) |
| `SCENARIOS`, `INSTRUCTIONS`, `METRICS`, `METHOD` | scenarios measured on the timer and their side; those whose instructions are counted; metrics (name, direction `higher` or `lower`, unit); method texts added to the report |
| `VERIFICATION` (optional) | keys the plugin adds to `judge.verification` in the report |
| `corpus(tooling)` | the base's corpus, `[(name, bytes)]` (helper: `inputs.load_corpus`) |
| `verification(rng, corpus)` | verification inputs (`inputs.Input`): corpus, randomly drawn data, derived data (streams produced by the host), invalid inputs |
| `verify(a, b, inputs)` | correctness rule on the outputs of the `verify` mode; raises `Refusal` at the first discrepancy, `JudgeError` if the base itself is wrong; returns the number of outputs compared |
| `fixed(outputs, corpus)` | metrics that do not depend on time (compression ratio…), read on the verification outputs |
| `repetition(rng, corpus)`, `instructions(rng, corpus, prefix)` | inputs of the measurements, perturbed at each call (the common judge mixes verification inputs into them, then renames everything) |
| `scenario(s, a, b, inputs, measurement)` | checks **each** output of a measured scenario by `verify`'s rule, mixed-in verification inputs included (invalid ones too), and derives the metrics from them (from chrono's measurement); returns `(values, outputs compared)` |

**What a plugin imports.** The judge puts its own folder first on the import path; a plugin imports two of its modules
by name and uses these names alone:
- `inputs`: `Input`, a named tuple `(side, name, data, size, expected)` (`expected` optional, `None` by default: what the
  host expects of the input, known to the plugin alone); `perturb(rng, files, prefix=None)`, a copy of `[(name, bytes)]`
  with a few bytes changed at random; `load_corpus(tooling, generator, folder, name_prefix="k")`, which runs the base's
  generator (python, on the host) and reads the files it leaves, under neutral names (`k000`…).
- `reading`: `JudgeError` (code 2: the environment, the base or the plugin is wrong), `Refusal` (code 1: B is refused),
  `clean(text)` (bytes from the container made safe to put in a message), and the `Outputs` view it is given:
  `require(side, path)` (the bytes, or a refusal if missing), `read(side, path)` (the bytes or `None`), `status(side, path)`
  (a harness's status file « CODE INTEGER »: two integers).

A scenario's `measurement` is chrono's line for it: `user_s` and `system_s` (processor time, read by `wait4`), `wall_s`,
`maxrss_kb` (maximum memory), `instructions` (under Valgrind, else `None`), `code` and `signal`.

**The harness.** It is called with no argument; its descriptor 0 carries 256 bytes: the line `<mode> /inputs /outputs`
(mode `verify` or a scenario's name), padded with spaces and ended by a newline; `/inputs/list` gives one line
`<side> <name> <integer>` per input, whose bytes are in `/inputs/<side>/<name>`. In a scenario, it treats any
input of its side as in verification.

**What the harness guarantees the judged code (ruche-0037).** The same arguments, environment, descriptors, working directory
and mounts in every mode (verification, timer, instruction count), one container per scenario; the mode reaches the harness on
its descriptor 0, in a record of fixed length. The harness reads that record to its end, copies it, then erases it, its
arguments and its environment before any call to the judged code, and does the same work and writes the same outputs in every
mode. `/variant` holds the harness alone; inputs, harness, `chrono` and the output folder carry fixed times. Inputs are
shuffled and renamed (`e0000`…) in every mode; the plugin keeps its own names, translated by `Outputs`. These conditions do not
hide everything about the run: the wall clock stays readable, and the instruction count runs under Valgrind, which the judged
code can detect. Mixing is the backstop. Every verification input is verified; the verification inputs of each measured side are
also mixed into the measured ones and spread over the repetitions (⌈n/r⌉ per repetition, warm-up included, taken in turn in an
order drawn from the judge's seed; as many in the instruction count, within its prefix), the same for A and B. A wrong output
fails the judgement whatever the mode, and B's output of a mixed-in input must be, byte for byte, its own output in
verification. A measured side without verification inputs is an error. A scenario may return a fixed metric computed on its
timed outputs (the toy's ratio); it replaces the value `fixed()` reads on verification. `judge.json`:
`judge.verification.inputs_mixed` (total), `mixed_per_repetition` (per side), `instructions_without_mixing` (instruction-count
scenarios that got none). Since ruche-0117, the byte-for-byte check wants a comparable output in each scenario of the side, and
a fixed metric that no scenario returns, read on verification alone, is named in `fixed_without_measurement`, marked
`verification_only` in `metrics` and never `beyond_noise`: its value is the same at every repetition.

**Each execution on its own tmpfs (ruche-0117).** Nothing the judge's setup shows a container depends on the run's progress
(its position, the variant pass, the repetition, the mode). Just before each container, the judge mounts a fresh tmpfs
(`container.TMPFS`: 4 GiB, 262,144 files; as root or through `sudo -n`, an error otherwise) and creates there anew, in a fixed
order with fixed access and modification times, all the container sees of it: `chrono`, the harness, the inputs,
`/etc/hostname`, `/etc/hosts`, `/etc/resolv.conf` (which Docker would write on the host's disk) and the outputs folder; once
the container ends, the outputs are copied out and the tmpfs unmounted. Docker (up to 29.0) mounts folders of equal
depth in an order drawn for each container: since ruche-0136, each folder the judge mounts, in every container (executions and
builds), is given at a depth that no other mount of the container shares, from `container.DEPTH` (8) on, deeper than any
of Docker's own (4 at most: `/sys/fs/cgroup/cpu` under cgroup v1), through the image's link to its root
(`/.root/…/.root/variant` is `/variant`), so all are mounted in one order, whatever order Docker draws
(test_one_mount_order_whatever_docker_draws; with Docker, test_depths). `/etc`'s three files stay at their depth. Identical
scenarios thus find the same inodes, devices, links, sizes, directory order, free space and mount lines, change and birth times
as old (`f_fsid` is drawn by the kernel at each mount), and no container's outputs share space with another's while it runs
(test_same_mounts). What still follows the progress, as the clock does: the container's root, Docker's overlay on the host's
disk (its inode, free space and, with the containerd image store, its layers' numbers in `/proc/self/mountinfo`), and
kernel-wide counters (unique mount ids, the inode numbers of each container's cgroup and message queues, the host's process
count in `/proc`'s links).

**Per-scenario isolation (ruche-0036).** In the measurements and the instruction count, each scenario runs in its own
container (above), with a fresh `/tmp` and a fresh output folder mounted on `/outputs`: of all the outputs, it sees only its
own. Verification still runs one container per side, not per scenario.
- **Frozen outputs**: as soon as each container ends (verification included), its outputs are copied out of its tmpfs
  (`reading.copy_out`: no link followed, size bounded, a link or special file left as a link) and the judge records the
  listing of that folder and the SHA-256 of each file (`reading.freeze`). The plugin (through `Outputs`) and the byte-for-byte
  comparison of mixed-in inputs read only what was frozen: a file changed, added or removed afterwards is a refusal, when it
  is read and at the check that ends each step; so is anything the judge cannot read while freezing (root or not).
- **Drawn order**: the order of the scenarios is drawn anew at each repetition (warm-up included) and for the instruction
  count, the same for A and B.
- **`judge.json`**: `judge.scenarios.order_seed` is the seed of that draw (from `secrets`, separate from the inputs' seed and
  generator; `--order-seed` reruns it); `judge.scenarios.steps` gives, per step (`warmup`, `measurement`,
  `instructions`), the order of the variants and of the scenarios, and **each scenario's CPU time** for A and B (user +
  system, read by `chrono` with `wait4`; under Valgrind for `instructions`).
- Meta-test, on a copy of the toy with two scenarios per side: a candidate each of whose scenarios tries to read and to
  modify the others' outputs, before and after its own work, gets the honest toy's verdict and comparisons.

Safety rules, checked by the common judge (adversarial review of 28 October):
- the analysis listings (`nm`, `objdump`) are produced by the common judge itself, in a container, on
  all the objects in `obj/`: a build script can neither omit them nor empty them;
- the plugin sees the outputs only through `reading.Outputs`, which records what it has read: at each
  step, each input must have had at least one output of B read, otherwise the judge stops (code 2);
- the plugin runs nothing that the container produced and never puts bytes from the
  container into a message without `reading.clean`; any unexpected exception is an error (code 2);
- a harness never sizes a buffer from the judged code alone (a known bound of the format, at the least);
- the instruction analysis covers only x86-64: on another architecture, the judge flags it as a
  suspicious construct (a guardian reviews);
- what the object analysis covers: suspicious instructions (system calls, counter reads, processor identification,
  Valgrind client requests…) are counted in the disassembly and, independently, in the executable bytes of every
  object and of the linked program, read from the files at every offset, each hit compared with A's by its object
  and surrounding bytes; undecodable bytes and writable and executable memory count too. A failure of `nm` or of
  the disassembler stops the judge (refusal or error), and unreadable bytes make it incomplete: never complete;
- the judged files (`SOURCES`) are scanned whole, each file of B against A's, line splices joined, without
  git: only a net, the objects show the code produced;
- disk and reads are bounded (ruche-0038): containers run with `--ulimit fsize` at `reading.OUTPUT_FILE_MAX` (256 MiB) and no
  log on the host's disk, which keeps the first MiB of their standard output and the last of their error; no output is read
  beyond that size, and writing without end fails the judgement. `--workdir` names the judge's work folder (a size-bounded
  tmpfs, for one): filling it fails the judgement too.

**The suspicious constructs.** `judge.json` lists 100 suspicious constructs at most (the rest: `suspicious_constructs_omitted`),
the most serious first (`judge.SEVERITY`), each kind counted (`suspicious_constructs_by_type`), each detail cut to 300
characters as `analysis.analyse` builds the list (ruche-0117). The kinds, fixed words, the most serious first:
`incomplete_analysis` (bytes the analysis could not read), `architecture` (instructions not analyzed on this machine),
`forbidden_call` and `forbidden_symbol` (a function never allowed, called or defined), `instruction` (a suspicious mnemonic in
the disassembly), `bytes` (bytes that spell such an instruction, or writable and executable memory), `section` (a section run
before the program, or unusual), `symbol` (an indirect function or unique symbol), `defined_symbol` (a global symbol outside
the project's namespace), `external_call` (an external function outside the allowed list), `source` (a word of the judged
files with no business in the project). The hive takes one figure for each kind counted, `suspects_<kind>`
([protocol.md](protocol.md)). Before judge-v5 the kinds were French words (`analyse_incomplete`, `appel_interdit`,
`symbole_interdit`, `octets`, `symbole`, `symbole_defini`, `appel_externe`; `architecture`, `instruction`, `section` and
`source` are unchanged).

**Machine failures and seeds (ruche-0136).** A failure of the machine that judges is an error of the environment, never a
refusal of the judged code: after each container, the judge reads Docker's own record of it (`docker inspect`, then the container
is removed), never its code or error stream, which the judged code writes; a container that was not created (daemon out of reach,
image or runtime missing), that its runtime failed to start, or whose recorded state is not « exited » with its process's code
stops the judge with code 2 (`reading.MachineFailure`, whose reason never quotes the container's error stream); at its
deadline, a container that never started is one too, one that ran a refusal. With `--json`, `judge.json` is written whole or not
at all (renamed into place) whatever the outcome: `judge.code` and `judge.outcome` (`correct` 0, `refusal` 1,
`environment_error` 2), and on a stop `judge.reason` and `judge.machine_failure`, a refusal staying a refusal whatever its
message holds; `report.py --code` publishes 0 only with its report, whole and checked, and a code only if the report does not
say another (code 2 otherwise; a refusal needs no report). The hive takes its figures from what `report.py --code` publishes.
`judge.seed_origin` says for each seed (`seed`, `order_seed`) whether the judge drew it (`drawn`) or it was given on
the command line (`given`, `--seed`, `--order-seed`: a local reproduction). `report.py --verify` refuses any report
whose seeds were not both drawn, or that does not say: a reproduction is never taken for a judgement (its seed is no longer drawn
after the build). Refusing rather than marking keeps one rule on the verdict side: only a judgement passes.

**Declared history.** A plugin may read files of the project frozen at an old commit by their git id (a corpus of the
project as it was): judging refuses any git transport (`GIT_ALLOW_PROTOCOL`), so those commits are in the base's repository
before the judge runs. The hive puts them there itself, from the commits the project's file lists (`judge.history`,
[protocol.md](protocol.md)). `judge.py --history-only --history <commits>` does the same for a caller that has a clone of the
base: 16 full commits at most, each an ancestor of the base (compare API of the calling repository: `identical` or `behind`),
all checked before any fetch, each fetched with its tree and without its history, in 10 minutes at most in all, without
loading the plugin. It passes `GH_TOKEN` to `gh` alone; in every mode the judge takes `GH_TOKEN` out of its environment before
any plugin is loaded. An undeclared object is an error (code 2).

## Versions

- The common judge is versioned by tag: `judge-v4`, `judge-v5`… (the registry's `juge-v1` to `juge-v3` before; each number
  has one name; ruche-0148). `judge.json`, and a project's records after it, carry `judge.version` (an integer: 2 for
  minizBee's judge of miniz-0031, 3 for the common judge, from v1 on), `judge.common` (`judge-v5`, `common_tag()`),
  `judge.source` (`--judge-source`: the judge's code, REPO@COMMIT, when the caller names it), `judge.project` and
  `judge.plugin` (SHA-256 fingerprint of the plugin): a verdict says by which judge it was rendered.
- A project moves up a version when the hive's judge does: its plugin, harness and build script keep the contract of the
  version the hive runs.

## Version 5: the judges in English

Version 5 is version 4's judge entirely in English; what it checks does not change. Version 4's second plugin contract, in
French, is read no more, and `report.py` reads only English reports (`judge.json` is English since version 4). A project's
plugin, harness and build script use the names this text gives: the modules a plugin imports and their names, chrono's
measurement keys, the harness's list of inputs (`list`) and verification mode (`verify`), the folders the harness and the
build script are given (`/inputs`, `/outputs`; `/sources`, `/tooling`, `/output`). The image's label,
`bee-common-judge:<fingerprint>`, the fingerprint of the Dockerfile's whole text, changes with version 5's text. The
suspects' kinds are English words (above): a project that keeps their figures lists `suspects_<kind>` under them.

## Three plugins side by side

The contract was checked on two real projects (miniz, with a trial plugin giving exactly the
results of miniz-0031's judge) and on the toy; for libyaml (libyaml-0005), it is filled in as follows:

| Element | toy | miniz | libyaml (planned) |
| --- | --- | --- | --- |
| `SOURCES` | `rle.c`, `rle.h` | `miniz*.c`, `miniz*.h` | `src/*.c`, `src/*.h`, `include/yaml.h` |
| `BASE_HEADERS` | `rle.h` | `miniz*.h` | `include/yaml.h` (harness compiled with `-I/tooling/base/include`) |
| `SIDES` | `f` raw, `z` streams | `f` raw, `z` zlib streams | `f` documents (no derived data) |
| `SCENARIOS` | compression, decompression | n1, n6, n9, decompression, memory | parsing, loading, emitting, memory |
| correctness | output identical to the base, reference codec in Python | identical to the base, the host's zlib | serialized event stream and emitter output identical to the base; invalid inputs: same error, same positions |
| `PREFIXES` | `rle_` | `mz_`, `tdefl_`, `tinfl_`, `miniz_`, `MZ_` | `yaml_` |
