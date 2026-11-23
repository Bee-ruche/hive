# The judge's third kind: `relay` (two phases, the second with the first's message alone)

Status: written in November 2026 beside a third pilot project (a compressor built from scratch, in its own
repository), and brought here; tried on its own toy project in its tests (`tools/judge/relay_toy/`,
`tools/judge/test_relay.py`) and on that pilot, on the builder's machine. It has judged nothing on a hosted runner
yet.

A project names its judge's kind in its file (`judge.kind`, [protocol.md](protocol.md)). `common`
([common-judge.md](common-judge.md)) compares a candidate's outputs with the tip's and measures both;
`reference` ([reference-judge.md](reference-judge.md)) holds a unit to a reference's answers. This one serves a
project whose worth is **how little must be handed over for the rest to be rebuilt**: a program is run twice, the
second run sees nothing of the first but the message it left, and must give the project's data back, byte for byte.
What is measured is exact: the message's bytes plus the program's. A compressor and its decompressor are one such
program.

Nothing of a language, a format or a project is in the kind: it knows containers, files of bytes, an exact
comparison and two lengths. What knows the project is the project's, at its tip.

## Why the common judge could not judge it

Four things its plugin contract does not hold ([common-judge.md](common-judge.md)):

1. A container's input that is the candidate's own output of another container. Every input there is written by the
   plugin on the host before any run, in one folder shared by the tip and the candidate. Its decompression side works
   for miniz because the host owns a reference codec of a fixed format; here the format is the candidate's.
2. The plugin never sees the candidate's program: what the decoder weighs could only be a number the judged process
   writes.
3. A proof (`sure_<measure>`) is a sign test over at least six timed repetitions; a figure that is exact needs no
   repetition to be sure, and twenty-eight passes over the data where seven are enough.
4. Data that is not in the project's tree: no place for one download held to a fingerprint.

## Who holds what

| Part | Where | Runs |
| --- | --- | --- |
| The kind: the steps below, the isolation (`container.py`), the safe reading (`reading.py`), the launcher that reads the kernel's clock (`chrono.c`), the gate that shuts a program's system calls (`gate.c`), the comparison, the count, the verdict | the hive | on the judge's machine |
| The image | the hive: the manifest names an image the hive holds (`common`, `rust`), never brings one | — |
| The manifest `bee/relay/project.json`: data | the project's tip, a path no candidate can change | never: it is read, every field checked against a floor and a cap |
| `bee/relay/build` and whatever it needs beside the program (the skeleton) | the project's tip, paths no candidate can change | in containers only |
| The data: a file of the tip, or an address with its fingerprint | the project's tip; fetched once, at the image step | never: bytes |
| The program's files | the candidate | read as bytes on the host; built and run in containers only |

Nothing of the tip and nothing of the candidate runs on the judge's machine itself.

## Words

- The **data** is one fixed file of bytes, the project's.
- The **program** is the source files under the manifest's `program` paths: the only paths a candidate may change.
  Built, it is one file, `/out/run`, linked statically.
- A **phase** is one run of that file, alone in a container, behind the gate: `run encode` reads the data on its
  descriptor 3 and writes the message on its descriptor 4; `run decode` reads the message on 3 and writes the data
  on 4.
- The **message** is what the first phase leaves. The host reads it as bytes and writes it again for the second.
- The **total** is the message's length plus the built program's length, both counted by the host.
- The **gate** (`tools/judge/gate.c`, the kind's own program) stands between the hive's launcher and a program: it
  opens the phase's two files, shuts the system's calls, and starts the program.

## The four rules

1. **Each phase has a world of its own, and the decode phase's holds the message and nothing of the encode phase.**
   A phase's container is built on an image the kind makes, which holds nothing (no system, no shell, no library,
   no text: one link, which the hive's mounts go through). Everything it is given is on a **memory file system made
   for that phase alone**, filled with that phase's own copies of the launcher, the gate, the program and its one
   input, unmounted when the phase ends: no folder of the host is ever given to two containers, so no inode, name
   or page of one phase's files is another's (as `container.Execution` does for the common judge). The message
   reaches the decode phase as bytes the host read from the encode phase's output and wrote into the new one.
2. **What is counted is what runs.** The program's weight is the length of `/out/run` as the host read it from the
   build's output; copies of those same bytes, and no other file of the candidate's, are what every phase
   executes. So no placement escapes the count: bytes in a source file, in a second file, in a file's name, in a
   constant computed when the program is built, reach the phases only by being in that file. What does not reach
   it (a comment, a name the compiler drops) weighs nothing and does nothing. A candidate's tree must be the tip's
   everywhere but under the `program` paths; a build is given those paths and the tip's skeleton, never the data.
3. **The figure repeats.** The tip and the candidate each encode the data twice, in containers of their own; each
   one's two messages must be the same bytes. The tip decodes its message once and the candidate twice; each
   decoding must be the data. A candidate whose message changes (bytes the kernel draws, the clock, an address) is
   refused; a tip whose message changes is a failure to judge, on the tip's side (below, "When the tip is at
   fault"). Two runs do not prove that a thousand would agree: they make a figure that
   moves fail loudly, soon (below).
4. **A phase is native code, and is given nothing to call.** Whatever a program's language promises, the kind takes
   it for a process that can make any system call. The gate opens its two files, then installs a system-call filter
   (seccomp) that leaves it: reading and writing the descriptors it holds, its own memory, its own signal handlers,
   SIGABRT to itself (how a C library aborts) and no other signal, and ending. Every other call is answered « not
   permitted » before it is carried out: no name is looked up, no file opened or examined (no time of any file can
   be read), no state of the machine asked for (no `/proc`, no `/sys`, no `mincore`, no clock as a call), no
   process, thread or descriptor made, no network, no way to wait or to stop itself. Before the filter the gate also
   shuts the processor's time-stamp counter for the process and the program it becomes (`prctl PR_SET_TSC`: tried
   on the builder's kernel, the setting survives `execve`), and with it the fine clocks of the time the kernel maps
   into every process, which read that counter; where a machine's clock is not read through it, those fall back to
   the call, which the filter refuses. **A tick clock is left, and the gate cannot take it away**: the coarse clocks
   of that same mapped time (`time()`, `CLOCK_REALTIME_COARSE`, `CLOCK_MONOTONIC_COARSE`) read no counter, only the
   page the kernel updates at each tick (1 to 4 ms), as plain memory. Tried: behind the gate it reads, and moves
   (`test_a_phase_has_a_tick_clock_and_no_finer_one` pins it). Whether some machines have other counters a process
   can read that the setting does not cover is not established. Its processor time and its memory are bounded from
   outside it, and it has room for one process.

What a program still has without a call: the addresses the system draws for its memory (Docker's own filter refuses
the gate the call that would switch that off: tried, `personality(ADDR_NO_RANDOMIZE)` answers « not permitted »),
sixteen bytes the kernel draws for each process at its start, and `getrandom`, which the gate lets through: taking it
away would cost an honest program the hash tables of its language's library and add nothing, since the drawn bytes
and the addresses stay. None of these carries anything from one phase to the next; a message that follows them is
what the judge's two runs catch (rule 3).

## One judgement

For the tip's tree and the candidate's tree, written out by the base:

1. **Read and check.** The manifest; the task's files, plain paths under the program's paths; the manifest's
   bounds, every container of a candidate's judgement at its clock, which must fit `judge.timeout_seconds`; the
   tip, which holds the program's paths and no repository of its own.
2. **What is told without running anything.** The candidate's tree equals the tip's outside the program's paths
   (no deeper than 32 folders); the program's files are plain files with plain names, within the manifest's count
   and weight. The data is read and held to the manifest's fingerprint.
3. **The tip's build.** The hive's launcher and the kind's gate (two small files of C, linked statically); then the
   tip's program, in a container of the manifest's image that holds the tip's skeleton and the tip's program.
4. **The tip's figure.** The tip's program encodes the data twice and decodes once (rules 1 and 3). Its total is
   measured in this judgement, as the candidate's is: a gain is never a difference between two machines. **The tip
   against itself** (`--tip-itself`) stops here, answered 0. Nothing of the candidate's has been built or run yet
   (below, "When the tip is at fault"). A step of the tip's (its build, one of its phases) that fails in a way its
   bytes do not decide is run once more before the tip is said to be at fault.
5. **The candidate's build**, as the tip's, with the candidate's program; then **the candidate encodes, twice**
   (rule 3).
6. **The candidate decodes, twice** (rule 1); each result is read no further than the data's length plus one byte.
7. **The figures.**

The verdict:

- **0, correct**: the candidate's program gives the data back at every run, within its bounds, with one message. The
  figures say whether that is a gain: `gain_total_bytes` (1 − candidate's total / tip's total, rounded down to a
  millionth) and the proof `sure_total_bytes`, 1 when the candidate's exact total is below the tip's. A correct
  program that is no smaller is correct, with a proof of 0: the base then refuses it for its task's goal.
- **1, refused**: what the candidate brings or does: a tree that differs elsewhere or is too large or too deep to
  read, a program that does not build within its bound, a phase that fails, is killed, passes its processor time,
  leaves no file or one past its bound, a message that changes, data that does not come back.
- **2, failure to judge**: what the candidate has no part in: the manifest, the task, the data (missing, not
  fetched, another fingerprint), the tip's own build or phases, the launcher's or the gate's build, the machine.
  And one case nobody can settle: a build or a phase stopped by its clock while it had **not** used its processor
  time (below).

Of the report the base keeps numbers only: `total_bytes`, `tip_total_bytes`, `gain_total_bytes`,
`sure_total_bytes`, `message_bytes`, `program_bytes`, `encode_seconds`, `decode_seconds` (processor time, the
larger of the candidate's two runs), `encode_memory_kb`, `decode_memory_kb`, `builds`, `runs`, `tip_retried`.

## Time, and which side a doubt falls on

A phase's bound is **processor time** (`encode_seconds`, `decode_seconds`), and so is a build's (`build_seconds`,
all its processes together). A busy machine stretches the clock, not the work. A command is stopped at a clock set
half as much again above its bound (and five seconds): `bound + bound / 2 + 5`. A phase is one process, which the
launcher ends at that clock. A build is many (a shell, a compiler, a linker), and the hive's launcher ends its own
child alone: so the gate stands between them (`gate --build`). It holds every process the build leaves behind (it
is their « subreaper »), and at the clock it ends every process of the container but the launcher, reaps them, and
ends itself; the launcher, whose own clock waits fifteen seconds more, reads its end and the processor time of
every process it reaped, the ended ones too (`wait4` counts a child's reaped children). A compiler made to run past
the clock is ended with its shell and counted with it.

| What the launcher measured | Whose doing | Code |
| --- | --- | --- |
| ended by itself, processor time within the bound | — | goes on |
| ended by itself, processor time above the bound | the candidate's | 1 |
| stopped by the clock, processor time above the bound | the candidate's | 1 |
| stopped by the clock, processor time within the bound | the machine did not give it a processor | 2 |
| killed before the clock, another signal, a status that is not 0 | the candidate's | 1 |
| the container ended by the kernel with the launcher in it (status 137, no line), and Docker's own record says it was for memory (`OOMKilled`) | the candidate's | 1 |
| status 137 and no line without that record (Docker restarted, a run cancelled) | the machine's | 2 |

The same measurements of the tip's own build or phases are failures on the tip's side (2: below, "When the tip is
at fault"), and those its bytes do not decide (past its processor time, a signal, the memory record, and two exit
statuses: the gate's own 126, and a build's 137) are run once more first; the two that are no one's doing stay the
machine's.

The fourth line is the only doubt. Behind the gate a phase cannot wait: no call that sleeps, polls with a delay or
waits on anything is let through, and no signal that would stop it (it may send itself SIGABRT alone). A phase
stopped by the clock with its processor time unused was therefore not given a processor by the machine: a failure
to judge, never the candidate's. A build may also wait on its own processes (a compiler waiting for a child): the
same answer. Either way it is never held against a candidate at once: the base asks about the tip itself after a 2,
and counts the failure against the deal only if the tip passes; three such failures end the deal (`judge_failed`).
That a waiting build costs the candidate nothing rests on one condition: today a candidate controls no code that
runs at build time (the build script is the tip's, and the pilot's rule refuses every way for a source to run
something when compiled). If a project's build script ever runs anything of the program's at build time, a build
that waits becomes a candidate's free retry, and that project must bound it otherwise.

The **tip's own program** is given a quarter more processor time than a candidate (`bound + bound / 4`): a program
accepted within the bound stays judgeable on a machine a quarter slower. Past that, twice in a row, the judge fails
(2) and the project's lead sees it: the machine, or the bound, is what must change.

**What a project tells its workers.** Processor time varies between machines and between runs of one machine
(the processor's model, its neighbours): a tenth or two. A project sets its bounds far from what its tip takes, and
tells its workers to stay under a fraction of them (the pilot: six tenths), with the tip's own figure on the hive's
machine as the scale: `encode_seconds` and `decode_seconds` are kept on every accepted verdict's line. A candidate
between that fraction and the bound was told the risk it takes.

**Memory** needs no margin for noise: a program that does the same work takes the same memory. The bound is the
container's, so it covers what the program writes in its output folder as well (a memory file system charged to
it). The gate marks the program as the process the kernel ends first when memory runs out (`oom_score_adj` 1000),
so that the launcher survives to say so (« ended by signal 9 »). On a host that ends a container's whole group
instead, the container ends with status 137 and no measurement; the kind then takes it for the program's memory only
if Docker's own record of the container says the kernel ended it for its memory (`OOMKilled`, which the hive's
`container.Docker.launch` hands back from that record as `oom_killed`), and for the machine's otherwise. Whether that
record is also set when the host as a whole runs short of memory and its kernel ends a process of the container is
**not established**: with the newer control groups the kernel counts, in a group's own events, every process of it
ended for memory, whatever ran short. A host short of memory may then read as the program's (for the tip's own
phases, one of the failures run once more). Which of the two ends a hosted runner gives is to be seen at the first
runs there.

**The data is not in the judge's memory while a decoder runs.** Before each decoding the judge lets the data go
and keeps its length and SHA-256 alone; what comes back is held to those two. The data is read again (and held to
its fingerprint again) for the next encodings, and to say where a wrong decoding differs. (The bytes are let go, not
wiped: a reading of the host's memory from a container, by the processor's own faults, is suspected only, and
would find no copy kept on purpose.) Against such a reading it protects little: the same bytes are in the host's
file cache, since the tip's tree and the candidate's tree, written out by the base, both hold the data.

## The data

The manifest gives it one of two ways:

- **a file of the tip** (`path`, `bytes`, `sha256`): never under the skeleton or the program, so that no build is
  given it;
- **an address** (`url`, `fetched_bytes`, `fetched_sha256`, `member`, `bytes`, `sha256`): http or https, a host and a
  plain path. It is fetched **once, at the image step** (`--image-only`: the judging job's one step with network,
  before any candidate's code is on the machine), held to the size and fingerprint of what is fetched, then, if
  `member` names one, that member of the zip archive is taken and held to the data's own size and fingerprint. The
  data is kept as an image of one file in the machine's Docker (`bee-relay-data:<fingerprint>`); a judgement reads
  it out as bytes and holds it to its fingerprint again. Nothing is fetched while judging.

When the data cannot be had, the judge **fails to judge** (2), at whichever step meets it, and no candidate is
refused for it:

| What happens | Where | What the judge says |
| --- | --- | --- |
| the address does not answer, or not in ten minutes | image step | `the data could not be fetched` |
| what was fetched has another size or fingerprint | image step | `what was fetched: not the N bytes whose SHA-256 the manifest gives` |
| the archive holds no such member, or the member is other data | image step | `the archive fetched does not hold the data`, `the data fetched: not the N bytes…` |
| the image step did not run on this machine | judging | `the project's data is fetched at the image step (--image-only), which has not run on this machine` |
| the kept data, or the tip's own file, is not the manifest's | judging | `the data kept at the image step: not the N bytes…`, `the tip's data: not the N bytes…` |
| a fingerprint of sixty-four zeros | wherever the manifest is read | `sixty-four zeros name no data`: a placeholder, as a workflow's forty zeros |

The image step fails with them (`hive.py image` then stops the judging job: nothing is judged). http is taken as
https is: integrity rests on the fingerprint, and the request carries nothing.

## The manifest

```json
{
  "image": "common",
  "data": {"path": "bee/relay/data", "bytes": 4270, "sha256": "747d0c13…"},
  "skeleton": ["bee/relay/build", "bee/relay/main.c"],
  "program": ["codec"],
  "build_seconds": 60, "build_processes": 64,
  "encode_seconds": 4, "decode_seconds": 4,
  "memory_mb": 256, "output_mb": 16,
  "program_bytes": 65536, "program_files": 8
}
```

`skeleton`: what a build is given beside the program; it holds `bee/relay/build`. `program`: files or folders, never
the skeleton's, never under `bee/` or `hive/`. `program_bytes`, `program_files`: the most a program's source may
weigh and hold (a bound on what a build is given, not the count). `output_mb`: the most a build may write.
`memory_mb`: every container's memory. `build_seconds`: a build's processor time.

## What the project's programs are given

| Program | Container sees | Asked |
| --- | --- | --- |
| `/bin/sh /src/bee/relay/build`, under the launcher and the gate's build mode | `/chrono` (a copy of the launcher and the gate), `/src` (the skeleton and one program's files), `/out`, in the manifest's image | leave `/out/run`, linked statically |
| `/program/run encode`, behind the gate | its own memory file system: `/chrono` (the launcher, the gate), `/program/run`, `/in/data`, `/out`; and three files of `/etc` with fixed texts; in the empty image | read descriptor 3, write descriptor 4, exit 0 |
| `/program/run decode`, behind the gate | the same, with `/in/message` | read descriptor 3, write descriptor 4, exit 0 |

Every container is without network, read-only, unprivileged, bounded in time, memory, processes and bytes written
(`container.Docker.launch`, under Docker's own system-call filter); a phase has room for the launcher and itself,
and no other process or thread; the folder a container writes in is a memory file system of bounded size, gone when
the step ends. A program that needs a library of the system does not start in the empty image (status 127: the
candidate's build is the tip's script, so it is the tip that fails first, as a failure to judge).

Access and modification times of everything a phase is given are fixed; change and birth times are the kernel's
own clock, and no call that reads any of them is let through.

## What the kind does not close

- **Timing, narrowed, not closed.** A decoder has a tick clock (rule 4) and no finer one, so it can read when it
  started to within a tick and the host's own jitter between two containers: an encoder that takes longer for some
  data moves that moment, and that is a few noisy bits a judgement, outside the count, of no use against data of
  millions of bytes. The processor's caches outlive a process for a moment; reading them takes a finer clock than a
  tick. (Where `prctl PR_SET_TSC` fails, the gate stops and the judge fails to judge: it does not go on without it.)
- **The gate is for x86-64.** On another processor it does not build and the judge fails to judge (2).
- **The builds' image.** A build runs in the manifest's image, compiler and all, with the system's calls open: it
  is the tip's own script that runs there, on the candidate's source. What a source can pull in when it is built
  is the project's build to bound (the pilot's rule refuses every way to include a file), and a build is never
  given the data.
- **A program fitted to the data.** The data is fixed and public: a program may be tuned to it, and that is the
  measure's nature (every byte of tuning that reaches the program is counted).
- **Determinism is tested, not enforced.** A program can still be right one time and wrong the next on purpose:
  the addresses of its memory, the bytes the kernel draws, `getrandom` (above) differ at every run, and a program
  may let them decide. Two encodings and two decodings catch a program that varies at every run; a decoder that
  fails one time in three passes its own two decodings four times in nine. Two runs and not more: each is a pass over the
  data, and most programs that are not a function of their input show it at once.
  A program that wavers, once it is the tip, fails one of its own phases sooner or later: see "When the tip is at
  fault", below.

## When the tip is at fault

When the tip's own build or phases fail in a judgement (its build fails or passes its bound, one of its phases
fails, is killed or passes its bound, its two encodings differ, its decoding does not give the data back), the
judgement is a failure to judge (2), and the judge says the failure is on the tip's side: « on the tip's side (not
the candidate's) » in the reason, and `"fault": "tip"` in the report it writes. That is **taken as the tip's**; it
does not prove the tip's code wrong. Some of those failures may be the machine's: a kill for memory (above, the
memory record), processor time stretched past the tip's bound by a slow or crowded machine, a fault of the hardware.

So a step of the tip's that fails in a way its bytes do not decide is **run once more** first:
- ended by a signal, past its processor time, its container ended by the kernel for its memory, a build stopped at
  its clock with its time used;
- exit status 126, the gate's own when it could not set itself up before the program started (a file, a page, its
  filter): the program has not run yet;
- for a build, exit status 137: the build's shell saying that a process of the build, its compiler for instance, was
  ended by SIGKILL. That is how the kernel ends a process for memory, the build's bound or the host's, and the same
  event one process down from a build ended by signal 9. A phase is one process that starts no other: its 137 is its
  program's own status.

If the second run passes, the judgement goes on with it, and the judge's log says the first failed (« the tip's own
step failed once and is run once more », with the first failure's words: a line a person can search for). The
report counts those steps, `tip_retried`, whatever the judgement then answers, and the hive's call says it in the
run's log: « judge: 1 step(s) of the tip's failed once … and were run once more, judging <commit> for <task> ». The
hive does not show the judge's own log, and it does not read it for this: that log can hold what the programs judged
wrote. A project that lists `tip_retried` in `judge.metrics` keeps it on a verdict's line, as `builds` and `runs`.
If it fails again, the failure is on the tip's side. What the tip's bytes decide is not run again: any other exit
status that is not 0, a build that leaves no program, a phase that leaves no file, two encodings that differ (rule 3
keeps its meaning), a decoding that is not the data.

A candidate's steps are never run twice, for the same causes: the tip is treated more gently than a candidate. Its
program was judged correct before, and a false failure on its side stops the run's judging for every candidate. A
second run of a candidate's step would be a second chance for a program that fails at random, and the candidate's
own program can end with status 126 or 137 itself. A false refusal costs that candidate alone, and its member can
submit again.

By then nothing of the candidate's has been built or run in that judgement, so nothing of that candidate's brings
it about within it. Two things are shared beyond the judgement: the machine, with the run's earlier judgements; and
the tip itself, which moves within a run: a program accepted earlier in the run is the tip the later candidates are
judged against.

The hive takes that answer as it takes a judge that fails on the tip itself ([protocol.md](protocol.md), "How a
candidate is judged and integrated"): the run stops judging, the candidate it was on is not charged, the log says the
judge found the fault on the tip's side and for which task, and the run ends as a failure, so that a person sees it.
A project whose tip wavers (a program that fails one of its own runs one time in some, on purpose or not: rule 3
tests determinism, it does not enforce it) therefore stalls, loudly, from the first judgement that meets such a
failure: its candidates wait, and nobody pays for them. **The architect recovers** by one revert of the commit that
brought the program in, on the hive's branch; the next run judges against the tip before it. A failure that was the
machine's costs the run, and the next run on a sound machine judges again.

## What a run costs

A candidate's judgement: the launcher's build, two builds and **seven passes over the data** (the tip's two
encodings and one decoding, the candidate's two encodings and two decodings), each in its own container, plus the
host's reading and comparing (the data a few times). A step of the tip's run once more ("When the tip is at
fault") adds a build or a pass; the report's `builds` and `runs` count every one started, and `tip_retried` how
many were such a second run (so `builds + runs` is `9 + tip_retried` for a candidate, `4 + tip_retried` for the tip
against itself). Its worst case, which the
manifest must fit in `judge.timeout_seconds`, is every container at its clock and every step of the tip's run twice:
`70 + 3 × (build clock + 15 + 10) + 6 × (encode clock + 10) + 4 × (decode clock + 10) + 60` seconds. A phase's clock
is that of the manifest's bound for it, the tip's as a candidate's: the tip's quarter more is processor time, which
fits under that clock, so the tip's phases are counted at it too. The tip against itself: one build and three
passes, two builds and six at most. A project keeps that worst case well under
its judgement's time: a bound edited up to the edge turns every judgement into a 2.

Every judgement measures the tip's whole figure before the candidate's build, so a candidate that does not even
build costs the tip's figure all the same. A tip at fault costs one measured tip in every run until it is mended.

## For the base

A task of such a project lists files under the program's paths. The project's file says `"kind": "relay"` under
`judge`, lists in `judge.metrics` the figures it keeps, and takes `sure_total_bytes` as its proof
(`judge.confirm`); a task's goal is then `{"kind": "metric", "name": "gain_total_bytes", "min": …, "and":
[{"name": "sure_total_bytes", "min": 1}]}`. The kind answers nothing about the tip for the cutter (`TIP_KINDS`): its
tasks ask a gain, never « correct ».
