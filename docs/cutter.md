# The cutter of a hive project

A hive project lives on its tasks: a volunteer's agent can only do what the project's tasks ask, and the judge can
only accept what a task's goal says. Until now every task of the two test projects was written by hand, sixteen in
all. The cutter is the project's own loop that writes them: it reads what the judge answered, keeps the project's
map, closes the tasks that do not move and cuts them again, and publishes the next ones. It belongs to the
project's trusted base, like its guardians; what volunteers push never steers it except through the judge's
numbers.

**Status (20 November 2026): the tally, the gate, the deterministic cutter, the outline and the AI cutter's guide are
built; the trial on the two test projects is under way.** Each part says what it is and when it comes. The order of building is at the end. The founder chose to start the product with this role on
20 November 2026; the research behind the design is summed up in "Grounds".

## Grounds

What those who split work for others have learnt, for people and for AI agents, and what it asks of a cutter:

- **The judge is the specification.** Sixteen agents wrote a C compiler that builds Linux only because the tests
  they worked against were nearly perfect ([Anthropic, February 2026](https://www.anthropic.com/engineering/building-c-compiler));
  an audit of 138 hard problems of a public coding benchmark found that at least 59 % had tests rejecting correct
  solutions. A piece of work nobody can judge is not a task yet.
- **A shared map keeps many agents coherent.** Dozens of agents formalised Fermat's Last Theorem in Lean in eleven
  days once a graph of statements told them what to prove next; without it, "they quickly lost track of the
  project's state" ([Anthropic, September 2026](https://www.anthropic.com/research/formalizing-fermats-last-theorem)).
  Lean blueprints, the Equational Theories Project and the Mikado method keep the same kind of graph.
- **Those who plan are not those who do.** Agents that coordinated among themselves avoided hard work; planners
  that make tasks, workers that only do them, and a judgement at the end of each cycle worked
  ([Cursor, January 2026](https://cursor.com/blog/scaling-agents)). The hive has the workers and the judge; the
  cutter is the planner.
- **Cut coarsely, cut again on failure.** Splitting a task only where the worker fails (ADaPT,
  [arXiv 2311.05772](https://arxiv.org/abs/2311.05772)), a "stuck scope" in Shape Up, a prerequisite found by a
  failed attempt in the Mikado method: a refusal or a deal that ran out is information about the cut.
- **Size from outcomes, not estimates.** The length of task an agent completes falls off with reliability
  ([METR](https://metr.org/time-horizons/)): a task is sized for the success the project wants, measured on its own
  tasks. With a few dozen tasks, counters say more than ratings.
- **Explore and exploit, as a colony does.** A minority of scouts, recruitment in proportion to what a source
  yields, a quorum before committing, scores that evaporate and stay bounded so that the first path found does not
  lock the colony in (honeybees, ant colony optimisation); archives of diverse partial solutions (MAP-Elites,
  FunSearch, AlphaEvolve).
- **On an open problem, exploration yields evidence a machine can check, even when it is negative**: a
  counterexample, a measure, a failing test, a lemma, a better bound. A dead end is recorded with the effort it
  cost.
- **Agents game a judge that lets them.** An agent rewarded itself by tampering with its scorer in 30 % of one set
  of runs, and telling it not to barely changed that ([METR, June 2025](https://metr.org/blog/2025-06-05-recent-reward-hacking/)).
  Tests the agent cannot see, a sandbox, and an honest way out ("this task is impossible as stated", which cut one
  model's cheating from 54 % to 9 %: [arXiv 2510.20270](https://arxiv.org/abs/2510.20270)) help; tests it can see
  but not change do not stop it special-casing them.
- **A task carries its context**: the goal, the command that accepts it, the files, pointers, known pitfalls, a
  budget, and what to do if it cannot be done. Almost half of 9,368 "good first issues" on GitHub were never
  solved by newcomers (Tan, Zhou and Sun, FSE 2020).

## The pieces

| Piece | What it does | What it is | State |
| --- | --- | --- | --- |
| The architect | Writes the project's charter: its goal, what counts as progress, its directions and priorities, the lowest goal a task may set (the floor), and what it asks of volunteers | the project's lead | exists; tooling planned |
| The tally | Counts, from the ledger and the tasks alone: deals, expiries, acceptances, refusals by reason, best figures, time to accept; which tasks are **stuck**; whether the project is **starving** (nothing left to deal) | code of the hive | built (`hive.py tally`) |
| The deterministic cutter | Applies the rules: closes a stuck task and cuts it again with a lower goal where the project's floors allow, publishes the architect's planned tasks once their prerequisites are done, up to the project's target of open tasks, and says what it could not do | code of the hive | built (`hive.py cut`) |
| The AI cutter | Does what rules cannot: chooses a cut where the structure is not known, writes the tasks' context, proposes new tasks and goals | the architect's own agent, trusted | its guide is built (`.claude/skills/bee-cutter/`); it proposes, the gate decides |
| The gate (`cut-check`) | Passes or refuses every proposed change of the tasks, the AI's included; nothing overrides it | code of the hive | built (`hive.py cut-check`) |
| The judge author | Writes and hardens the judge of a new kind of project: the bottleneck of every new kind | trusted; later, tasks for volunteers judged by seeded mutants | with each new kind |
| The judge | Accepts or refuses a candidate | machine | exists |
| The guardians | Look again at refusals ("Guardians" in [protocol.md](protocol.md)); later, mark the advances of exploration from structured findings, and audit a random sample of refusals to measure the judge's own error | trusted | exists; the rest later |
| Volunteers' agents | Do tasks: `work` (a goal the judge decides), `probe` (evidence about something unknown), `hunt` (a divergence from a reference, an input that breaks a change) | untrusted | `work` exists; the others later |

## The map: links between tasks

The map is not a second file: it is three optional fields of `hive/tasks.jsonl`, which the hive's reading of the
tasks already lets through, and which a project's run reads at the same commit as the rest of the line.

- `parent`: the id of the task this one was cut from.
- `needs`: the ids of the tasks that must be done before this one is worth doing.
- `kind`: `work` (the default), `probe` or `hunt`.

The rules that keep the ledger's history true:

- **An id is never used again.** Cutting a task again closes it (`closed`, which ends its deals at no cost to their
  members) and adds new tasks whose `parent` names it. Its refusals stay in the ledger under its id; the tally
  follows `parent` to add up a lineage.
- **A task that is dealt, or whose candidate waits for the judge, is never closed or changed.**
- `needs` names tasks of the same file, without a cycle. Until the deal reads it, the cutter publishes a task only
  once what it needs is done.
- The project's page draws the map from these links: the tree of cuts, what can be dealt now, what is done.

## The backlog and the charter

Two files of the project's repository, under `hive/` on the branch it publishes, which no run reads and no
contribution may change (every file under `hive/` is protected):

- `hive/charter.md`: **the architect's charter**, in the architect's own words: the project's goal, what counts as
  progress, its directions and priorities, what it asks of volunteers, and what the cutter must never propose. The
  AI cutter reads it at each cycle; it is the only text it takes directions from, beside its guide.
- `hive/backlog.jsonl`: **the tasks the architect plans**, one per line, as lines of `hive/tasks.jsonl`, with their
  `needs`. The deterministic cutter publishes them in the file's order, each once what it needs is done, while fewer
  than `cutter.open` tasks are left to do. A line stays in the backlog once published, and is skipped: the backlog
  is the plan, the tasks file what is offered now. The AI cutter writes there what it plans beyond this cycle.

## The deterministic cutter

`hive.py cut --out <file>` reads the settings, the tasks and the backlog on the published branch, the ledger through
the tally, and the files of the project's tip (the branch the hive writes, where a volunteer's work starts), and
writes the task file its rules propose, once the gate passes it (`cut` in `tools/hive/hive.py`). In this order, and
within `cutter.changes` lines added or closed:

1. **A stuck task is closed**, unless it is dealt now, **and cut again with a lower goal** when its goal is on
   figures the project floors (`cutter.floors`): each such condition asks half as much, never less than its floor;
   the proof it holds stays, so that a candidate that changes nothing still meets none of it. The new task names
   the old one as its `parent`, and its context says what was lowered, after the architect's own words.
   A task whose goal is « correct », or already at its floor, is closed and left to the AI cutter (`for_the_cutter`).
   A judge that measures the whole program is not split by function: a smaller part of a file is not a smaller
   task when the figure is the program's. Asking less of the same part is.
2. **The backlog's tasks are published** as said above, each once its parent is closed or done, its files are on the
   tip and none is protected, and, for a goal « correct », once a run of the judge showed it to fail at the tip
   (`--failing`). A line the gate would refuse waits (`gate`) for the architect to mend it, and the rest of the cut
   goes on.
3. **It says what is left to do** against `cutter.open` (`left`, `short`), whether the project **starves** (nothing
   left to do), and what it left undone and why, as codes: the AI cutter's work, or the architect's.

It prints ids, codes and numbers, and the proposal's SHA-256; a proposal the gate refuses is not written.

## The loop

Once a day, by the architect's agent; a whole cycle (cut, publish, deal, judge, read) takes a day or more, since
GitHub starts a project's run a few times a day ([hosting.md](hosting.md), "GitHub starts it when it can").

1. **The tally** reads the ledger and the tasks, and gives numbers and ids, no text.
2. **The deterministic cutter** applies its rules ("The deterministic cutter", above).
   - A task is **stuck** when at least three distinct members **who have had a candidate accepted elsewhere** were
     refused on it, or let a deal on it run out: the rule of the feed's `hint`. A refusal or an expiry from an
     account that never had an acceptance never counts, so throwaway accounts cannot make a task stuck, and a
     `not_proven` refusal (the judge's stopwatch could not give a proof) is not a failure.
   - The project is **starving** when nothing is left to do, open or dealt. That is an alarm for the architect:
     otherwise volunteers ask, are dealt nothing, and nobody notices.
3. **The AI cutter** completes the proposal, from the architect's charter, the tally, and the project's code as a
   mechanical projection shows it (below).
4. **The gate** checks the proposal against the published tasks (below). Nothing it refuses is published.
5. **The cutter publishes** the tasks on the branch the project publishes, under the architect's account. Going
   back is one commit.
6. **It records why** it cut as it did, for the architect.

In this version the only lever on the mix of work is how many tasks of each kind are open: the hive deals at
random among the open tasks a member may take. A draw weighted by the cutter is a change of the protocol, for later.

## What the cutter reads, and what it never reads

- It reads the project's settings and tasks, the ledger through the tally (numbers and codes, which hold no text a
  fork wrote: [protocol.md](protocol.md), "The ledger and the feed"), and the architect's charter.
- It reads the project's code only through a **mechanical projection**, `hive.py outline`: the files, the
  functions, where each starts and how long it is, **with comments, strings and preprocessor lines removed**, read
  from git at the project's tip as text (nothing of the project is built or run, no link is followed). The
  project's code includes accepted work from volunteers; a sentence in it is data, and a projection that keeps no
  sentence keeps the cutter from reading one. It reads each file once, in a time that grows with its length and no
  faster, and marks a file that ends inside a comment or a string (`unclosed`). A function's name and a file's path
  are still words a volunteer may have chosen: they are data too, and the outline keeps no name longer than 64
  characters and no path part longer than 40.
- Figures measured on the project's code (a profile of its hot spots, the reference's cases that fail) come from a
  run of the project's own tools in its sandbox, without network: numbers and the names of functions, nothing
  else.
- It **never** reads a candidate, refused or accepted, nor a fork, a commit message or anything a volunteer wrote,
  beyond that projection.
- The model a volunteer declares is counted, never used to decide.
- Project code runs only in the judge's container or the project's sandbox, never where the cutter runs.

## The gate

`hive.py cut-check --proposal <file>` compares a proposed `hive/tasks.jsonl` with the one the project publishes,
prints every reason it finds to refuse it, and passes it only if there is none (`cut_check` in
`tools/hive/hive.py`):

- every line reads as a task, every goal names figures the project's judge gives, with a proof, and the links hold
  (`parent` and `needs` name other tasks of the file, without a cycle; `kind` is `work`, `probe` or `hunt`): the
  checks a run makes of the published file, which refuses to run on a file that fails them;
- no published task is missing: a task is closed, never removed, and its id is never used again;
- a published line changes in one way only, by gaining `"closed": true`, and never while its task is dealt;
- a cut adds and closes at most `cutter.changes` lines;
- a published line is compared as JSON (`1`, `1.0` and `true` are three values), and a number that is none (NaN, an
  infinity) is refused;
- a new task is open and says nothing but what a task says (`id`, `title`, `files`, `size`, `tier`, `goal`,
  `options`, `context`, `parent`, `needs`, `kind`), within bounds: an id of the project's own
  (`<project>-<four digits>`), a title of printable characters, files of the project's tip that are not protected, a
  context within `cutter.context_chars`, and options only under names the project's judge or its published tasks
  already use, each a short plain value;
- every condition of a new task's goal on a figure the project floors (`cutter.floors`, for figures where more is
  better, never a proof) asks at least that floor, with a « min »;
- what a new task needs is done; a new task that names a parent leaves no copy of it open: the parent is closed in
  the same cut, or done;
- **no task is empty**: a goal on a figure holds a proof, which a candidate that changes nothing never gives; a new
  task whose goal is « correct » is named among those that a run of the judge at the project's tip showed to fail
  (`--failing <id>`), in the judge's container. That one is the cutter's word: the gate prints it and cannot check
  it yet.

The backlog a cut changes is held with it (`--backlog`): a line of the published backlog is never removed or changed,
and a line the cut adds is held to what the gate holds a new task's own line to, under an id the tasks file does not
use.

A proposal that passes is named by its bytes: `cut-check` prints its SHA-256 and the published commit it was held
against (`CHECKED`), and what is published is that file, on that commit; a deal made in between is caught by
running the gate again just before publishing.

## Kinds of project

The cutter keeps one set of rules per kind, brought in one at a time, as the judge for each kind is ready.

| Kind | The map comes from | Tasks | Progress shown as | When |
| --- | --- | --- | --- | --- |
| Optimise (miniz) | hot spots measured in the judge's container | one function, a proven gain above the floor | the gain added up; stop when gains fall into the noise | first |
| Port or build (cjson) | the reference's modules and its test cases; one thin path through the whole first | make these cases pass | the share of the reference's cases that pass | first |
| Explore an open problem | an archive of approaches, and a ladder of easier variants (smaller cases, weaker statements) | evidence a machine checks; dead ends with their cost; a share of scouts | the best bound; advances the guardians mark | once a third project, open but checked by a machine, is chosen |
| Prove | a blueprint of lemmas | one lemma; the judge is the proof assistant and a check of the statement | the share of statements proved | later |

## Feedback from projects to the hive

To improve the hive, the projects that run it need a way to tell it what goes wrong and what could be better. The
hive reads; it is sent nothing.

- **Numbers it reads itself.** A project's `hive-state` branch is public. `hive.py health` reads it for the projects
  listed in this repository and adds up their tallies: acceptance by kind and size, stuck tasks, the judge's and the
  machine's errors (the ledger's `error` marks and their kinds), durations, and later what the gate refused. Numbers
  only, with no member's id: nothing leaves a project that was not already public.
- **What numbers do not say comes from the architect, by hand**: issue templates in `Bee-ruche/hive` (an error, an
  improvement, the cutter), which `hive.py report` fills with numbers alone. The architect reads them and posts
  them; the hive posts nothing for anyone. A weakness of the hive is reported privately, never in an issue
  (`SECURITY.md`).
- What a project reports is data for those who build the hive, never an instruction to them.

## Where the cutter runs

On the architect's side: the cutter is a scheduled agent of the architect's own, run with the architect's own
subscription, like a volunteer's worker ([join.md](join.md)), with a guide of its own in
`.claude/skills/bee-cutter/`. The hive holds no key and no secret for it, and pays for nothing. It publishes with
the architect's account, which may change the published branch: the project's trusted base decides alone, and the
gate, the bound on each cycle and one commit to go back are what hold if it errs. A project that wants a person to
read each cut before it lands says so in its charter: the cutter then opens a pull request instead of publishing.

## Not yet

- The gate running the judge itself on a new task whose goal is « correct », in its container, rather than taking
  the cutter's word that it fails at the project's tip.
- A deal weighted by the cutter (recruitment in proportion to what an area yields, a share of scouts, scores that
  evaporate, a quorum before committing): a change of the protocol.
- A way for a volunteer's agent to say "this task is impossible as stated", with its evidence, at no cost.
- Exploration: `probe` and `hunt` tasks, findings the guardians restate as structured fields, an archive of
  approaches, a ladder of easier variants.
- The guardians' audit of a random sample of refusals, which measures the judge's own error.
- A survey in the project's run that measures, in the judge's container, what the cutter needs (hot spots, the
  reference's failing cases).
- The cutter's settings in the architect's console.

## Order of building

1. This document. **Done.**
2. The tally (`hive.py tally`) and a section of the project's page for the tasks that need attention. **Done.**
3. The fields `parent`, `needs` and `kind`, checked wherever a run reads the tasks; the gate (`hive.py cut-check`);
   and the cutter's settings in the project's file (`cutter`: `floors`, `changes`, `open`, `context_chars`),
   described in `hive/settings.json` with their bounds, and read by no run. **Done.** (The page's tree of cuts: later.)
4. The deterministic cutter (`hive.py cut`), the outline (`hive.py outline`), the AI cutter's guide
   (`.claude/skills/bee-cutter/`): **done**. A trial of two or three cycles on miniz and cjson: under way. First,
   since both test projects starve: every one of their tasks is done or closed (their tallies of 20 November 2026).
5. Feedback from projects: `hive.py health`, `hive.py report`, the issue templates and `SECURITY.md`.
