# The cutter of a hive project

A hive project lives on its tasks: a volunteer's agent can only do what the project's tasks ask, and the judge can
only accept what a task's goal says. Until now every task of the two test projects was written by hand, sixteen in
all. The cutter is the project's own loop that writes them: it reads what the judge answered, keeps the project's
map, closes the tasks that do not move and cuts them again, and publishes the next ones. It belongs to the
project's trusted base, like its guardians; what volunteers push never steers it except through the judge's
numbers.

**Status (21 November 2026): the tally, the gate, the deterministic cutter, the outline, the AI cutter's guide, the
projects' feedback to the hive (`health`, `report`) and the judge's proof that a new task « correct » fails at the tip
are built; the trial on the two test projects is under way.** Each part says what it is and when it comes. The order of building is at the end. The founder chose to start the product with this role on
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
| The tally | Counts, from the ledger and the tasks alone: deals, expiries, deals given back, acceptances, refusals by reason, best figures, time to accept; the judge's figures at the tip; which tasks are **stuck**; whether the project is **starving** (nothing left to deal) | code of the hive | built (`hive.py tally`) |
| The deterministic cutter | Applies the rules: closes a stuck task and cuts it again with a lower goal where the project's floors allow, publishes the architect's planned tasks once their prerequisites are done, up to the project's target of open tasks, and says what it could not do | code of the hive | built (`hive.py cut`) |
| The AI cutter | Does what rules cannot: chooses a cut where the structure is not known, writes the tasks' context, proposes new tasks and goals | the architect's own agent, or the agent of an account the project trusts with `cut`, during a duty the hive deals it | its guide is built (`.claude/skills/bee-cutter/`, both ways); it proposes, the gate decides |
| The gate (`cut-check`) | Passes or refuses every proposed change of the tasks, the AI's included; nothing overrides it | code of the hive | built (`hive.py cut-check`) |
| The judge author | Writes and hardens the judge of a new kind of project: the bottleneck of every new kind | trusted; later, tasks for volunteers judged by seeded mutants | with each new kind |
| The judge | Accepts or refuses a candidate | machine | exists |
| The guardians | Look again at refusals ("Guardians" in [protocol.md](protocol.md)); later, mark the advances of exploration from structured findings, and audit a random sample of refusals to measure the judge's own error | trusted | exists; the rest later |
| Volunteers' agents | Do tasks: `work` (a goal the judge decides), `probe` (evidence about something unknown), `hunt` (a divergence from a reference, an input that breaks a change) | untrusted | `work` and `probe` exist; `hunt` later |

## The map: links between tasks

The map is not a second file: it is three optional fields of `hive/tasks.jsonl`, which the hive's reading of the
tasks already lets through, and which a project's run reads at the same commit as the rest of the line.

- `parent`: the id of the task this one was cut from.
- `needs`: the ids of the tasks that must be done before this one is worth doing.
- `kind`: `work` (the default), `probe` ("Probes", below) or `hunt`. A `hunt` is checked and read by nothing yet.

The rules that keep the ledger's history true:

- **An id is never used again.** Cutting a task again closes it (`closed`, which ends its deals at no cost to their
  members) and adds new tasks whose `parent` names it. Its refusals stay in the ledger under its id; the tally
  follows `parent` to add up a lineage.
- **A task that is dealt, or whose candidate waits for the judge, is never closed or changed.**
- `needs` names tasks of the same file, without a cycle. Until the deal reads it, the cutter publishes a task only
  once what it needs is done.
- The project's page draws the map from these links, given the project's task file (`tools/hive/page.py --tasks`):
  the tree of cuts, each task under the one it was cut from, what each task waits for, and how each stands (open,
  dealt, done, closed); a branch whose tasks are all done or closed is one row, and on a large map the rows that lead to
  a task left to do come first. A task that needs a closed one is counted: it will wait for ever. Tasks with no links
  are one flat list, those left to do first. Beside it, the tasks that need attention: the alarms (tasks on which a
  member saw the project ask for something else), the stuck ones, the others refused or run out twice or more
  (refusals by reason), the codes members reported ("Signals"), the runs spent without an answer by kind, and whether
  the project starves. Numbers, codes and task ids, from the tally and what `health` adds up of it.

## Probes

A `work` task bets on a threshold: « do this idea, gain at least X ». When the bet is wrong, little is learnt: a
worker that cannot reach the goal gives the deal back as out of its reach ("Deals given back", below), its member
waits as after a judged refusal, and the task is open again, with a line that says it was given back and no figure:
what the worker measured is its own word, and the ledger holds none. A **probe** (`"kind": "probe"`) asks one named
thing to be tried without knowing whether it helps, and records what the judge measured, even nothing.

- **Its line** is a task's: a title and a context that name the one thing to try, the files, and a goal on a figure
  (`metric`), held to the same rules as any goal, the project's floors included. It may say how many `answers` it
  asks, from distinct members: 1 by default, 5 at most.
- **Its answer** is what the judge measured on a correct candidate. A candidate that reaches the goal with its proof
  is accepted and integrated, as for a `work` task. One the judge finds correct, within the project's requirements,
  and short of the goal (`goal_not_met`) is refused and not integrated, and its line is the probe's answer: the
  judge's figures and `probe` ([protocol.md](protocol.md), "How a candidate is judged and integrated"). The member
  pays nothing for it and earns nothing by it. A member who answered is never dealt the same probe again. One short
  of its proof alone (`not_proven`) reached the goal: no answer, and the probe stays open, as a work task would.
- **It is done** once as many distinct **established** members answered as it asks: members with an acceptance of
  their own on the project before their answer. A probe is dealt only to such members, so every answer counts when
  it is given. On a project's first day nobody is established: a project whose open tasks are probes alone deals
  nothing, so never open a project with probes alone, and cut none before a task is done. An answered probe
  satisfies what `needs` it, whatever was found: so do not put `needs` on a probe when the task that follows
  depends on what was found; write that task once you have read the answer.
- **What the cutter reads**: `hive tally` gives, for each probe, how many answers it asks, each answer (its
  instant, its reason, the judge's figures, and whether its member had an acceptance on the project before it),
  how many distinct members answered and of them how many had, how many answers it still needs from established
  members (`answers_needed`), and `answerers_left`. That number is exactly the accounts with an acceptance on the
  project that its file still takes (neither banned nor left out where it is open by invitation) and that have not
  answered the probe. It does not know the tier a member asks for, nor whether a member will come back. Numbers and
  codes, as everything the tally gives.
- **A probe short of members** (`short_of_members` in the tally): it still needs more answers than there are
  established members who have not answered it, for instance two answers in a project with one member. It would stay
  open for ever and count as left to do. The cutter closes it, and cuts it again asking fewer answers if a direction
  is still worth trying.
- **How to read it.** One short answer from one member is weak evidence: nobody can check that the thing was
  really tried, and a correct candidate that changes nothing the judge counts answers « nothing gained ». A
  direction is closed on several answers from established members, or on the architect's word. A later task states
  a finding in the cutter's own words, with the judge's figures (« the order-4 model was tried: 0.3 % »): never in a
  worker's words, which the ledger does not hold.
- **When to cut one**: an idea whose worth is unknown and cheap to try, and **any goal whose threshold would be a
  guess**. This is about goals on a figure: a goal « correct » has no threshold, and is never a probe. A `work`
  task's threshold comes from a measure of that very change: a figure the charter gives for it, or one the tally
  holds on the goal's own figure for the task's own files (an accepted task's report, a probe's answer). A threshold
  set by likeness alone (« the same change gained 1.4 % in the file beside it »), or a published goal's bounds
  changed with no such measure, is a guess; the half the rules themselves take off a stuck task's goal is not. Cut
  the probe first, its goal at the least the project takes on that figure: its floor (`cutter.floors`), or, without
  one, the least step the charter names. With neither, the idea is not cut: it goes to the architect, in the
  cutter's report. A try that reaches the probe's goal is integrated as a task's would be; one that falls short is
  recorded instead of lost, and its member waits for nothing.
- **When no probe may be cut** (no task of the project is done yet, or the architect has not said that its caller's
  commit holds probes), or when the open tasks would be probes alone, which deal nothing to a new member: the same
  idea is written as a `work` task with its goal at that same least, and the cutter's report says that its
  threshold is a guess. Where the project has no such least, it is not cut either.
- **When not to**: where such a measure gives a threshold, write the `work` task. A probe's short answer costs the
  hive a judgement for no integration, counts in its member's deals of the day, and ends the probe for that member,
  who is never dealt it again; a task can be tried again. The open count counts probes as it counts tasks.
- **The pin.** A hive at an older commit reads a probe as a `work` task: a short answer is an ordinary refusal and
  the task stays open, and the cutter (the hive's latest) then reads those refusals as failures. A project publishes
  probes once the commit its caller names holds this rule.
- `hunt` (a divergence from a reference, an input that breaks a change) is not built: the hive checks the word and
  reads nothing of it.

## Deals given back

A worker that finds its task out of its reach, after an honest try checked as the task's check allows, gives the
deal back (`hive.py release`, [protocol.md](protocol.md), "What a worker pushes"), and so does one whose machine
cannot run the project's sandbox. The deal ends at the next run, the task is free for others, and the ledger's line is
the deal's `expired` line with `released` (`out_of_reach` or `cannot_run`) and the release's commit id. A code alone,
and the member's signals where it gave any ([protocol.md](protocol.md), "What a worker pushes": codes of the hive's
own, such as `too_large` or `goal_beyond`, never text): what the worker measured, and its words, the ledger holds none
of. A release `out_of_reach` counts for « stuck » whichever case it is, the three the worker's guide added (`too_large`,
`duplicate`, `off_task_request`) included; a stuck task whose failures mostly say the task stood in the way is left to
the AI cutter, never halved by rule ("The deterministic cutter", C1). What the tally reads of signals is in "Signals",
below.

- **What the tally gives**, for each task: `released` (how many deals were given back), `released_for` (by code), and
  `released_established` (of them, those by a member with an acceptance on the project before it; the others are
  `released` less these). A deal given back is not counted under `expired`. `health` adds them up, by code too, and
  counts a deal given back as out of reach as an ending in the acceptance share of a kind or size of task; one given
  back for want of a machine, which says nothing of the task, is left out of it.
- **Stuck**: a deal given back as out of reach by a member with an acceptance before it counts as a deal left to run
  out does ("The loop"). One given back because a machine cannot run the sandbox says nothing of the task, and
  counts for nothing there: many of them say the project's sandbox is hard to run, which is for the architect.
- **How to read it.** A release is its member's word: the hive checks nothing of the try, nor whether there was one,
  and a release costs its member a wait and no work. It is cheap evidence, weaker than a refusal, which the judge
  measured. Given back as out of reach by several established members, a task needs cutting again as their signals
  say ("Signals"); without one, its goal is likely beyond what the idea gives, or the task too large for a deal: cut
  it smaller, or turn the idea into a probe ("Probes"), whose answer records the judge's figures. One release from
  one member says little.
- **A probe is never given back as out of reach**: its answer is a correct try, which the worker submits. It may be
  given back because the machine cannot run the sandbox.
- **The pin.** A hive at an older commit reads no release: the worker's tool then gives nothing back, and the deal runs
  out as before.

## Signals

A member may add up to four signals to its candidate or to its release: codes of the hive's own, each with at most
one value of a fixed kind ([protocol.md](protocol.md), "What a worker pushes"). They change nothing the hive decides
(no verdict, wait, deal, day's count, « stuck » or hint reads one), and the feed and the worker's tool show no worker
another's (the ledger, which holds them, is public). They are evidence for the cutter, weaker than the judge's figures
and the ledger's outcomes: a signal is its member's word, said at no cost beyond the deal it rides on.

- **What the tally gives**, for each task: `signals`, each code with `by` (how many accounts said it), `by_established`
  (of them, those with an acceptance on the project before they said it last) and `values` (the latest values of the
  established, counted); and `signalled_failures`, of the failures the stuck rule counts, the releases out of reach
  whose member said the task, not its goal, stood in the way (`outside_files`, `unclear`, `needs_first`, `duplicate`,
  `too_large`, `off_task_request`). A probe's answers carry the member's `outlook` (`promising`, `dead_end`,
  `inconclusive`) and `effort` where it said them: a dead end recorded with its cost. Project-wide, from established
  members alone: `headroom` (tasks accepted with `more_gain`), `disagreements` (per task, candidates the judge examined
  and refused, `judge_refused`, that their member's own check passed: read per judge kind, since a reference judge
  draws its cases when it judges and a relay worker cannot measure on the judge's data), `alarms` (tasks left to do on
  which a member saw the project ask for something other than the task) and `calibration` (`felt` and `effort` by
  size, and the verdicts by `confidence`); and `signalled`, the tasks C1 closed for the AI cutter from which no task
  has been cut yet. In `signals`, each account counts once per task and code; `disagreements`
  and `calibration` count candidates and releases, so one member can fill them: read them beside the `by_established`
  counts. An account with no acceptance before it said a code counts in `by` and in nothing else, so throwaway
  accounts steer nothing. `health` adds them up.
- **What the deterministic cutter does with them**: C1 alone ("The deterministic cutter", below). It closes only what
  the stuck rule closes; a signal only changes who cuts the task again: the AI cutter, in place of any rule (a lower
  goal, or none). It never cuts a task or sets a goal because of a signal.
- **How to read them.** The judge's figures first, then the ledger's outcomes (refusals, deals run out, releases),
  then the established members' signals; the others' never. Several established members who say `too_large` or
  `splits` of a task tell how to cut it again; `unclear`, that its context needs rewriting; `needs_first`, that a task
  should come before it; `duplicate`, that two tasks overlap (read both lines yourself). `headroom` sends an idea to a
  probe, never to a work task's threshold: that would be a guess; `goal_beyond` too sends the idea to a probe, or to the
  architect, and the stuck rule's halving stays the only rule that lowers a goal. An alarm is for the architect, who
  reads the task and its files; the AI cutter writes no task on those files until then. A later task states what was found in the cutter's own words and counts (« two members gave it back as
  too large »), never a member's.

## The backlog and the charter

Two files of the project's repository, under `hive/` on the branch it publishes, which no contribution may change
(every file under `hive/` is protected). No run reads the charter; the run's judging and write jobs read the backlog
for one thing, the proof at the tip (below):

- `hive/charter.md`: **the architect's charter**, in the architect's own words: the project's goal, what counts as
  progress, its directions and priorities, what it asks of volunteers, and what the cutter must never propose. The
  AI cutter reads it at each cycle; it is the only text it takes directions from, beside its guide.
- `hive/backlog.jsonl`: **the tasks the architect plans**, one per line, as lines of `hive/tasks.jsonl`, with their
  `needs`. The deterministic cutter publishes them in the file's order, each once what it needs is done, while fewer
  tasks are left to do than the cutter aims at ("How many tasks", below). A line stays in the backlog once
  published, and is skipped: the backlog is the plan, the tasks file what is offered now. The AI cutter writes there
  what it plans beyond this cycle.

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
   **C1**: so is a stuck task more than half of whose counted failures are releases whose member said the task, not
   its goal, stood in the way (`signalled_failures`, "Signals"): it is closed and left to the AI cutter as
   `signalled`, with how many established members said each such code, and never cut again with a lower goal by rule,
   since halving a goal mends no task that is unclear, too large, another's, or that needs something first. Such a
   task has no rule left to cut it: the AI cutter takes it first, in that cycle from `for_the_cutter` and later from
   the tally's `signalled` (closed by C1, no task cut from it yet), and the page and `health` show it to the architect.
   A judge that measures the whole program is not split by function: a smaller part of a file is not a smaller
   task when the figure is the program's. Asking less of the same part is.
2. **The backlog's tasks are published** as said above, each once its parent is closed or done, its files are on the
   tip and none is protected, and, for a goal « correct », once a run of the judge showed it to fail at the tip: the
   project's own run asks the judge ("The proof at the tip", below), or, the manual way, the architect runs it and
   gives their word (`--failing <id>`). A line not shown to fail yet waits (`not_shown_failing`); one a run of the
   judge showed the tip passes already waits (`shown_passing`): the task is done, or empty, whatever word is given. A
   line the gate would refuse waits (`gate`) for the architect to mend it, and the rest of the cut goes on.
3. **It says what is left to do** against its aim (`left`, `aim`, `short`, and `pace`: "How many tasks"),
   whether the project **starves** (nothing left to do), and what it left undone and why, as codes: the AI cutter's
   work, or the architect's.

It prints ids, codes and numbers, and the proposal's SHA-256; a proposal the gate refuses is not written.

### How many tasks

The cutter aims at `cutter.open` tasks left to do (open or dealt). A fixed number fits one pace only: one volunteer at
night empties ten tasks in days, ten volunteers in hours, and a project with nothing left to do starves without anyone
noticing. With `cutter.open_more`, the aim follows the project's pace, from `cutter.open` to `cutter.open` plus
`cutter.open_more` (`open_aim` in `tools/hive/hive.py`):

- **the tasks held now** by members with an acceptance on the project before their deal (`held`): each is left to do
  and taken;
- **and half again as many tasks as the acceptances of the last 72 hours** (`accepted`) would use up in
  `trusted.cut_hours`, the project's time between two cut duties: what the members would take before the next cut.

It is read from the ledger alone, in numbers. An account with no acceptance raises it by nothing, as it makes no task
stuck: deals taken by accounts made for the purpose do not make the cutter publish more, and an acceptance is a task
the judge found done. `cutter.open_more` is a hard ceiling, and `cutter.changes` still bounds each cut, so a pace
read wrong cannot flood the project; tasks that share files are dealt one after the other whatever the aim (`areas`).
With few members the pace is noisy, and the floor and the ceiling do most of the work. No run reads `open_more`: a
run deals a cut duty early while fewer tasks are left than `cutter.open`, and otherwise every `trusted.cut_hours`,
the horizon the aim is measured over. `cut` says the aim and what it read (`pace`); `cut-check` says the aim too.

## The loop

Once a day, by the architect's agent; a whole cycle (cut, publish, deal, judge, read) takes a day or more, since
GitHub starts a project's run a few times a day ([hosting.md](hosting.md), "GitHub starts it when it can").

1. **The tally** reads the ledger and the tasks, and gives numbers and ids, no text. Its `tip` is the judge's report
   on the project's latest accepted candidate: the task, the instant of its line, whether a guardian's ruling
   admitted it (`ruling`: a figure may then be beyond a bound the ruling waived), and the figures as numbers under
   the project's own names (for a judge that measures the project, its figures at the tip; for one that measures a
   gain, the gain over the tip before it). They are the figures at the tip as long as nothing but the hive moved the
   project's branch since; `null` before the first acceptance. A task's context quotes the tip from there.
2. **The deterministic cutter** applies its rules ("The deterministic cutter", above). A planned task « correct » is
   published at the first cycle after two quiet runs of the project's hive (no candidate, no task held), six hours
   apart, judged the tip as a candidate for it and saw it fail ("The proof at the tip"): the cutter runs nothing of the
   project, and waits for that answer.
   - A task is **stuck** when at least three distinct members **who have had a candidate accepted elsewhere** on the
     project, before they failed on this task, failed on it: the judge examined their candidate and refused it
     (`judge_refused`, `goal_not_met`, `requirement_not_met`), they let a deal on it run out, or they gave a deal on it
     back as out of their reach (whatever its signal: `too_large`, `duplicate` and `off_task_request` included; a
     stuck task most of whose failures are such signalled releases goes to the AI cutter, C1). A failure from an
     account that never had an acceptance, or from before its first
     one, never counts, so throwaway accounts cannot make a task stuck; a `not_proven` refusal (the judge's stopwatch
     could not give a proof) is not a failure, nor is a deal given back because a machine cannot run the project's
     sandbox. The feed's `hint` is another count: the members with an acceptance, at any time, whose candidate the
     judge examined and refused on the task (a `not_proven` among them); no deal run out, none given back.
     A project with fewer than three members who ever had a candidate accepted never has a stuck
     task: its architect closes one by hand.
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
- The state it reads is the folder given to `--state`, a clone of the project's branch `hive-state`. `hive tally`,
  `hive cut` and `hive cut-check` refuse a folder that is not one, which would read as a state where nothing was
  ever dealt. A folder is a state if it holds at least one of the state's files (`ledger.jsonl`, `feed.json`,
  `ignored.json`, `accounts.json`, `stats.json`, `tip.json`), or if git's own `HEAD` in it names the branch
  `hive-state`. So a project's first day is a state: the branch as its lead made it, with a README and nothing
  else, or a state written by runs that dealt nothing yet and hold no ledger. A state whose feed names another
  project is refused. The test is only that (a file of the state at the folder's root, or the branch `hive-state`
  checked out), so it refuses a folder that does not exist, an empty one, and the project's own clone unless that
  holds a file of one of those names at its root; and it cannot tell another project's state on its first day (no
  feed yet), or any repository on a branch of that name, from this project's. The refusal says how to take the
  state: `git clone --depth 1 --branch hive-state https://github.com/<owner>/<name> <folder>`.
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
- Whether the project's tip fails a planned task « correct » comes from the project's own run, which asks its judge
  and writes the answer to the state: ids, codes and commits ("The proof at the tip").
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
  task whose goal is « correct » is one a run of the judge showed to fail at the project's tip: the judge's answer,
  which the project's run wrote to its state, for that very line, at the tip or at an earlier tip it still holds at
  ("The proof at the tip"); or, the manual way, the architect's word (`--failing <id>`), which the gate prints and
  cannot check. A new task a run of the judge showed the tip passes already is refused, whatever word is given.

The backlog a cut changes is held with it (`--backlog`): a line of the published backlog is never removed or changed,
and a line the cut adds is held to what the gate holds a new task's own line to, under an id the tasks file does not
use.

A proposal that passes is named by its bytes: `cut-check` prints its SHA-256 and the published commit it was held
against (`CHECKED`), then the new tasks « correct » the judge showed to fail (`shown to fail at the tip by the judge:
<ids>`) and those the architect's word names (`shown to fail at the tip, by the cutter's word: <ids>`); what is
published is that file, on that commit; a deal made in between, or an answer of the judge that no longer holds, is
caught by running the gate again just before publishing.

The project's run holds a trusted account's cut to the same gate ([protocol.md](protocol.md), "Trusted accounts and
their duties"): the proposal that account pushes for its cut duty, against the commit the run reads, with the
inputs `cut-check` gathers, and with the judge's answers alone for the tasks « correct »: the run takes no account's
word that a task fails at the tip, the architect's included. Its marker names the digests `CHECKED` prints. The run
records whether it stands and publishes nothing. `hive.py publish-cut`, run with the project's own account, publishes
the cut that stands: it holds it again to its account's fork, its marker, its form and this gate, against the
published branch and the state as they are when it runs, and pushes its two files as one commit of its own on the
published commit ([protocol.md](protocol.md), "Publishing a cut").

## The proof at the tip

A new task whose goal is « correct » is worth publishing only if the project's tip fails it: one the tip passes
already would be accepted for nothing. Its proof is a run of the judge, not the cutter's word, and the cutter runs
nothing of the project: its machine may hold no Docker, and it holds the right to publish.

- **Where the judge runs.** In the project's own hive run, in the judging job (`hive.py judge`), which holds no secret
  and runs the tip's code in containers without network, **and only in a quiet run**: one whose plan holds no
  candidate, and in which no member holds a task. No candidate's code has run in that job before the questions, and
  no candidate can come while they are asked. A busy project, or one where a member always holds a task, has no quiet
  run: its proofs wait, and the architect's word (`--failing`) stays. The job judges **the
  plan's tip itself as a candidate** for planned tasks: the tip's own tree, written out as a candidate's is, judged
  as a candidate's is. For the reference judge that is the tip's own files of the unit, built and run as a
  candidate's would be, on cases drawn then ([reference-judge.md](reference-judge.md)). No question is started that
  could end after the judging's time.
- **What is asked.** Of the lines of the backlog at the plan's commit, those the deterministic cutter would publish
  but for the proof: not published yet, a goal « correct », held by the gate's rules for a new task's own line, what
  they need done, their files on the tip and none protected; and among them, those whose latest answer does not hold
  at the tip under this judge (below), or was given long enough ago: six hours for a `failing` said once (to be said
  a second time or not), a day for an `unknown` or a `passing`. A `failing` said twice is not asked again. **At most
  two in a run**: those never asked first, then the one asked longest ago, in the backlog's order between equals. The
  rest wait for the next run. After an `unknown` nothing more is asked in that run: the judge could not say, and its
  machine may be failing. The job's log names a task it could not answer.
- **What is recorded.** The answer is code 1 (the judge refuses the tip: `failing`), code 0 (it finds it correct:
  `passing`) or code 2 (it failed to judge: `unknown`). It goes to the state, in `tip.json` on the branch `hive-state`:
  for each planned task, its latest answer, the commit it judged, the SHA-256 of the task's line, the instant, how
  many runs in a row gave it, each at a tip where the answer before it still held, the key of the run that gave it,
  and what judged: a SHA-256 of the protocol's judge programs and of the hive's call of them, and one of the
  project's judge settings. Ids, codes, commits, keys, digests and numbers: no text. An answer about a task
  published, or planned no more, is dropped, and the latest 5,000 are kept.
- **Two runs for « failing ».** A refusal can come from the judge's own limits as well as from the unit: a run that
  passes its time on a slow machine is refused. For a candidate that costs only its turn; a task published on a false
  « failing » would be accepted for nothing. So `failing` proves once two runs in a row gave it, the second at least
  six hours after the first, at a tip and under a judge where the first still holds: a task said `failing` once is
  asked again six hours later or more, and published a cycle after that. A machine slow for hours on end can still
  say it twice: the rule bounds what a passing slowness does, no more. `passing`, which only keeps a task back, acts
  at once, and is asked again a day later: a wrong one keeps a task back a day.
- **Who writes it, with which right.** The judging job hands its answers to the write job inside `verdicts.json`, the
  file that job already takes by name; the write job (`hive.py apply`) writes `tip.json` with the token it already
  holds to write `hive-state`. No new file between jobs, no new step, no new right, no secret. The write job works out
  itself which questions were due in the run, from the same plan, its instant, the ledger and the state the judging
  job had, and takes answers for those tasks alone, about the plan's tip and no other commit, as one of the three
  words, whole or not at all; in a run with a candidate it takes none. So a write step run again on the same plan,
  even after a later run wrote, takes nothing: at its plan's instant, the question it answered is not due. What the
  state holds is read back as data: an entry of any other shape is no answer.
- **What a judging job taken over can do to it, and what it cannot.** The judging job of a quiet run
  builds and runs the units the tip holds, in containers without network: the work of volunteers the judge accepted,
  now built and run again outside any member's judgement. A unit that broke out of its container there could make the
  job lie about the tip: say `failing`, `passing` or `unknown` for the questions due in that run (two at most), about
  that run's tip. Two such runs, six hours apart, would have `hive cut` publish a task the tip passes, which a
  candidate then completes for nothing. That is all it can do to the proof: it cannot answer for another task or
  another commit, undo a `failing` said twice, or write text, a path or more than an answer; and a run with a
  candidate takes no answer about the tip at all, so a candidate's code never writes one. The same unit, broken out in
  any judging job, can already lie about verdicts ([protocol.md](protocol.md), "Four jobs, each with one risk"): the
  judge's container is what stands between it and both. A volunteer's fork reaches the state by no other path.
  A member who holds a task, or any candidate in the plan, keeps a run from being quiet: that only delays the proof,
  and the architect's word (`--failing`) remains. But one who could both keep runs from being quiet and answer in the
  quiet ones (a judging job taken over through the tip's own unit files) could choose when its two answers fall: the
  two-runs rule does not stop that.
- **What reads it.** `hive cut` and `hive cut-check` take the proof from the state they are given, for the commit of
  the branch the hive writes (where a volunteer's work starts). **An answer holds at a tip** when it is about the
  task's very line (the same SHA-256) and was given under the same judge, at that commit, or at an ancestor of it
  from which the tip moved by the hive's own integrations of other tasks alone: every commit between the two is one
  the ledger records as an accepted contribution to another task, and no path that differs between the two is one of
  the task's own files (a task cut again names its parent's) or a protected path. A judge of the reference kind judges
  a unit from its own files and from the project's tree beside them (its reference, its skeleton, its judge). The hive
  refuses any contribution that changes a path outside its own task's files, and the reference judge takes a task whose
  files are exactly its unit's, which it never reads when it judges another unit: a contribution to another task
  changes nothing of this one's judgement. Anything else leaves no proof: a maintainer's commit or a merge, whatever it
  touches; the task's own files; a commit of another line of history, or one the clone does not hold; more commits or
  changes than the tool reads; another judge. The run then asks again at the tip as it is. The cutter holds an answer
  to the project's judge settings as its file says them now, and to the judge programs of the newest answer in the
  state: which commit of the hive the project's run uses, it cannot tell, and the newest answer comes from the latest
  run that asked. After the project changes the commit its caller names, the first quiet run sets aside every answer
  given under the judge before; until then they stand. A project whose judge cannot answer reads no answer. The cutter
  works out the digest of the project's judge settings with its own copy of the hive, and the run with the commit the
  project pins: if the two read the file's `judge` differently (a setting one fills in and the other does not), no
  answer is carried until the pin moves. That fails safe, and it is why a proof may be refused after the hive changes
  how it reads a project's file.
- **`--failing`** stays the architect's manual way: the architect runs the project's check at the tip, in the judge's
  container, and gives their word. The gate prints it as before. A run of the judge that showed the tip passes the
  task wins over it.
- **A line the tip passes already** waits (`shown_passing`): the task is done, or empty. It is asked again a day later.
  The architect who finds the judge wrong changes the line (its context, say: another line is another question, asked
  at the next quiet run); one who finds the task done takes the line out of the backlog. A `passing` ages only when a
  quiet run asks again: the cutter's side never ages one, so where no run is quiet a wrong `passing` stays until the
  architect changes the line.
- **The proof is an extra.** Whatever fails in it (a backlog or a `tip.json` it cannot read, the judge, the state) is
  said in the job's log, in the tool's own words and the error's kind, and the run goes on without it: the members'
  candidates are judged, integrated and recorded as before.
- **What it costs.** Two judgements at most per quiet run, and nothing in any other. The project's runs go one at a
  time: a run queued behind one that asks waits for those judgements (the project's `judge.timeout_seconds` each at
  most) before it starts. A member who asks for a task while a quiet run asks waits that long more for its deal.
- **Kinds.** The question is asked only of a judge that can answer it: the reference kind. The common judge compares
  a candidate with the tip, which always passes against itself: a project of that kind (miniz) is asked nothing, its
  goals on figures hold their own proof, and a goal « correct » there is published on the architect's word alone.
- **Projects on an older pin.** A project whose caller names a commit of the hive older than this (the two test
  projects name 64615af) runs as before: its judging job asks nothing, its state holds no `tip.json`, and the
  cutter's `hive cut` (the hive's latest) reads that state as it is: nothing is shown failing by the judge, and the
  architect's word publishes as before. The older runs never read `tip.json`, and save only the files they write: a
  project that goes back to an older pin keeps the file as it is, and its answers stop where they were. To take the
  new version, a project changes the commit its caller names (`.github/workflows/hive.yml`) to one of
  `Bee-ruche/hive`'s main that holds it, reviewed as any change of that line is ([hosting.md](hosting.md), "Which
  version of the hive a project runs"): no setting, no input, no job, no file and no right more.

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
hive reads; it is sent nothing, and it posts nothing for anyone.

- **Numbers it reads itself: `hive.py health`.** It reads the projects listed in this repository
  (`hive/projects.json`), each from `https://github.com/<owner>/<name>` with no account, and of each two public
  branches: the default one, for the project's settings and tasks, read as a run reads them, and `hive-state`, for
  its ledger. One listing and one fetch of the two tips (no history) per project, bounded in time and in bytes, into
  a temporary store of its own that it removes once the project is read. No token reaches git: git sees only a few
  of the machine's variables (where programs are, the language, the time zone, the temporary folder, a bundle of
  certificate authorities, and a proxy whose address names no user or password), the hive's own git settings, and a
  home that holds nothing. Nothing of the machine is sent, and nothing is written elsewhere. It runs on the hive's
  side (Linux), wherever git can reach GitHub.
  It adds up what the tally says of each project (above) and prints JSON. For each project: the two commits it read;
  its tasks by status; what is left to do, what can be dealt now and in how many separate areas; the stuck tasks, by
  id; whether it starves, whether it is paused; how many members are active (each project counts its own: an
  account active in two projects is two in the totals); its deals, acceptances, refusals by reason, deals run out at
  the member's cost or at nobody's, and deals given back, by code; the ledger's `error` marks by kind (`judge`: the
  judge did not answer; `hive`: the hive's machine; `push`: the project's repository declined the commit; `none`: the
  judge started and gave no answer in the run) and the tasks they fell on; acceptance by kind and by size of task;
  the hours from a deal to its acceptance, and their median; the members' signals by code (by accounts, and by the
  established), the tasks with an alarm and those accepted with more gain in sight, the candidates the judge refused
  that their established member's own check passed, and what the established said of their effort, of a task against
  its size and of their confidence beside the verdict ("Signals"). Acceptance is counted by answer: of the candidates
  answered, the deals run out at the member's cost and the deals given back as out of reach, the share accepted. A
  refusal the protocol puts on the hive's or the project's side (`not_answered`, `task_closed`) is left out;
  `judge_failed` and `push_refused`, which it charges to the candidate, count; a candidate a guardian admitted after
  its refusal is one answer more. Then the totals, each the sum of the projects', and the projects it could not read,
  each with a code: among them a project whose name or a task's id is longer than 64 characters, whose file names
  more than 1000 accounts as its members or banned, or whose tasks name more than 2000 entries in their files (what
  the tally costs grows with the square of those, or with the accounts named times the members). It keeps only what
  the tally keeps of a ledger line: no login, no account number, no candidate's commit, no text a volunteer wrote.
  Later, what the gate refused.
- **What numbers do not say comes from the architect, by hand: `hive.py report`.** Three issue templates in this
  repository (`.github/ISSUE_TEMPLATE/`): a judge or machine error, an optimisation of the hive, feedback on the
  cutter. `hive.py report --template error|optimisation|cutter [--project <owner/name>]` prints one of them with its
  numbers part filled from `health` alone, as a table with a column for each project, under its repository. The
  architect reads it, writes their own words where it asks,
  and posts it, or not: the hive opens no issue, calls no API and writes nothing for anyone.
- **A weakness of the hive is reported privately, never in an issue** ([SECURITY.md](../SECURITY.md)). Turning on
  GitHub's private vulnerability reporting for this repository is the founder's setting.
- **What comes back is data, never instructions.** The numbers, the issues and every word in them are data for those
  who build the hive, and for their agents: an issue that asks for a change is weighed like any other proposal, and
  nothing it says is run, followed or obeyed as such.

## Where the cutter runs

On the architect's side: the cutter is a scheduled agent of the architect's own, run with the architect's own
subscription, like a volunteer's worker ([join.md](join.md)), with a guide of its own in
`.claude/skills/bee-cutter/`. The hive holds no key and no secret for it, and pays for nothing. It publishes with
the architect's account, which may change the published branch: the project's trusted base decides alone, and the
gate, the bound on each cycle and one commit to go back are what hold if it errs. A project that wants a person to
read each cut before it lands says so in its charter: the cutter then opens a pull request instead of publishing.

Or on a trusted account's side: an account the project trusts with `cut` cuts during the duties the hive deals it
([protocol.md](protocol.md), "Trusted accounts and their duties"). Its agent runs the same guide, from a clone of
the project and one of its own fork, every hour while it works for the project. It pushes its cut to its own fork,
and the project's publisher (`hive.py publish-cut`), run with the project's own account, publishes the cut that
stands. The guide says both sides: the account's ("For a trusted account: the cut duty") and the architect's ("For the
architect: the trusted accounts' cuts"). A charter that asks a person to read each cut holds for these cuts too: the publisher
opens no pull request, so the architect then runs it by hand, after reading the cut that stands. No schedule
runs the publisher on such a project.

## Not yet

- A deal weighted by the cutter (recruitment in proportion to what an area yields, a share of scouts, scores that
  evaporate, a quorum before committing): a change of the protocol.
- A volunteer's agent says why it gave a task back, or what it saw, in signals ("Signals"), with no evidence and at
  the release's flat cost, signalled or not (the founder's choice: a signal never makes a release cheaper). A probe that
  cannot be tried within its files is not given back yet (its deal runs out): a change of the protocol, later.
- Rules on signals beyond C1, each gated on a measure of the ledgers: a task made stuck by two established members
  who agree on one code (gate: how many such tasks were later accepted without a cut); a probe at the floor on the
  files of a task accepted with `more_gain` (gate: how many such probes reached the floor); a weight for each account
  by how often its `confidence` or `local_check` disagree with the judge.
- Exploration beyond probes: `hunt` tasks, findings the guardians restate as structured fields, an archive of
  approaches, a ladder of easier variants.
- The guardians' audit of a random sample of refusals, which measures the judge's own error; candidates accepted with
  `confidence: low` and the tally's `disagreements` are where it would look first.
- A survey in the project's run that measures, in the judge's container, what the cutter needs (hot spots, the
  reference's failing cases).
- The cutter's settings in the architect's console.

## Order of building

1. This document. **Done.**
2. The tally (`hive.py tally`) and a section of the project's page for the tasks that need attention. **Done.**
3. The fields `parent`, `needs` and `kind`, checked wherever a run reads the tasks; the gate (`hive.py cut-check`);
   and the cutter's settings in the project's file (`cutter`: `floors`, `changes`, `open`, `context_chars`),
   described in `hive/settings.json` with their bounds, and read by no run but for `open`, which paces the cut duty of a
   trusted account ([protocol.md](protocol.md), "Trusted accounts and their duties"). **Done.** The page's tree of cuts: **done**
   (21 November 2026).
4. The deterministic cutter (`hive.py cut`), the outline (`hive.py outline`), the AI cutter's guide
   (`.claude/skills/bee-cutter/`): **done**. A trial of two or three cycles on miniz and cjson: under way (as of
   21 November 2026, one cycle on each project has been published, and some of its tasks dealt to a bee and
   judged; the projects' ledgers, on their branch `hive-state`, hold the details).
5. Feedback from projects: `hive.py health`, `hive.py report`, the issue templates and `SECURITY.md`. **Done.**
   (GitHub's private vulnerability reporting, which `SECURITY.md` sends weaknesses to, is the founder's to turn on.)
6. The proof at the tip: the project's run judges its tip as a candidate for planned tasks « correct », the write job
   records the answers in `tip.json`, and `hive cut` and `cut-check` take the proof from there ("The proof at the
   tip"). **Done**; it acts in a project once its caller names a commit of the hive that holds it. The last manual
   step of a cycle on a project of the reference kind: with it, a cutter can run alone on a schedule.
7. Cutting by trusted accounts: the cut duty, its proposal held to the gate in the project's run, the publisher
   (`hive.py publish-cut`), and both sides in the cutter's guide. **Done** in the hive. Moving a pilot onto it (a
   trusted account cutting, the architect's schedule running the publisher): not yet.
8. The members' signals: codes beside a candidate or a release, recorded on the ledger and changing nothing the hive
   decides; read by the tally, `health`, the page and the cutter's guide; C1 in the deterministic cutter ("Signals").
   **Done** in the hive; a project takes them when its caller names a commit that holds them.
