# The hive protocol, version 1

*How work reaches the hive. Implemented by `tools/hive/hive.py`, tested by `tools/hive/test_hive.py` and
`tools/hive/test_schedule.py`. A project holds its own settings, its tasks and its state, in its own repository, and
calls the hive's run from there ([hosting.md](hosting.md)); in this text, « the protocol » is this repository,
`Bee-ruche/hive`, at the commit the project's run names: the hive's code and its judges.*

> **Status: in service by invitation for two test projects** (miniz since 16 November 2026, cjson since
> 17 November, with one worker, the founder's own, first from `Bee-ruche/registre`; since 19 November each runs from
> its own repository, as [hosting.md](hosting.md) says). **Nobody else is invited
> before a whole round of review by another model, on the code as it stands, finds nothing high or critical**
> ([plan.md](https://github.com/Bee-ruche/registre/blob/2baa4d2/docs/plan.md), 7.2). In an
> earlier draft, members competed for tasks and the hive decided who came first; review after review, by a model
> other than the one that wrote the collector, that decision was where the guarantees gave way. This version removes
> the competition: **the hive deals each task to one member at a time.**

## The idea in six lines

1. A volunteer forks a project and points their AI worker at the fork. **The only thing a worker ever writes is a
   commit pushed to the volunteer's own fork.** No pull request, no comment, no token for the hive.
2. The worker **asks for a task** (a marker on its fork). The hive **reads the forks, once per run**, and **deals**
   each asker one open task, for three hours. At any time at most one member may submit for a task, and the hive
   decides who.
3. The worker does the task and pushes its candidate, marked for that deal.
4. The candidate is merged on the project's current tip and **judged in the isolated judge**, by code that comes
   from the project's own branch, never from the candidate.
5. What passes is **integrated as one commit**, authored by the fork's owner as GitHub names them, and recorded in
   a public ledger. What fails gets a reason code.
6. A **feed** tells each worker what it holds, until when, and what has been tried on each task.

Because workers trigger nothing in the hive (no workflow, no API write), there is no approval click for
newcomers, no flood of pull requests, and no path from a contribution to a secret. Because a task has one holder,
there is no race to win, nothing to gain by copying someone's public work, and no work done twice.

## What a worker pushes

Three kinds of commit, each recognised by lines of its **tip commit message**, each alone on its line.

**An ask**, on the fork's branch `hive/ready` (pushed over the previous one): a commit that holds no file and has
no parent, so that it carries its message and nothing else.

```
Hive-Action: ready
Hive-Member: alice
Hive-Tier: 2
Hive-Prefer: miniz_tdef.c
```

**A candidate**, on the branch `hive/submit/<task>`:

```
Hive-Task: miniz-0010
Hive-Action: submit
Hive-Deal: 2026-11-12T12:00:00Z
Hive-Member: alice
Hive-Model: claude-fable-5-2
```

**A release**, on the branch `hive/release/<task>` (pushed over the previous one): a commit that holds no file and
has no parent, as an ask. Its member gives back the deal it holds ("How tasks are dealt").

```
Hive-Task: miniz-0010
Hive-Action: release
Hive-Deal: 2026-11-12T12:00:00Z
Hive-Member: alice
Hive-Because: out_of_reach
```

- `Hive-Member`: the GitHub login of the fork's owner. **A commit counts only in the fork of the member it
  names**: the same commit pushed to someone else's fork is nothing there, and credits nobody else.
- `Hive-Tier` (optional, 1 to 3, 3 by default): the hardest tier of task this worker takes. A task's tier is
  the project's own.
- `Hive-Prefer` (optional, on an ask): the part of the project the member prefers: one of the files the project's
  tasks name, exactly as the project's tasks write it (a folder with its final `/`). `hive.py ready --prefer <file>`
  writes it, from the volunteer's prompt and from nowhere else, and refuses any other value before it makes
  anything. The hive compares what the line says with the project's own strings and takes nothing else from it: a
  value that is none of them is no preference, the ask is still an ask, and nothing of the value is kept anywhere.
  On a candidate the line means nothing. See "How tasks are dealt".
- `Hive-Task` and `Hive-Deal`: the task, and the instant of the deal the candidate answers, as the feed gives
  it. A submit for a task its member does not hold, or for another deal than the one it holds, **is not a
  candidate**: it is not judged, not answered, not recorded, and not read again.
- `Hive-Model` (optional): the model's identifier. It feeds the public statistics of which models succeed at
  what, for the models the project lists; any other is counted as undeclared. It is what the worker declares: a
  statistic, not a proof.
- `Hive-Because` (on a release, and required there): one of two codes of the hive's own. `out_of_reach`: an honest
  try, checked as the task's check allows, showed that the member cannot do the task (its goal, its tests, its
  files). `cannot_run`: the member's machine cannot run the project's sandbox. `hive.py release` writes nothing else
  in it, and the hive takes nothing else from it. `Hive-Task` and `Hive-Deal` name the deal it gives back, as on a
  candidate: a release of another deal than the one its member holds, of a deal that is over, or of a probe given
  back as out of reach (a probe's answer is a correct try, submitted), is nothing, and is not read again. A hive at an
  older commit knows no such action: for it the commit holds no marker, and the deal runs out as it always did.

A key that appears twice, an unknown action or a malformed value means "no marker": the commit is ignored.
`hive.py ready`, `hive.py submit` and `hive.py release` write these commits and push them to the fork. `release`
gives nothing back unless the project's feed shows the member holding that deal, and lists the code among those its
run reads (`releases`: a run at an older commit lists none), and the fork holds no candidate for the deal.
`hive.py start`, before the work, asks the project's own repository for its tip, puts the clone on the task's
branch at that commit, and says the task started only once it has shown that the work tree holds that commit's
files and nothing else: it lists them from the commit's folders, read as bytes it hashes itself, and reads each
entry of the work tree as a plain file. The commands push to one address,
`https://github.com/<login>/<the project's repository name>`, worked out from the member's login (every command is
given it, `hive.py setup` included) and the project's repository (the user's prompt names it);
the address the clone gives its origin is only compared with it. `submit` commits the work (the task's files, and
nothing else of the work tree) and its marker, two commits made on the project's commit that the clone rests on:
whatever else the clone's branch held stays behind. Before it pushes, it asks the project's own repository for its
tip and shows, from commits and folders it reads as bytes and hashes itself, that the candidate starts from the
project's history and changes only the task's files; it then runs the same structural checks as the hive, so that
a worker learns of a refusal before spending a judgement. A refusal it prints names a path only if the project
holds it.

A candidate is identified by its commit id. The same commit is answered once as a candidate, whatever the number
of branches that carry it, and is not read again. A commit that was refused is judged a second time in one case
only: a guardian of the project admits it ("Guardians"). Of several candidates pushed for one deal, one stands (a
draw) and the others are ignored.

## Whose forks are read

Only the forks owned by **a person's GitHub account, older than the project's minimum (90 days by default) and
not banned**. The forks of other accounts (organizations, bots, young or banned accounts) are not read at all:
nothing is fetched from them and nothing is answered, so they cost the hive nothing. A ban names the account's
numeric id: it survives a change of login.

A project can be **open by invitation**: its file lists the numeric ids of the accounts whose forks are read
(`members.only`), and no other fork is. This is how a project starts, among people who are known.

**A fork is read whole or not at all**: one with more new branch tips than the hive reads at once (30), or whose
new branches hold more bytes than one fetch may write (four times what the project takes from one candidate: 128 MiB
unless the project says otherwise), is not read until it holds less, and for the hive it then holds nothing. A fetch
is bounded in time as well; one that does not end well leaves nothing on the hive's machine.

**What a fork's owner can bring about is never « could not be read »**. A fork counts as read once the hive has
listed its branches and its fetch ended well (a branch that moved since the listing is read at the next run), or was
stopped by the bound above, or failed while the fork's branches changed under it. It counts as not read, at no cost
to its member, only when the hive could not list it, or when its fetch failed on branches that stood still: then
GitHub or the network may be the cause.

**A guardian's fork is read for its rulings** ("Guardians"), in the same way and within the same bounds, whatever
this section says of its account as a member's: the project's file names a guardian by the account's number, as it
names a member it invites, and a project open by invitation, an age the account does not have or a ban on it as a
member change nothing to that. What such a fork holds as a member's (an ask, a candidate) is then nothing, as
before, and is not remembered either.

## How tasks are dealt

Each run, after the forks were read, in this order:

1. **Deals whose time is up.** A deal lasts three hours from the moment it is published, plus one hour of grace.
   After that, if the member's fork was read whole in this run and holds no candidate for the task, the deal
   *expires*. If the fork could not be read, nothing is decided; a day later the task is freed at no cost to the
   member. A deal on a task the project closed meanwhile ends at once, at no cost either. **A deal its member gives
   back** (a release of that deal in the member's fork) ends at once too, whatever time it has left, and its task
   is free for others in the same run. A candidate for the same deal wins: it is judged, and the release is spent.
   A release counts as long as the ledger holds the deal as live, whenever the run that reads it comes (its time
   and its grace may be past), as a candidate does; `hive.py release` gives nothing back once the deal's time is up.
2. **Candidates.** A submit is a candidate if its member holds the task's live deal and it names that deal. An
   expired deal is over: what its member pushes for it afterwards is not a candidate.
3. **Askers.** Members with an ask at a branch tip, except those who hold a deal without a candidate, are waiting
   after a deal that ended badly, or have had their deals for the day. In this order: those whose last deal was
   accepted, then those who never had one, then the others; within each group, a draw.
4. **The deal.** Each asker gets one task, drawn among the open tasks that nobody holds and that it takes by its
   tier. While two at least of those tasks are ones the member never held in vain (a candidate of its own
   refused, a deal it left without one), the draw is among these alone: a task that failed in a member's hands
   goes first to another member, or waits. With fewer than two, the draw is among all of them: the rule narrows
   a draw, it never names a task. An ending that was the hive's or the project's doing is not held against the
   task, and what a member held in vain stays so. A probe is among them only for a member with an acceptance of its
   own on the project, and never for one who answered it ("How a candidate is judged and integrated"). The draws use a key drawn *after* the forks were
   read: nobody can push something that steers them. An ask is used once.

**A project's trusted base keeps pace with its members.** A project that names guardians ("Guardians") may say how
many active members one guardian covers (`members.per_guardian` in its file): the project's lead sets it, and the
hive counts. A member is *active* when it holds a live deal (a task is in its hands now, however long ago it was
dealt), or when a candidate of its own was **accepted** within the project's window (`members.active_days`, 30
days unless the file says otherwise: to the second, from the instant of the acceptance's line; an acceptance a
guardian's ruling brought is one). Nothing else makes a member active: not an ask, not a deal that ran out, not a
candidate that was refused. A place is held by work the project took, or by a task being worked on; an account
whose deal ends otherwise holds none from then on, and then waits what any member waits. And an account the
project's file does not take today (one it bans, or one it does not name where it is open by invitation) is never
counted, whatever the ledger holds of it: its place is free from the next run. The base *covers* `per_guardian`
times the number of accounts the file names as guardians. A member that is active is dealt as above; a member
whose candidate waits for its answer holds a live deal, and is dealt its next task as any such member is (once the
candidate is answered, an acceptance keeps it active and a probe's answer does not: see below). An asker
that is not active is a **new member**, and is dealt a task only while the active members, with the new ones the
same run has already dealt to, are fewer than the base covers. Beyond that it is passed over: no deal, no line, no
wait, and its ask stays where it is, for the run that finds room (a deal ends without an acceptance, a member's
last acceptance leaves the window, the project turns an account away or names one more guardian). The askers come
in the order of point 3 whatever the bound: it holds a new member back and moves nobody ahead. A member that is
active is never turned away by it, even where the project has more of them than its base covers. A project that
sets no `per_guardian` has no such bound. The jobs that write hold the plan against the same rule, from the
project's file, its tasks and the ledger as the plan read it: they count the active members themselves, once the
deals the plan says are over are closed; they hold each of those deals as one the ledger has live and whose time
is up at the plan's instant, or whose task is no longer open (that the member's fork held no candidate for it is
the plan job's reading of the fork); and a plan that frees a place by a deal that is not over, or deals to more
new members than the base covers, is not applied at all.

Between the candidates and the askers come the rulings of the project's guardians, where the project names any
("Guardians"): a ruling that stands is served when its task is free and every open task that shares a file with it
is; the commit it admits is then that task's one candidate in the run, and those tasks are dealt to nobody in it.

**A member may say which part of the project it prefers, and the hive follows it only when its own rules lose
nothing by it.** The project is already chosen by the fork the worker runs in; a part is one of the files the
project's tasks name. At the member's turn, among the tasks it could be dealt anyway (open, held by nobody, the
tasks that share a file with them free too, of a tier it takes, and those it never held in vain alone while two
of them are left: point 4 above), the preference is kept if and only if, decided in
this order:

1. the project offers preferences (`members.preferences` in its file, on by default);
2. the member's last deal that came to an end, in whatever way, ended with an accepted candidate (an ending that
   cost the member nothing, such as a task the project closed, is no accepted candidate either). For a member dealt
   in the run that answers its candidate (below), that is where it stood before that answer;
3. at least two of those tasks list the part: a preference chooses a part, never a task.

The task is then the same draw among those of these tasks that list the part. In every other case the plain draw
runs, unchanged, and the deal's line says why the preference was not kept: `not_offered`, `needs_an_accepted_deal`
(one word for a member that never had a deal come to an end and for one whose last deal ended otherwise: the line
names its member), `no_free_task` or `one_free_task` (one task alone listed the part: following the preference
would have chosen it). A member with several asks has a preference only if all of them name
the same part. Two things hold whatever an ask says: **a kept preference only ever gives a task the plain draw
could have given, and the order in which askers are served reads no preference.** Nor do the waits, the day's
deals, the tiers, or the rule on tasks that share a file.

**Tasks that may change the same file are never held by two members at once.** What a member pushes for its task
is public; someone holding another task on the same file could put that work into its own candidate. So such a task
is dealt only when the others are free. A project whose tasks name separate files loses nothing; one whose tasks share a file does them one at a time.

A member who pushes a candidate *and* an ask is dealt its next task **in the same run, when that candidate is
accepted, or is a probe's answer** ("How a candidate is judged and integrated"): a worker that runs every hour and
succeeds gets a task per run, and an answer, which costs no wait, frees its member as an acceptance does. The task
is the one the plan kept for that member, and the job that writes holds it again, once the run has answered,
against the rules it was dealt by: the member waits for nothing; the day's limit (a probe's answer stays one of the
member's deals of the day, so a member it brings to the limit is kept no task); the trusted base's cover (above: an
acceptance keeps its member active, an answer does not, so a member whose last acceptance has left the project's
window, and who held its place by its probe alone, is a new member then, dealt only if the base covers one more);
and never a probe the member answered.
If the candidate is refused otherwise, whatever the reason and even at no cost to its member, the ask stays, and is
served at a later run, once any wait is over.

What ends a deal, and what it costs its member:

| The deal ends when | Cost to the member |
| --- | --- |
| its candidate is accepted | none; it clears any wait |
| the judge examined its candidate and refused it (`judge_refused`, `goal_not_met`, `requirement_not_met`) | a wait of two hours, each time, never doubled: a refusal there is ordinary, on tasks that ask for a measured gain |
| its task is a probe, and the judge found its candidate correct, within every figure the project requires, and short of the probe's goal (`goal_not_met`): the probe's answer ("How a candidate is judged and integrated") | **no wait**, and no credit either: the class is left as it was, and the deal counts in the day's limit |
| the judge examined its candidate, found it correct, nothing degraded and the figure the task asks for reached, and only the proof of it is missing or did not come out beyond the measure's noise (`not_proven`) | **no wait**: the hive does not charge a member for what its own stopwatch could not tell. It cost the hive a judgement all the same, and it is a deal that did not end in an acceptance: it counts in the day's limit and in the member's class |
| its candidate is refused before the judge could examine it: on a structural rule, because it does not merge or changes nothing, after three failures that are its own (`judge_failed`) or three pushes the project's repository declined (`push_refused`) | a wait that doubles |
| its member gave it back (a release: `out_of_reach`, or `cannot_run`) | a wait of two hours, each time, never doubled, as when the judge refused a candidate: the deal ends hours before one left to run out, with no longer a wait, and never at less cost than trying. The deal counts in the day's limit, and the task is one the member held in vain |
| its time is up and the fork holds no candidate | the same wait that doubles |
| the hive could not answer it in six runs for no fault of the candidate's (`not_answered`), could not read the fork for a day, or the project closed the task | none: not the member's doing |

These are a project's defaults (two hours as the first wait); a project whose file names one account alone may
set the wait to nothing while it is tried, and then only the day's count is left of what follows.

**A deal that does not end in an accepted candidate costs something**, so that no way of ending a deal is free: a
wait, or, for a candidate that lacks a proof alone, its place in the day's limit. When the judge examined the
candidate, the wait is two hours; there is none when the candidate is correct, reaches the task's own figure and
lacks only a proof (`not_proven`): the hive cannot tell a gain the noise hid from no gain, so it neither accepts
nor charges. **A deal given back costs two hours, each time**, as a judged refusal, never doubled. A worker that finds
its task out of reach and says so at once frees it for others hours earlier, spends no judgement, and is free itself
as much sooner than after a deal it lets run out. When the task was held for nothing (no candidate, or one
refused before the judge), it is two hours doubled at each such deal since the member's last accepted candidate,
seven days at most; an acceptance clears both, and nothing else does. A project also limits the deals an account
is given in a day (5 by default), **not counting those whose candidate was accepted**: the limit bounds what an
account can take and waste, never what it can contribute. (A deal whose candidate still waits for its answer
counts until it is accepted.)

So an account holds at most one task at a time, chosen by the hive, and one that takes tasks and leaves them is
dealt fewer and fewer.

## What the hive checks before judging

All of it is read from git objects, on **the difference between the project's tip and the candidate merged on
it**: exactly what would land.

| Reason code | Refused when |
| --- | --- |
| `unrelated`, `too_many_commits`, `history_too_big`, `conflict`, `empty` | the branch does not come from the project, is too long, holds commits that together weigh more than the project allows (32 MiB, unless the project says otherwise, as git packs them on the project's tip, which is how the hive carries them: whatever a commit added on the way counts, even removed since), does not merge on the tip, or changes nothing |
| `path_outside_task` | a changed path is not one of the task's files (a hard rule, not a warning) |
| `protected_path` | a changed path is protected, **at any depth of the tree**: CI and editor automation (`.github/`, `.vscode/`, `.devcontainer/`…), what steers git (`.gitattributes`, `.gitmodules`), **agent instruction files and folders** (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `.claude/`, `.cursor/`…), the hive's files (`hive/` at the root), and what the project adds (its tests, its judge) |
| `special_file`, `mode_change` | a symbolic link or submodule, an empty folder or a folder that is not, byte for byte, the one git writes for its entries (written by hand: an entry twice, entries out of order), a changed file mode |
| `bad_path` | a path that is not plain printable ASCII, or a **new** name that is not an identifier: letters, digits, `. _ + -`, 64 characters at most per part, not starting with a dot or a dash, not ending with a dot |
| `binary` | a file with a NUL byte anywhere (the hive reads the bytes itself), or one git calls binary |
| `too_many_files`, `too_large`, `file_too_big`, `line_too_long` | the project's size limits, among them the length of an added line. The hive lists what a candidate changes itself, folder by folder, and stops past the limit; no file is read before the entries are counted: what a candidate costs to refuse does not grow with what it sends, however many paths a few objects describe. A file larger than `file_bytes` is refused before the candidate is merged on the project's tip (git's merge reads whole each file that both sides changed), and a candidate one of whose own commits holds such a file, even removed since, is not carried to the judging at all: the plan asks git the size of each object those commits add. This holds whatever the project's own files weigh: a candidate whose commits bring a file larger than `file_bytes` is refused even where that file is the project's own, so a task on such a file waits until the project raises its limit |
| `stored_otherwise` | a changed file is not stored as the project's own rules store it (its `.gitattributes`: line ends, an encoding): once integrated, git would find it changed in every clone, where nobody changed it. The hive asks git, as a checkout does |
| `judge_refused`, `goal_not_met`, `requirement_not_met` | the judge refused; the candidate is correct but misses the task's goal; or it misses a figure the project requires of every contribution |
| `not_proven` | the candidate is correct, degrades nothing and reaches the figure the task's goal asks for, but a proof the project takes of it (`judge.confirm`) is missing or short: everything the goal asks is there except its proofs. Nothing is accepted without its proof, and nothing is held against the member: no wait |
| `judge_failed` | three times the judge failed on this deal's candidates (it ran out of time, for instance), or the hive could not derive them, while both worked on the project itself |
| `push_refused` | the project's repository declined the commit (a rule on what may be pushed there), three times |
| `not_answered` | the hive spent six runs on this deal's candidates without an answer, for no fault it can pin on them (see "What holds over time") |
| `task_closed` | the project closed the task between the plan and the write step |

Agent instruction files are protected because an integrated instruction would be read by every later worker: a
stored prompt injection. Coding agents read such files in sub-folders too, so the rule holds at any depth. Changes
to protected paths are ordinary pull requests, reviewed by the project's maintainers.

This narrows one channel; it does not close it. Whatever a contribution adds (a comment, a string, a file's name)
is read by the workers that come after. That is why a worker treats everything in a project as data, and why it can
reach nothing but a branch of its owner's fork.

No `.gitattributes`, the project's own included, changes how the hive merges, counts lines or finds binary files:
the hive runs those git commands with an empty attribute source.

## Four jobs, each with one risk

| Job | Holds | Runs contributors' code | Talks to forks | What it does |
| --- | --- | --- | --- | --- |
| `plan` | the project's token, to read | no | **yes, once** | reads the project's settings at its published branch's tip, and names that commit; reads the forks; decides the deals whose time is up, the candidates and the new deals, and the duties that are over and the new duty; writes **the plan** and a bundle of the candidates' git objects (1 GiB and two million objects at most: the candidates beyond either wait for the next run, oldest deal first; one whose own commits are too many or too heavy is refused without being carried); publishes the plan's SHA-256 |
| `record` | the project's token, to write its branch `hive-state` | no | no | checks that the plan is the one `plan` published, and that the published branch is still at the plan's commit; writes the plan's deals, its duties and the feed, **within minutes of the run's start** |
| `judge` | the project's token, to read, given to no step that runs a candidate | **yes**, in the judge's container | no | judges the plan's candidates; writes **a table from the id of each judged commit to the judge's answer**; in a quiet run (no candidate, no task held), for a judge that can tell, judges the plan's tip itself as a candidate for at most two planned tasks « correct », for the cutter ([cutter.md](cutter.md), "The proof at the tip") |
| `apply` | the project's token, to write its branch for the hive and `hive-state` | no | no | checks the plan, and that the published branch is still at the plan's commit; derives every commit by itself; looks each one up in the judge's table; pushes; records; in a quiet run only, writes to the state the judge's answers about the tip for the questions it finds were due, and for no other task |

- **The forks are read once.** What the plan read is what the run is about: a branch taken away or pushed after
  that changes nothing in this run, for anybody.
- **The plan carries a fingerprint of the ledger it read**, and the jobs that write refuse a plan made on another
  state of the ledger: two runs that overlap never deal one task twice.
- **The judging job cannot change the plan**, and the write job takes two things from it: the judge's answer for a
  commit id the write job derived itself (an answer under any other id is nothing), and which commits it started
  on. So a judging job that was taken over can lie about what the judge said of a candidate, or stay silent about
  it, and so decide which candidates are accepted among those that keep every structural rule. That is its limit:
  it cannot name a candidate, a member, a task or a path, decide who is dealt what, credit an account for work
  that is not in its fork, change history, or write anything but the project's listed figures, as numbers, into
  the ledger. The judge's container is what stands between a contribution and that job.
- **The judging job of a quiet run (no candidate in its plan, no task held by a member) asks about the tip** ([cutter.md](cutter.md), "The proof at
  the tip"): it builds and runs again, outside any member's judgement, the units the tip holds, which are the work of
  volunteers the judge accepted. One that broke out of its container there could make the job lie about the tip, for
  the questions due in that run (two at most, about that run's tip, as one of three words), and nothing else: the
  write job works out itself which questions were due and takes answers for those alone, and takes none in a run with
  a candidate, so no candidate's code writes one. Two such lies, in two runs six hours apart, would have the cutter
  publish a task the tip already passes, which a candidate then completes for nothing: the residual risk of the
  proof, as lying about a verdict is the residual risk of the judging.
- **The settings are read at one commit for the whole run.** The plan names the commit of the project's published
  branch it read the settings and the tasks at; the judging job reads them there, and judges nothing when its own clone
  of the project is at another commit (the branch moved since the plan); the jobs that write read them
  there too, once they have asked the project's repository themselves and found the published branch still at that
  commit: otherwise they write nothing, and the next run plans on the settings as they are then. A plan that names
  any other commit is not the hive's. The judging and the write job go through the same candidates, with the same
  ledger, settings, tasks and instant (the plan's): they derive the same commits. A plan from the future, or more
  than a day old, is not applied; nor is anything if the project's tip moved since the plan.
- **Of a guardian's ruling, the jobs that write take from the plan what the plan job read in the guardian's fork**
  (that the fork holds the ruling at its task's branch and what the ruling says, the guardian's login, that the
  ruling carries its commit) **and hold everything else again by themselves**, against the project's file and the
  ledger as the plan read it, before they write or push anything ("Guardians", "What each job holds of a ruling"):
  a plan that says of a ruling what these do not bear out is not applied at all.

## How a candidate is judged and integrated

- The hive first lists, itself and up to the project's limit, what the candidate changed since it left the
  project's history; only then does it compute the merge, without a work tree (`git merge-tree`) and without
  looking for renames (a candidate that moves a file the project changed meanwhile is a `conflict`). It writes the
  two trees to disk **byte for byte, without git's checkout** (no hook, filter, attribute or end-of-line conversion applies), and hands them
  to the judge. A candidate can add or change plain files only; the project's own links and submodules are
  written as they are.
- **A project names its judge's kind** (`judge.kind` in its file). What a verdict is, where judged code runs and
  what may accept a candidate are the hive's, the same for every project; how a candidate is found right or wrong
  is a kind of judge's; what is asked of the judge's figures is the project's. A kind is code of the protocol's: a
  project's file can name one and never bring one, and a file that names a kind the tool does not hold is refused
  when it is loaded, at every step. Three kinds exist. `common`, which a project that names none has, is the
  protocol's common judge (docs/common-judge.md): the candidate gives the same outputs as the project's tip, and
  is measured against it. `reference` (docs/reference-judge.md) is for a port or a rewrite: the unit a candidate
  writes answers exactly as the project's reference does, on cases drawn when it is judged. `relay`
  (docs/relay-judge.md) is for a program run in two phases, the second handed the first's message and nothing
  else, which must give the project's data back: what it measures is exact (the message's bytes and the built
  program's), and its proof is an exact comparison with the tip's figure, with no noise to be beyond (a
  compressor and its decompressor). In all three, candidate code builds and runs only in a container without
  network, and the verdict is derived on the host. Whatever the
  kind, code 0 is correct, 1 a refusal, 2 a failure to judge, and the project's tip judged against itself is
  answered 0. Another question is asked of the reference kind alone, in a quiet run (no candidate, no task held): the tip
  judged **as a candidate** for a task, where the unit the tip holds is built and run as a candidate's is. Its answer
  is no verdict and moves nobody: it
  tells the project's cutter whether a planned task « correct » fails at the tip ([cutter.md](cutter.md), "The proof
  at the tip").
- **A project's settings are its own, and name it.** `hive/project.json`, in the project's repository, names that
  repository (`repo`) and its default branch (`published`), where it is read: a file that names another repository or
  another branch is refused, so one project's settings never run another's state or forks. A step of the hive reads
  the settings of the repository it runs for and no other; a worker's command checks in full the settings of the
  project it is told about (its repository, as the user's prompt names it) and reads nothing of any other.
- **A failure to judge is the candidate's doing only if the machine works and the tip is sound.** When the judge
  fails on a candidate, the hive asks it about the project's own tip against itself. If that fails too, the machine
  is down: the run stops judging and no candidate pays for the breakdown. If it passes, the failure is counted
  against the deal, whose candidate is judged again at the next run, three times at most. A judge may also say, in
  its answer, that its failure is on the tip's side (`"fault": "tip"`: a kind that measures the tip in the same
  judgement as the candidate, before anything of the candidate's runs, takes it from the report its judge wrote;
  the relay kind does, once the tip's own build or phases failed, and the reference kind, once its reference or its
  control failed, before the candidate's build; either is taken as the tip's, not as proof that its code is
  wrong): the hive then does as when the judge fails on the tip itself, without asking it: the run stops
  judging, the candidate it was on pays nothing, and the log says that the judge found the fault on the tip's side,
  and for which task. The field is read on a failure to judge alone, in that one spelling; a kind that never writes it
  is answered as before. A run whose judge failed on the project's own tip, or found it at fault, ends as a failure
  once everything it could decide is written, so that a person sees it: the machine may be down, or the tip itself
  may no longer pass the project's check. A project whose tip is at fault stalls, its candidates waiting, until its
  maintainers mend the tip (a revert of the commit that brought the fault in).
- **A measure accepts no candidate alone, whatever the project and whatever its judge.** A judge gives measures (a
  gain, a count) and proofs. A proof is a figure named `sure_<measure>`: 1 when the judge saw, by a comparison it
  made from outside the two programs and beyond its noise, that the candidate is better, else 0. A task may add a
  goal on a figure of the judge's report (for instance a minimum gain), and a project may require a figure of every
  contribution. A goal names figures the project lists, and it always holds one of the proofs the project takes
  (`judge.confirm`), with a minimum of 1: a task whose goal could never be met, or would rest on a measure alone,
  is refused when the project is loaded, at every step of the hive. The common judge gives a `sure_` figure for
  each measure of its report's « metrics »; a count made by a tool that runs the program inside itself is not one
  of them, and has no `sure_` figure under any name. Among those figures a project takes as proofs the ones the
  judged program cannot bear upon (the processor time the kernel reads, what the judge itself reads of the
  outputs), and its maintainers answer for that choice. What a project requires of every candidate
  (`judge.require`) can only refuse. **What the hive vouches for in an accepted contribution is its proof**: that
  the judge saw it better beyond its noise, with the same outputs. A bound on a measure that has no proof (in miniz,
  the count of instructions) is a bar that can only refuse: the hive does not vouch for that measure's size, and the
  ledger keeps it as the judge gave it. The page leads a contribution's card with a figure that has its `sure_`, and
  with no other: a measure without one is a row of its table. Told which proofs the project takes (its file, given
  to the page tool), the page leads with one of those measures only: a flag the project keeps and does not take as
  a proof leads nothing.
- **A probe's answer is what the judge measured.** A task of the kind `probe` asks one named thing to be tried,
  without knowing whether it helps; its goal is on a figure, as a `work` task's is. A member's candidate for it that
  the judge finds correct, within every figure the project requires, and short of the probe's goal (`goal_not_met`)
  is the probe's **answer**. A candidate short of its proof alone (`not_proven`) reached the goal: a working idea, not
  an answer, and on a probe it is what it is on any task (no wait, and the probe stays open). An answer:
  - Its line is the refusal's, with the judge's figures, and one number more, `probe` ("The ledger and the feed").
    Nothing is integrated.
  - It costs its member no wait and leaves its class as it was. It is no acceptance: it makes nobody active, follows
    no preference and counts for nobody's standing. It still counts in the day's limit, so an account answers no more
    probes in a day than the project's `members.deals_per_day` (5 by default).
  - A probe is dealt only to a member with an acceptance of its own on the project already, in the ordinary and the
    conditional deal alike, and a member who answered a probe is never dealt it again, even when it is the one task
    left. On a project's first day, with probes alone open and nobody established, nobody is dealt anything.
  - The probe is **done** once as many distinct **established** members answered as it asks (`answers` on its
    line, 1 by default, 5 at most), or once a candidate reaches its goal with its proof, which is accepted and
    integrated as any other. A member is established for an answer when a candidate of its own was accepted on the
    project before it: the answer counts only after its member's first acceptance, as a failure counts towards
    « stuck ». Since a probe is dealt only to such members, every answer counts when it is given; a line that says
    otherwise (written by hand, or under an earlier rule) still completes nothing. An answer that tries nothing costs
    its author nothing, so it must not close the question for everyone. Done means done for everything that reads
    it: no deal, the `needs` of other tasks, the feed, the tally.
  - A refusal by the judge, a figure the project requires that is not met, and everything refused before the judge
    (a change that changes nothing among them) are the refusals they are, for a probe as for any task. A ruling
    reviews a refusal for a figure the project requires: a probe's answer is none, and a ruling brings no probe an
    answer.
  - Nothing the worker wrote is recorded. The thing to try is named by the task, which the cutter wrote; the answer
    is the judge's numbers. Nobody can check that it was really tried: a correct candidate that changes nothing the
    judge counts (a comment) answers « nothing gained ». That is why a probe may ask several answers, and why the
    cutter weighs one short answer from one member as weak evidence ([cutter.md](cutter.md), "Probes").
  - A hive at an older commit reads a probe as a `work` task: its short answer is an ordinary refusal, with its
    two-hour wait, and the task stays open. A project publishes probes once the commit its caller names holds this
    rule.
- **A refusal on the suspects says which of the judge's checks it was.** The common judge counts what its
  reading of the compiled code and of the source flags in a candidate and not in the base (`suspects`), and a
  project may bound that count for every contribution. Beside the count the hive takes from the judge's report one
  figure for each kind the judge counted at least one of, `suspects_<kind>`, under the judge's own word for the kind (`bytes`: bytes that spell an instruction a computing
  library has no use for; `instruction`; `source`; `defined_symbol`, `external_call`, `forbidden_call`,
  `forbidden_symbol`, `symbol`; `section`; `architecture`; `incomplete_analysis`). A project that keeps those
  figures has them on the refusal's line. These words are English from judge-v5 on; the ledger's past lines keep the
  words they were written with (`suspects_octets`, `suspects_appel_externe`…, [common-judge.md](common-judge.md)). A kind the judge counted none of has no figure, so these figures say and
  bound nothing: a project bounds the count itself. What was flagged (a name, bytes, a line) is text of the judged
  code: it stays in the judge's own report and reaches no line of the ledger.
- Candidates are judged one after the other on a tip that moves with each acceptance, so **what is integrated is
  exactly what was judged**. They are different tasks' candidates: there is one per task at most.
- **The order: oldest deal first**, so that a candidate the run had no time for moves up. After them come those a
  run already failed on, and last those the project's repository already declined.
- The integrated commit is a squash: its tree is the merged tree, its parent the tip, its author the fork's owner
  (`<id>+<login>@users.noreply.github.com`: the member is credited), its committer the hive, its date the instant of
  the run that judged it. Its message says what it is, in the hive's own fixed words: that an AI coding agent wrote
  it unattended, that the hive's judge accepted it and that no person read it before it was integrated; then the
  task, the member, the candidate and the model the worker declared (`Hive-Model`, or `undeclared`). It is
  deterministic: the same tip, candidate, task, member, model and instant always give the same commit id. The
  candidate's own commit messages and author fields never enter the project's history. A commit a guardian
  admitted says so: in place of the judge's acceptance and « no person read it », that the judge refused it for a
  figure the project lets its guardians waive, that a guardian of the project admitted it and that it was judged
  again in full; and in two lines more, `Hive-Guardian` (the guardian's login) and `Hive-Ruling` (the ruling's
  commit id).

## Guardians

Members are strangers, and nothing in this protocol trusts one. A project may also name **guardians**: a few
accounts that its own file trusts, by their GitHub account numbers (`guardians.accounts`). A guardian is honest
and may be wrong. It decides alone and at once, and what guards against its mistakes is that each decision is a
public line of the ledger, with its account on it. A project that names none takes no ruling, and everything
below is absent from its runs.

A guardian has one power: **to admit one commit that the hive refused for a figure alone that the project lets a
guardian waive.** What a project requires of every contribution (`judge.require`) can only refuse, and one such
bar may be a count of what the common judge flags in a candidate (`suspects`): a flagged construct is not a
fault in itself, it is what a guardian reviews (docs/common-judge.md). A ruling is the outcome of that review. It
relaxes nothing that is asked of members: the commit is judged again, in full, and the ruling changes one thing in
that judgement.

**What may be waived is the project's to say.** `guardians.waive` lists figures, each with a bound. A figure
there is one the project keeps and requires with a `max`, in one condition that asks nothing else; its bound, that
`max` at least, is the most a ruling may let the figure reach. A file that says anything else of its guardians
does not load.

**A ruling** is a commit at the tip of one branch of the guardian's own fork: `hive/rule/<task>`, the branch
`hive.py admit` writes for the task the ruling names. Its one parent is the commit it admits and its files are that
commit's, so that reading the guardian's fork brings the admitted commit itself, whatever its member's fork holds
since. Its message, each line alone on its line:

```
Hive-Action: admit
Hive-Member: gina
Hive-Task: miniz-0010
Hive-Commit: 3b1f0c9a5d2e4f60718293a4b5c6d7e8f9012345
Hive-Waive: suspects 2
```

- `Hive-Member`: the guardian's login. A ruling counts only in the fork of the account it names, and only if the
  project's file names that account (the number GitHub gives for the fork's owner).
- `Hive-Task` and `Hive-Commit`: the task, and the full id of the commit admitted, as the ledger's refusal names it.
  **A ruling counts at one branch, by its name**: the guardian's fork lists `hive/rule/<that task>` at that very
  commit. A guardian's fork holds other commits than those the guardian's command made (a commit fetched to be read,
  and pushed along with the rest): what one of them says is no decision of the guardian's, whatever it is shaped
  like.
- Anywhere else (a fork whose owner the project's file does not name, the member's own fork included; another
  account's name; any other branch of a guardian's fork) a commit shaped like a ruling is a commit without a
  marker: not read again while it stays there, and no line. That holds for good: a guardian the file names later,
  or one who meant a ruling that sits elsewhere, makes it anew (`hive.py admit` makes a new commit each time).
- `Hive-Waive`, once for each figure waived: the figure, and up to what, as a plain decimal number. The hive
  compares the figure's name with those the project's file lists and keeps the file's own string; a name the file
  does not hold is counted and goes no further.

`hive.py admit --project <project> --login <the guardian's login> --task <task> --commit <id> --waive
<figure>=<bound>`, run in a clone of the guardian's fork that holds the commit, makes the ruling and pushes it to
the fork's branch `hive/rule/<task>`, under the same checks of the clone as a worker's commands; `--withdraw`
deletes that branch. The guardian fetches the commit into that clone **by its id, as the ledger's refusal gives
it**, never as a branch of its member's fork: a branch is whatever its owner pushed there since, and what it holds
is data. A guardian keeps no branch under `hive/rule/` that came from another remote, and pushes there only
through `hive.py admit`: what a guardian's fork holds at that branch, the hive takes as the guardian's. The
command decides nothing: whether a ruling stands is said by the hive.

**A ruling stands** only if all of this holds:

- the project's file names the account;
- the ruling carries the commit it names (its one parent, the same files);
- the task is one of the project's, open, and not done;
- the ledger holds the hive's answer to that commit as a candidate for that task, and that answer is a refusal
  `requirement_not_met` whose line keeps what the judge measured: every requirement that report fails is on a
  figure the project lets a guardian waive;
- the commit's member is an account the project takes today, by its file: not one it bans (by the account's
  number, or by the login of its deal's line), and, in a project open by invitation, one the file names. A ruling
  brings in no work of an account the project has turned away since. The login held against a ban here is the
  one the member had when it was dealt the task, where the reading of forks holds the fork's login of the day: a
  ban written as a login reaches a ruling under the login of that time only, and a ban by account number is the
  same everywhere. A project that bans, bans by number;
- the commit is not the guardian's own, except in a project whose file names one account alone as its members: a
  trial with one person in it has nobody else to rule, and the line shows the same account twice;
- each figure the ruling waives is one the file lists, with a bound between what the project requires and the
  file's own bound, and the ruling covers what the commit failed: each failed figure, as far as it was measured;
- the ruling has no answer yet. Of several rulings that stand on one commit, one is taken, by the run's draw; the
  others are answered `duplicate` by the run that answers that one, and wait with it until then.

**What each job holds of a ruling.** The `plan` job is the only one that reads a fork, a guardian's as a member's.
Three things are its reading, and the jobs that write take them from the plan, as they take from it which commits
a member's fork held: that the fork of that account holds, at the task's ruling branch, a commit of that id that
says this (the task, the commit, each figure waived and its bound); the login GitHub gives for the account; and
that the ruling carries the commit it names. Everything else in the list above is read from the project's file,
its tasks and the ledger, and `record` and `apply` hold it again, by themselves, against the ledger as the plan
read it, before they write or push anything: the account is one the file names; the commit, its task, its member,
that member's login and fork, the deal and the model are the ledger's own for that refusal, field for field; the
refusal is one a guardian may lift; the member is one the project takes; what is waived lies within the file's
bounds and covers what the commit failed; the task was free, and no other candidate or deal of the plan takes it or
a task that shares a file with it; a void line names a task of the project's or none, for the reason those same
readings give; `duplicate` is said only in a plan that admits the same commit under another ruling; and no ruling
is named twice in a plan. A plan that says otherwise is not applied at all. One case is the project's doing and
stops nothing: a task the project's tasks close, or list no more, when the write job reads it. Whatever the plan
said of a ruling for that task (admitted, void for another reason, `duplicate`), the write job answers it void
itself, `task_closed` (`malformed` stays, where the plan read that the ruling does not carry its commit), with the
task as the project's tasks name it now or none, as it refuses a member's candidate whose task was closed meanwhile; a
task's name they do not list reaches no line; and the rest of the plan is applied.

**A ruling that stands is served when its task is free**, and every open task that shares a file with it: until
then it stays where it is, in the guardian's fork, and the hive keeps nothing of it. Then the commit joins the
run's candidates, for that task and in the name of the member who wrote it: the account of the refusal's line,
with the login and the fork that the line of its deal gives. **It is judged again as any candidate is**, merged on
the project's tip as it stands then: the limits, the structural rules, the judge's own answer, every requirement
of the project, the task's goal and its proofs. One thing differs: a requirement on a figure the ruling waives is
met when the figure is within the ruling's bound. What passes is integrated and credited to its member.

**Every ruling is answered once, on a line of the ledger, and a ruling that fails costs the commit's member
nothing.**

- *Accepted*: a `verdict` line like any other (the task is done, the member is credited, the statistics count
  it), with four fields more: `ruling` (the ruling's commit id), `guardian_id` and `guardian` (the account that
  admitted it, by number and by login), and `waived` (each figure waived with the ruling's bound). The line names
  the deal the commit answered when it was refused, and it is written when it is decided: after whatever the
  member's later deals came to. The ledger's endings are read in the order they were written, so **that acceptance
  is the member's latest ending**, whatever ended between the refusal and it: every wait the member had is
  cleared, a later failed deal's included; the member has the class, and what goes with it (a preference
  followed), of one whose last deal was accepted, until its next deal ends; and the deal the line names leaves the
  day's count. It is the most recent thing the hive said of that member's work, and it counts as that.
- *Anything else*: a line of type `ruling`, which is no verdict: the ruling's commit id, the guardian's number and
  login, the task (as the project's tasks name it, or none), the commit, a `result` and a `reason`. It names no member
  and counts in nobody's deals, waits, refusals or statistics.

| `result` | `reason` | The ruling |
| --- | --- | --- |
| `void` | `malformed` | does not carry the commit it names |
| `void` | `task_closed`, `task_done` | names a task that is not the project's or is closed; or one that is done (by the commit of a member it was dealt to meanwhile, for instance) |
| `void` | `unknown_commit` | names a commit the ledger holds no answer to, as a candidate for that task |
| `void` | `not_reviewable` | names a commit that was not refused for figures alone that the project lets a guardian waive |
| `void` | `member_not_taken` | admits the commit of an account the project's file does not take today: one it bans, or one a project open by invitation does not name |
| `void` | `own_candidate` | admits the guardian's own commit, in a project whose file does not name one account alone as its members |
| `void` | `beyond_bound` | waives a figure the file does not list, or outside the file's bounds, or not as far as the figure the commit was refused for |
| `void` | `duplicate` | stands, and lost the draw to another ruling on the same commit: said in the run that answers that other ruling, never before |
| `refused` | a candidate's reason code (`conflict`, `judge_refused`, `requirement_not_met`…) | stood, and its commit, judged again, was refused: the line says whether the judge examined it (`judged`), and keeps `detail` and, for a figure, the judge's `report`, as a refusal's verdict does |

A run spent on an admitted commit without an answer is a mark of the ruling, not of the deal the commit once
answered; a ruling's marks end as a deal's do (`judge_failed`, `push_refused`, `not_answered`), on the ruling's
line and at no cost either. The write
job answers rulings, once it has seen the project's tip where the plan saw it; the `record` job holds them and
writes none. A ruling that lost the draw has its `duplicate` line in the run that answers the ruling that won it:
where that run did not reach the commit, or could not tell the fate of its push, both wait. A ruling whose guardian the file no longer names is not applied, and at the next run it is a commit
like any other.

## Trusted accounts and their duties

A project may also trust accounts with a **role**, by their GitHub account numbers (`trusted.accounts`): each
account once, with its roles. `cut`, the project's cutting, is the one role there is. A file that names another
role, an account twice, more than 32 accounts, or an account it bans by number, does not load; an account it bans by
a login and trusts by its number is read for its duties, as a guardian is for its rulings. A project that trusts
nobody (the default) deals no duty: its plans and its ledger hold none, its feed carries `duties` and `duty_wait`
empty, and the settings list and `hive.py doctor` still name `trusted.accounts` among its settings. A cut duty's
work is a **proposal**, which the run holds to the cutter's gate and records (below). **Nothing in the run publishes
it**: the published branch stays the project's own to move, and the project's publisher, `hive.py publish-cut`, run
with the project's own account, publishes the cut that stands once it has held it again itself (below, "Publishing a
cut").

**The ask.** A trusted account that is free asks for a **duty** of its role in its own fork, at one branch,
`hive/duty` (`hive.py duty` makes the ask): a commit with no file and no parent, whose message says, each line alone
on its line:

```
Hive-Action: duty
Hive-Member: carol
Hive-Role: cut
```

It counts only in the fork of an account the project trusts with that role, by that fork's owner, at the tip of
`hive/duty`. Anywhere else, under another name, or for a role the file does not give that account, it is nothing,
for good. Such a fork is read for its duties whatever the project asks of a member, as a guardian's is read for its
rulings; its asks and candidates as a member keep the member rules. A branch of its own keeps an ask for a duty from
ever being taken for an ask for a task: one account may be a member and a trusted account at once.

**The deal.** At each run, after the tasks are dealt, the plan:

1. ends each live duty that is over: at once and at no cost when the file no longer trusts its account with its
   role; on its proposal (below), read while the duty is live, whatever its time, as a candidate is; given back by
   its account (below); or, once its time and the project's grace are past, `expired`:
   - at no cost to its account if the project was paused while the duty was live (a version of `hive/project.json`
     with `"paused": true` on the published branch, after the commit the duty was dealt at: the account's tool told
     it to stop), or if the run comes a day after its time and grace (`UNREAD_HOURS`: the hive did not run, or could
     not read the account's fork, for that long);
   - else at its account's cost if the account's fork was read whole in this run, or it has none;
   - else not yet: its account's fork could not be read, as for a deal, and nothing is decided;
2. deals a cut duty when none is live and either none was ever dealt, or `trusted.cut_hours` (6 by default) have
   passed since the latest one was dealt, or the project has fewer tasks left to do (open or dealt) than its cutter
   aims at (`cutter.open`), which a project that starves always has; after a duty that ended on a cut that stands
   or on nothing to cut, the next keeps to `trusted.cut_hours`, short of tasks or not (a cut stands until it is
   published, and another duty would cut the same commit again);
3. deals it to one of the accounts the file trusts with the role whose ask stands, but not one that holds a live
   duty, nor one whose duty wait (below) is not over: the least loaded first (how many duties of that role the
   ledger dealt it in the last `trusted.window_days`, 7 by default), then a draw with the run's key, drawn after the
   forks were read. An ask's date is the fork's word, and decides nothing. The ask is used.

A duty lasts `duty_hours` (2 by default, from 1 to 24) from the moment it is written, then the project's grace. The
`record` job writes the duties and their ends, and holds each again before it writes anything: one duty per role, of
a role whose latest duty is over, to an account the file trusts with it that holds no duty and does not wait, at the
project's pace, on asks the plan sets aside; and each end against the ledger as the plan read it (that duty was
live; the file took the role away, at no cost, or its time and grace are past, and a day past them it costs
nothing; a release or a proposal the plan sets aside, used once; a proposal called stale if and only if it was cut
against another commit than the plan's). Which asker had the duty stays the plan's word, as a member's draw does,
and so do that the account's fork was read, that the published branch shows a pause, and what a proposal holds and
what the gate said of it.

**The proposal.** A cut duty's account pushes its cut to its own fork, at one branch, `hive/cut`: **one commit whose
one parent is the published commit it was cut against, whose files are that commit's but for `hive/tasks.jsonl` and,
if the cut changes it, `hive/backlog.jsonl`**. Its message says, each line alone on its line:

```
Hive-Action: cut
Hive-Member: carol
Hive-Deal: 2026-11-24T10:00:03Z
Hive-Published: 4f1c0e9a3b2d5c6e7f8091a2b3c4d5e6f7081920
Hive-Tasks: <the SHA-256 of the tasks file it proposes>
Hive-Backlog: <the SHA-256 of the backlog it proposes, if it changes it>
Hive-Area: null
```

`Hive-Deal` is the duty's instant; the digests are those `hive.py cut-check` prints (`CHECKED`); `Hive-Area` is
reserved, and a proposal that gives it another value is none. It counts only in the fork of an account the project
trusts with `cut`, by that fork's owner, at the tip of `hive/cut`, for the live duty that account holds at that
instant; anything else is nothing, and every proposal is read once. It is pushed straight to `hive/cut`: a commit the
hive has read at another branch of the fork is not read again; and once pushed it is not taken back (`hive.py duty
--withdraw` takes back an ask): the next run reads it. The plan holds it, in this order:

1. to the published commit it reads the settings at: cut against an earlier commit the branch was at during the duty
   (one that descends from the commit the duty was dealt at, which the duty's line records), it is `refused` as
   `stale`, at no cost (the branch moved under it); cut against any other commit, or for a duty whose line records
   no commit, it is `malformed`;
2. to its form: one commit on that commit, no other file changed, each file plain and with the mode the published
   commit gives it, and the digests its marker names (a backlog it changes has its digest): otherwise `refused` as
   `malformed`, and so when git fails or runs out of time on that commit;
3. no file changed: `nothing`, a duty that found nothing to cut;
4. its files read as a task file is read: otherwise `refused` as `gate`;
5. to the cutter's gate (`cut_check`, and `backlog_check` for the backlog: [cutter.md](cutter.md), "The gate"), with
   the inputs `hive.py cut-check` gathers: the published tasks, the tasks dealt now (this plan's own deals
   included) and those done, the files of the tip of the branch the hive writes, and, as the tasks shown to fail or
   to pass at that tip, **the judge's answers in the state and nothing else**: no account's word is taken for a task
   « correct ». Refused: `refused` as `gate`. What the hive reads there of its own (the project's published backlog,
   the tip's files, the state) and cannot read: `refused` as `unchecked`, at no cost;
6. a change of tasks, a task added or closed or a task planned: `cut`. Files whose bytes changed and whose tasks did
   not (another order, other spaces): `nothing`.

A proposal and a release of the same duty: the proposal is read, and the release is spent. The duty's end names the
proposal's commit, the published commit and the fork the plan read it in (`repo_id`); `cut` and `nothing` add the
digests. **A `cut` line is the record of which proposal stands.** The steps that write hold what the ledger can tell
of it (above); what the proposal holds and what the gate said stay the plan's word, which the publisher does not take
(below).

What the hive reads of its own for a proposal (its clone's commits, the project's published backlog, the tip's
files, the state) and cannot read, and anything else unforeseen, ends the duty `refused` as `unchecked`, at no cost:
a proposal never stops the plan, and it is read once, so it stops no later run either. The plan's job says how many
of the duties it ended were on a proposal and how many of those were `unchecked`, and says so on a line of its own
when every one was: run after run, that is a fault of the hive's own side, which would make every proposal a free end.

**Publishing a cut.** `hive.py publish-cut --project <owner/name> --repo <clone>` is the project's publisher. It is
run on Linux with the project's own account, in a full clone of the project whose `origin` is its `https://` address
(as `cut-check` reads it), and whose git settings (a credential helper) let that account push the published branch:
by hand, or on the architect's schedule. No run calls it, and the run's token never writes the published branch. It
reads the state on the project's branch `hive-state` as the project's repository holds it when it runs, its latest
commit alone and within a bound in bytes (never a clone of it that may be behind: `state` when it cannot). A deal a
run records after that read may find its task closed by the published cut, and it then ends at no cost, as a deal
on any task the project closes does. That fetch (`--depth=1`) marks a shallow boundary in that clone at the state's
commit alone: the published branch's history is not affected. The publisher takes from the ledger the latest `cut`
line of a cut duty, and from that line nothing but which commit to look at. It then holds, in this order, and says
the first check that fails:

1. `line`: the line has the shape a run writes; `duty`: the ledger dealt that account a cut duty at the line's
   instant, in the fork the line names, and ends that duty on that one line;
2. the published branch: already the publication of that cut (`NOTHING published`), or still at the commit the cut
   was held against; else nothing is published, at no harm (`NOTHING tip`: that cut was published, or the branch
   moved since, and the next cut starts from it as it is); a paused project publishes nothing (`NOTHING paused`);
3. `trusted`: the project's file trusts the account with `cut` now;
4. `fork`: GitHub says the fork the line names (`repo_id`) is that account's own, and a fork of the project itself;
   `branch`: that fork's `hive/cut` still names the proposal's commit; `fetch`: a clone that lacks the commit
   fetches that branch, and takes what comes only if it is that very commit. **The forks of one project share their
   objects**: a commit may sit in a clone, or come from a fork that never pushed it. What binds the commit to its
   account is the account's own branch, which no other account can move, and the publisher takes the commit on
   nothing else of where it came from;
5. `marker`: a proposal's marker, naming that account, that duty, that published commit and the line's digests;
6. what the run held, again, against the published branch and the state as they are now: `clone` when this clone
   cannot read the published commit, then `parent`, `paths`, `modes`, `files`, `digests`, `task files`, `nothing`,
   then the cutter's `gate` with the deals and the judge's answers of the state; `gate inputs` when the project's
   own files or the state cannot be read for it, and `unforeseen` (with the error's type alone) for anything else;
7. `push`: the push itself (below).

A cut that passes is pushed as **one commit of the publisher's own on the published commit, whose files are the
proposal's** (its tree, so nothing but the tasks file and the backlog changes): the account as its author, under its
GitHub address `<number>+<login>@users.noreply.github.com`, the hive's name as committer, the cut line's instant as
its date, and the tool's words as its message, which end with two lines:

```
Hive-Cut: <the proposal's commit>
Hive-Deal: <the duty's instant>
```

The proposal's own message, author, date or signature never reach the published branch: nothing the account wrote
lands there but the two files the gate passed. That commit is the record of the publication: a commit of the published
branch whose one parent is the cut's published commit and whose message is that one is that cut, published, and a
second run says so and pushes nothing. The same line always makes the same commit (no signature, no clock), whichever
machine runs it. **A published cut is taken back by a commit that undoes it**: a published branch reset (not
reverted) to the commit the cut was held against, while that cut is still the latest, gets the same commit again at
the next run. The push moves the branch only from the commit the cut was held against to that commit, never over
what moved meanwhile (git's lease, as a run's push does), and with no terminal question: a push declined by the
repository, or that did not land, is `push`, and nothing is pushed. The publisher prints `PUBLISHED`, `NOTHING` or
`REFUSED` and the check's name, then commits, instants and the account's number: never a path, a token or a word
the account wrote. Like the volunteer's commands, it keeps what git writes on its error output to itself (of a push
that did not land, it says the status git gives the branch, made plain), and what it did not foresee ends in one line
that gives the error's type and where.

**What an account can do with it, and what it is charged for.** An account may answer `nothing` at any time of its
duty, at no cost: the next cut duty then keeps to `trusted.cut_hours`, so a trusted account can hold the project's
cuts off that long, and no longer than until the next duty, which may be another's. And the gate the plan runs is the
gate at the plan's instant: what moved after the account ran `cut-check` (the tip of the branch the hive writes, the
judge's answers, a task dealt in the same plan, its own deals included) can make the plan refuse what `cut-check`
passed, and that refusal (`gate`) costs the account the first wait, as any other.

**Giving a duty back.** A release is a commit at the same branch, with one of the codes of a release ("How tasks
are dealt": `out_of_reach`, `cannot_run`):

```
Hive-Action: release
Hive-Member: carol
Hive-Role: cut
Hive-Deal: 2026-11-24T10:00:03Z
Hive-Because: cannot_run
```

It ends the duty of that account, role and instant at the next run (`released`), whatever time is left, and is read
once. A release the run reads while the duty is live counts, whenever the run comes, as a deal's release does (the
tool gives nothing back once the duty's time is up); a duty whose role the file took away ends at no cost first. A
release of another duty, of a duty that is over, or of someone else's, ends nothing.

**What a duty costs.** A duty that ran out costs its account the wait after a deal held for nothing: `backoff_hours`,
doubled for each duty of the account's that ran out in a row, seven days at most. A cut that stands, or nothing to
cut, clears every wait, as an acceptance clears a member's. One given back, or whose proposal was refused as
`malformed` or by the `gate`, costs the first wait, each time, never doubled; one ended at no cost (the role taken
away, a pause, a day without a run or a read of its fork, a proposal gone `stale` or `unchecked`) costs nothing. That wait is the
account's duty standing, read from the duty lines alone. **A duty never reaches a member's standing, the day's limit, the cover or the tally**: none of them reads a
duty line, and a duty is no deal. A trusted account that is also a member is dealt tasks as anyone is.

## What holds over time

The hive runs every hour, for ever, among accounts that may take tasks and leave them, push what fails, what never
ends or what the project's repository declines, and on machines that sometimes break. Five rules are written, and
tested over schedules drawn at random (`tools/hive/test_schedule.py`):

1. **An honest worker that asks is dealt a task, and its correct candidate, pushed in time, is integrated in its
   member's name**, whatever others push, take away or break.
2. **Only the member the hive dealt a task to has credit for it.**
3. **Every run of the judge on a candidate leaves a line in the ledger**, and nobody is refused or made to wait
   for the hive's own faults.
4. **The project's branch only moves forward**, each task is integrated once, a task is never dealt while its
   previous deal is live, and an account never holds two live deals.
5. **Nobody stalls the work for long**: neither one or two accounts, nor one fault on the hive's side.

What makes them hold:

- **One holder per task.** There is no order to decide among members, no instant to trust, and nothing a member
  can push that changes what another member's candidate is worth.
- **A task is held for a bounded time.** Three hours and one of grace, by one account, which then waits: two
  hours if the judge examined and refused its candidate (nothing if all the candidate lacked was a proof),
  twice as long each time if it held the task for nothing.
  A candidate that waits to be judged keeps its task: that is the hive's delay, not the member's.
- **Not being answered never keeps a place.** Each run the hive spends on a candidate without an answer is
  recorded as a *mark*: the judge failed on it (`judge`), the project's repository declined it (`push`), the hive
  could not derive it (`hive`), or the judging stopped while it was on it (`none`: the judging step says which
  commit it starts on before it starts). A candidate the judging never reached is not marked: nobody pays for the
  time the others used up. A marked candidate goes after the unmarked ones; those the project declined go last,
  and nothing more is judged in the run once one of them is accepted.
- **Marks end in an answer**, and are counted for the deal, not for the commit. Three marks that are the
  candidate's own doing, and it is refused, with its cost: the judge failed on it while its machine works, the
  hive could not derive it while it can still do all of that for the project's own tip (a failure that is only
  slowness is never counted), or the project's repository declined it right after another push of the same run
  landed. Six runs without an answer for any other cause (the judging stopped
  while on it; the project declines every push), and the deal is closed at no cost to its member. Taking a
  candidate away before its third failure and putting another in its place starts nothing afresh. And a candidate
  that git itself cannot read as it is written is refused at once.
- **The judging has a time allowed** (four hours by default): no judgement is started that could end after it, and
  the answers are saved as they come, so that a judging job that is stopped leaves what it had.
- **The hive's own faults cost members nothing.** A fork GitHub would not let the hive read decides nothing. The
  judge's machine down, or the hive unable to derive even the project's own tip, marks nobody. What the judge ran
  on and the hive could not use is judged again.
- **The state survives a run that stops**: its files are written whole or not at all, one cut short is read as
  empty, a ledger line cut short is removed before anything is added, and a line of one run is recorded once
  however often a job is run again.

What this costs, plainly: a worker waits for the hive's next run before its first task; nobody chooses their task
(only the hardest tier they take, and a part of the project they would rather have, which the hive follows when
its rules lose nothing by it); an account that asks and never comes back holds one task for four hours, and
with it the tasks that share a file with that one.

## How the hive writes

- **It writes a branch of its own, never the one a project publishes.** A project's file names both: `branch`,
  where the hive integrates what its judge accepted, and `published`, the branch people take the project from. The
  hive pushes to the first and to no other; a file that names no published branch, or one branch for both, stops
  every step of the hive and every command of a worker. Each is written as a branch's own name, the one way: what
  git takes as a branch's name, with no `refs/` or `heads/` in front, not `HEAD` nor a name that ends in `_HEAD`,
  and not a commit's full id. The hive's own branch reaches git only inside a full reference (`refs/heads/<name>`
  on a repository, `refs/remotes/…/<name>` in a clone), never as a bare word; the published one reaches no git
  command of a run's: the hive only compares it (the project's publisher pushes to it, inside a full reference). What
  is on the hive's branch was accepted by a judge and read by nobody: each of its commits says so. The published
  branch moves when a maintainer, having read what accumulated, moves it, or, for the tasks file and the backlog
  alone, when the project's publisher pushes a cut that stands ("Publishing a cut"); a release, an offer to another project, anything that leaves the repository, is a
  maintainer's act. The judge's scan of a candidate's source is a filter, not a review of what a change does.
  What a maintainer commits on the published branch (a fix, a revert) the maintainer also brings to the hive's
  branch: the hive works on its own branch's tip and takes nothing from the other by itself. The file's two names
  are the project's settings' word: the host's own rule, which keeps the run's token off the published branch, is what holds
  if that word is wrong (docs/hosting.md, "The repository's settings": its rulesets).
- **It promises, then pushes.** Before each push the write job records an *intent* in the ledger and saves the
  state. If a run pushed and then could not record, or could not tell whether its push landed, the next run finds
  the promise, looks for the promised commit in the project's history, and completes the ledger. Nothing but the
  hive's own promise is believed: no field of a commit on the project's branch is. That a promised push *landed*
  is recorded as soon as a run sees the commit in the project's history; that it was *not seen there* is recorded
  only by a write job, against the project's tip as it is then. And a push given up on is still looked for during a
  week: one that lands after all is recorded, and its task is done once.
- **The push can only add to the judged tip.** The hive checks that what it pushes descends from the tip that was
  judged, and pushes on the condition that the branch is still at that tip. A branch that a maintainer moved
  meanwhile, to take a commit back for instance, is left as they put it.
- **Accepted commits are pushed one by one**, and what happened is recorded up to the first push that did not
  land; what the judge ran on after it is recorded as `unused` and judged again, at no cost to its member. A
  commit that the project's repository itself declines is a failure of its candidate's, and the run ends in error
  so that maintainers see it. It counts towards a refusal only when another push of the same run had just landed:
  otherwise the hive's own right to push is as likely the cause (a rule added, a token that lost its rights), and
  the candidate only loses its place.
- **A deal's time starts when it is published**, not when it was planned: the `record` job writes it, with the
  feed, before anything is judged. In the same way, a verdict is dated when the write job records it: a wait
  counts from the moment its member can see the answer, however long the judging took.
- A job run twice records nothing twice.

Strings that come from a fork (ref names, commit messages, paths) never reach a shell, a workflow expression or
the ledger.

## The ledger and the feed

On the project's own branch `hive-state`, at its root. Only the project's run writes it, its two jobs that write (`record`,
`apply`), by pushes that only add to it; a push that finds the branch moved takes what was saved there meanwhile (a
file beside the hive's) and pushes again, a bounded number of times. Each job reads it as it stands when the job starts.
The hive's files there:

- `ledger.jsonl`: append-only, one JSON object per line: `deal`, `expired`, `verdict`, `error` (a mark, with its
  kind), `intent` and `void` (a promise, and a promise whose push never landed), `unused`, `ruling` (a
  guardian's ruling that did not end in an integration: "Guardians"), and `duty` and `duty-end` (a trusted
  account's duty and its end: "Trusted accounts and their duties"); each carries the key of
  its run. **It holds no text a fork wrote**: logins, the numeric ids of the account and of its fork, task ids of
  the project, commit ids, instants, reason codes, a model identifier the project lists, whole numbers under the
  hive's own keys, a file of the project as its tasks name it, the judge's figures the project lists, and the
  bounds of a ruling under the project's own names for the figures. **A
  login is written beside a deal and beside an accepted candidate, which is a credit; a refusal, a run without an
  answer and an expired deal carry the account's number alone.** That is discretion, not secrecy: the deal names its
  member, and the candidate sits in a public fork. A guardian's login is written beside each of its rulings,
  whatever the answer: a guardian's decisions are public and named.

  A `verdict` line carries the task, the deal it answers, the candidate's commit id, the account's number and its
  fork's, the result, whether the judge examined the candidate (`judged`) and the model the worker declared. An
  accepted one adds its member's login, the integrated commit, what the hive counted of the change (`figures`) and
  the judge's figures the project lists (`report`). A refused one adds its reason code and `detail` (whole numbers
  under the hive's own keys), and no login on the line. **A candidate refused for a figure (`goal_not_met`,
  `requirement_not_met`, `not_proven`: the judge ran, the candidate is correct, a figure or a proof is short) keeps the same `report` as an
  accepted one**, the same numbers bounded the same way: how far it fell short is what its member needs to know,
  and whoever is dealt the task next. `judge_refused` and every refusal before the judge carry none. A refusal's
  line written before this rule has no `report`; it stays valid, and whatever reads the ledger takes both. **A
  probe's answer** ("How a candidate is judged and integrated") is such a line, refused for `goal_not_met`, with one
  number more: `probe`, how many answers the probe asks, from 1 to 5. A hive at an older commit reads it as the
  refusal it also is.

  **A verdict names the commit of the hive that judged it**, `hive`: the commit of `Bee-ruche/hive` the project's
  caller pins, which every job of the run checks is on the hive's main and runs ([hosting.md](hosting.md), "What
  carries it"). The job that writes is given it (`hive.py apply --hive-commit`): whoever reads a figure can tell
  which judge gave it, and where the judge changed. The promise of a push (`intent`) carries it too, and the verdict
  a later run builds from a promise keeps the promise's: the run that judged, not the one that found the push
  landed. A line without it (written before this rule, or by a job not given the commit) stays valid, and
  whatever reads the ledger takes both.

  A commit has one verdict as a candidate. One that a guardian admitted and the hive then accepted has a second,
  which names the ruling (`ruling`, `guardian_id`, `guardian`, `waived`: "Guardians") and is recorded once per
  ruling: the two lines stand side by side, the refusal as it was written and the acceptance that followed.

  A `deal` line carries the task, its member's login, the account's number and its fork's, when the deal starts
  and until when. When the member's ask named a part of the project it adds `prefer`: `{"file": <the part, as the
  project's tasks write it>, "kept": true}`, or `{"file": …, "kept": false, "because": <one of the four reasons of "How
  tasks are dealt">}`. An ask that named no part of the project's leaves no `prefer` at all: a deal's line written
  before this rule, or for such an ask, stays valid, and whatever reads the ledger takes both. The jobs that write
  copy nothing of a preference from the plan: before they write or push anything, they hold that it has that shape
  and names a file of the project as its tasks write it, and they write the project's own string.

  An `expired` line carries the task, the deal it ends, the account's number and `fault` (true when the deal ended
  at no cost to its member: the fork could not be read for a day, or the project closed the task). One whose member
  gave the deal back adds `released`, the release's code (`out_of_reach` or `cannot_run`), and `release`, the
  release's commit id, which anyone can find in the member's public fork: a hive at an older commit reads the line as
  the expiry it also is.

  A `duty` line carries the role, its account's login, the account's number and its fork's, when the duty starts
  and until when, `settings` (the commit of the published branch its plan read the settings at, from which a later
  plan reads a pause), and `area`, null: no part of the project is named yet. A `duty-end` line carries the role,
  the account's number, the duty's instant (`duty`), `outcome` (`expired`, `released`, `cut`, `nothing` or
  `refused`) and `fault` (true when it ended at no cost to its account: the role taken away, a pause, a day without
  a run or a read, a proposal gone stale or unchecked); one given back adds `because`, the release's code, and `release`, its
  commit id; one ended on its proposal adds `proposal`, the proposal's commit id, `published`, the commit it was
  cut against, and `repo_id`, the number of the fork it was read in, and then `digests` (`tasks`, and `backlog` where it changes it: SHA-256) for `cut` and `nothing`, or
  `reason` (`stale`, `unchecked`, `malformed` or `gate`) for `refused`. A duty is recorded once per role and run, its end once per
  duty. No reader of deals, verdicts or expiries reads either line.
- `feed.json`: the project's tasks with their status (`open`, `dealt`, `done`, `closed`), their tier, the number
  of judged refusals and the task's context (a probe adds `kind`, how many answers it asks and how many it has, and
  its answers are no refusals there); and, **under a hash of each login** that a worker computes for its
  own, the task a member holds, since when, until when and whether its candidate was seen (`deals`), and until
  when a member is dealt nothing (`wait`). It holds nothing a contributor wrote. The hash keeps sentences a login
  could spell out of the feed; it hides nobody, since the owners of forks are public. `members` says where the
  project's trusted base stands ("How tasks are dealt"): `active` (how many members are active now), `active_days`
  (for how many days an accepted candidate keeps its member active), `cover` (how many the project's guardians
  cover; `null` where the project sets no bound), `takes_new` (whether a new member is dealt a task now) and
  `active_marks` (the active members, under the same hash of their logins): whole numbers, a yes or a no, and
  hashes. A member is found there, as in `deals` and `wait`, under the login of the line of its latest deal: one
  that changed its login since is found there again once it is dealt a task under the new one. `releases` lists the
  codes of a release the run reads (a run at an older commit lists none, and a worker's tool then gives nothing
  back). How often a task was given back is not in the feed: a worker reads the judge's word on a task, never
  another member's that it could not do it. `duties` holds, under the same hash, the live duty of each account that
  holds one (its role, since when and until when), and `duty_wait` until when an account that was dealt a duty is
  dealt none: a run at an older commit writes neither, and the tool's `duty` command then asks for none.
- `stats.json`: candidates judged and accepted by declared model, and, for each account with accepted work, how many were accepted (what was refused is added up for a model, not for a member). A probe's answer is counted apart, under `answered` (where there is one), and not under `judged`: accepted over judged stays the share of candidates meant to be accepted that were. The project's page counts the same, and the hive's `health` gives each kind of task its answers apart and an acceptance share that leaves them out.
- `ignored.json`: fork by fork, the branch tips the hive does not read again (no marker, a marker for another
  member, an ask that was used, a submit that is not a candidate, a release once read, a commit shaped like a
  ruling in a fork whose owner the project does not name a guardian, under another account's name, or at another
  branch than its task's ruling branch; a duty marker or a proposal anywhere but at its place, an ask for a duty that
  was used, and a duty's release or a proposal once read). A guardian's ruling at its branch is not listed there: it is read at each
  run until the ledger holds its answer. Only what is still at a tip of that fork is kept: what one fork pushes
  never costs another its entries.
- `accounts.json`: when each account that owns a fork was created, asked of GitHub once.
- `tip.json`, in a project whose judge answers about the tip (the reference kind): for each planned task « correct »
  of the backlog, the judge's latest answer when the tip itself was judged as a candidate for it (`failing`,
  `passing` or `unknown`), the commit it judged, the SHA-256 of the task's line, the instant, how many runs in a row
  gave it, the key of the last, and digests of what judged. Written by the write job alone, in a run whose plan holds
  no candidate, read by the cutter ([cutter.md](cutter.md), "The proof at the tip"); a run pinned to an older commit of
  the hive neither writes nor reads it.

A task the judge keeps refusing asks for a stronger worker: the feed gives a `hint` that rises by one for every
three different members refused, among those the judge has accepted something from. It is a hint for people;
tasks are dealt by their own tier. A probe's answers raise no hint.

**What a worker believes.** The tool it runs is the protocol's own (its copy of `Bee-ruche/hive`, taken afresh at
each run). A task's text and files, the project's branch and its check come from the project's settings and tasks,
which each command reads on the project's default branch, at the commit the project's own address announces during
the command, as bytes the tool hashes itself: never from the feed, and never from the fork or its clone, whatever
they hold under those names. The state (a clone of the project's branch `hive-state`, taken afresh at each run) is
believed for what the hive did
for this member and nothing else: the task it dealt it and until when, its wait, whether its candidate was seen,
whether its ask was used (is the ask's commit id in `ignored.json`: an ask the hive still reads is not asked
again, and one that has waited six hours is reported to the volunteer), which codes of a release the run reads,
whether its account is one of the
project's active members where the feed says the project's trusted base has the members it covers (the worker
then waits, and asks nothing), and whole numbers (how often a task was refused, how many members the base
covers). No text of the state is printed by the worker's commands: every line they print is one of a fixed list
(`hive.py`'s own documentation), followed by values the tool checked. The fork's clone is not trusted either, once
project code ran in it: each command first checks that its git settings are the ones a clone has (anything else
stops the command: a filter, a hook, a credential helper, another address to push to, an included file, a reference
that is neither a branch, a tag nor the stash), and starts the task, commits and pushes itself, so that the worker's
assistant runs no git command of its own in the fork's clone. What a command decides on is never a value the clone
holds: the fork's https address is worked out from the login and the project's repository, a task starts on the commit the
project's own address announces, and a candidate is pushed only once
the tool has shown, from bytes it hashed itself, that it starts from the project's history and changes only the
task's files. Nor does a task start on what git made of the clone: git does not hash an object again when it reads
one, and its index is a file of the clone, so `start` shows by its own reading that each file of the work tree
hashes to the id the project's tip lists, and that nothing else is there. A file the project's own rules convert
(line ends, an encoding) is compared, byte for byte, with what a checkout writes for the hashed file; a file that
is run or obeyed on the host (the sandbox's launcher, the CI's files, an agent's settings and instructions) is
taken only as the tip's very bytes. Otherwise the command stops, and nothing is run from the clone, not even its
sandbox. A worker must run at least every two hours to do the tasks it asks for: a deal lasts three
hours and a worker starts on one only if an hour of it is left.

Each fork is read with one listing and one fetch, both limited in time. When the time allowed to read all the
forks runs out, what is left waits for the next run; the forks are read in an order drawn anew each hour from the
hour and the fork's own number, which adding forks to the list does not shift.

## What a worker's machine needs

A project's settings may say what a worker's machine needs, in a block `needs` of `hive/project.json` (not a
task's `needs`, the tasks done first, which the tasks file gives): a list of ten entries at most, each with its
`kind` and the fields of that kind, no more and no fewer ([`hive/settings.json`](../hive/settings.json) gives each
kind's fields and bounds):

- `program`: `name`, a bare file name meaning `/usr/bin/<name>` and nothing else, never a shell or a program
  that changes who runs, mounts, stops the machine or erases (`sh`, `bash`, `dash`, `zsh`, `su`, `sudo`, `ssh`,
  `mount`, `umount`, `reboot`, `shutdown`, `systemctl`, `dd`, `rm`); `package`, the system's package that provides
  it, only ever shown: lower-case letters and digits, with `+`, `.` and `-` each alone between two, so that it reads
  as no pattern of apt's; `version` (optional), a dotted prefix of the version the program gives (`1.75`
  takes 1.75.0 and 1.75.2, never 1.7.5).
- `file` and `document`: `name` (one folder for both: each name once), `why`, `url`, `sha256`, `bytes` (512 MiB at
  most for a file, 32 MiB for a document, 2 GiB for all of them together) and `licence`. `why` is one line of 80
  characters at most; `licence` a name as SPDX gives one (`MIT`, `CC-BY-4.0`, `GPL-2.0+`: letters, digits, `.`,
  `+`, `-`, brackets and spaces, 64 at most).
- `resources`, once at most: `processors`, `memory_mb`, `disk_mb` (free on the clone's disk) and `architectures`
  (`x86_64`, `aarch64`), one at least.

**What is never allowed**, and a file that names it does not load, at any step of the hive or any command of a
worker: a command written by the project (no field of any kind is run: a program is only asked `--version`, by the
tool); an address other than `https://<a public name>/<path>` (no user, port, query or fragment, no machine's
number nor one written into a name, no `localhost`, no name whose last label is one of a machine's own network
or kept for tests (`local`, `internal`, `localdomain`, `lan`, `home`, `corp`, `test`, `invalid`, `example`,
`arpa`), no `..`, and no part of 32 characters or more that looks like a key or a token, but a
commit's id or a fingerprint); a file or a document without its fingerprint and its size; a key, a token, an account
to create, or a service to reach while working (there is no field for any of them, and a host that asks for an account
is refused at the fetch).

**The soft check.** `next` (before it says `ASK`, and after a task's data), `ready` (before it asks) and `start`
(before it changes the clone) check the needs on the machine, and say what is missing:

- a program must be a file of the system's (`/usr/bin/<name>` leads, once every link is followed, to a plain file
  under `/usr/`, owned by root, that nobody else may write), and answer `--version` with exit 0 and, if the entry
  names one, a version that begins with it. It is run by the worker's tool, as the worker's own user and wherever
  the tool runs (inside the bee's sandbox when the worker runs there): the tool starts no sandbox of its own for it,
  and bounds it as it bounds git, in an empty folder of its own, with `PATH`, `LANG` and `LC_ALL` alone, nothing on
  its input, in a session of its own ended whole, for ten seconds at most, 64 KiB of its output read. A program the
  machine lacks is met all the same when the project's commit holds `bee/sandbox/Dockerfile` and the system's docker
  answers (`NEEDS-DOCKER`: the task is done in the sandbox's Docker form). The Dockerfile itself is not read: a
  project that brings one passes every program check that way, whatever its image holds;
- resources are read from the system alone (processors and memory, with the control group's bounds; free room on the
  clone's disk; `uname`'s architecture);
- **the digest** covers every need: the SHA-256, all 64 hexadecimal digits, of every entry as the loader holds it (a
  program's name, package and version; the resources; a file's or a document's kind, name, why, url, sha256, bytes
  and licence), in the file's order, as canonical JSON. The user accepts it with `--needs-accepted <digest>`; that
  yes lets the tool fetch the files and documents, and the guide install the packages the `NEEDS-MISSING` lines
  name (below). Any change of what the user was shown (a package, a version, a kind, a reason, a file, a host, a
  licence) is another digest: a worker given the old one stops (`NEEDS-UNACCEPTED`) until its user has read the
  change, and so does a worker given none when the project names files or documents;
- files and documents are fetched only once the needs are accepted. They are fetched over https, by the tool itself
  (`User-Agent: bee-hive-needs/1`, nothing of the user's; a redirection followed only to https on a public host,
  five at most; before each connection, its own or a redirection's, the name is resolved and every address it gives
  must be a global one, in IPv6 only in `2000::/3`, as `tools/hive/egress.py` holds them, or the host is refused;
  the tool connects to that address, with the name given to TLS for the certificate's check, and through no proxy;
  all the fetches of one check take 30 minutes at most together, each 15 minutes at most), into
  `~/.hive/needs/<owner>/<name>/` in the home the system's list of users gives (never `$HOME`):
  outside the clone, a folder of the tool's own that holds the declared files alone, each mode 0444, held to its size
  and SHA-256 again at every check. A file that does not match is said to be of another size or fingerprint, and
  nothing more of what was received is shown. Nothing there is extracted, opened or run on the machine.

What is missing is said in `NEEDS-MISSING` lines (`NEEDS-MET` when everything holds): `next` then says `CANNOT-ASK`
in place of `ASK`, `ready` makes no ask, and `start` changes nothing, each at no cost. `--despite-needs`, from the
user's own words alone, prints the lines and goes on. A deal whose needs show up unmet after the ask (an entry added
since, a file that vanished, a fetch that fails) is given back as `cannot_run`. The tool installs nothing; the guide
installs packages as follows.

An install needs one of two sentences of the owner's prompt: "I accept the project's needs <digest>.", and then only
when no `NEEDS-UNACCEPTED` line was printed, for exactly the packages the `NEEDS-MISSING` lines name; or "This
machine may install, from the system's archive, the packages <list> before anything of the project runs.", for the
packages that are both in that list and named by a `NEEDS-MISSING` line. Without either, nothing is installed. Each
package goes by the name the line gives: first `apt-cache policy <package>` for each, which must show a candidate
(`Candidate:` followed by a version, not `(none)`), or nothing is installed and the owner is told; then
`sudo apt-get install -y --no-install-recommends --no-remove -- <packages>`: with `--no-remove`, apt stops rather
than remove any package. Only from the archive the machine already has, before anything of the project runs: no new
source, no PPA, no address, no pip, npm, cargo or `curl … | sh`.

`hive.py needs --project <owner/name>` prints the needs as the project's own address gives them, with their digest
and the packages it covers, for the user to read before the yes: it reads the settings at the default branch's
commit from `raw.githubusercontent.com`, needs no clone and no login, and checks and fetches nothing.

**What the sandbox sees.** The project's own launcher (`bee/sandbox/sans-docker.sh`) shows the needs' folder to
project code at `/needs`, read-only, and nothing else of the home ([hosting.md](hosting.md), "What a project holds",
gives its lines); `hive.py doctor` notes a launcher that does not.

**No judge reads the needs.** The judge's data is the relay manifest's own (fetched at the image step, held to its
fingerprint), the same for every candidate; `/needs` exists in a worker's sandbox alone, and project code the judge
runs must not depend on it. The doctor notes a relay project whose data no file of the needs carries: its workers
cannot measure on the judge's data.

## A project's files

- `hive/project.json`, in the project's own repository, on the branch it publishes: the repository (`repo`, the one
  that holds the file), the hive's own branch in it (`branch`) and the
  branch the project publishes (`published`, which no run of the hive writes: the project's publisher pushes a cut
  there with the project's own account), the protected paths, the limits,
  the member rules (`min_account_age_days`, `deals_per_day`, `banned`, `only`, `preferences`: whether the
  part of the project an ask prefers is followed, true unless the file says false; and `per_guardian` and
  `active_days`: how many active members one guardian covers, a whole number of 1 or more, and for how many days
  after an accepted candidate a member stays active, 30 unless the file says otherwise; a file with no
  `per_guardian` sets no bound,
  and one that sets it without naming a guardian does not load), how long a deal lasts
  (`deal_hours`, `grace_hours`) and the first wait (`backoff_hours`: an hour at least, or none at all, `0`, for a
  project whose file names one account alone: a file that names a second one with that setting does not load),
  the models it keeps statistics for, the
  kind of its judge (`judge.kind`), the judge's options, the figures of the judge it keeps (`judge.metrics`) and
  requires (`judge.require`), the
  judge's proofs it takes (`judge.confirm`: figures it keeps, named `sure_<measure>`; every goal on a figure holds
  one of them, with a minimum of 1 or more, and a project that lists none has goals of the kind « correct » only;
  what the project requires of every candidate, `judge.require`, stays as the project wrote it), its guardians if
  it names any (`guardians`: `accounts`, their GitHub account numbers, and `waive`, the figures they may waive,
  each with the most a ruling may let it reach; a file without it takes no ruling, and one that names a guardian it also bans by number does not load: "Guardians"),
  the accounts it trusts with a role and the pace of their duties (`trusted`: `accounts`, each an account's number
  and its roles, `cut_hours` and `window_days`) and how long a duty lasts (`duty_hours`: "Trusted accounts and their
  duties"), the project's pause
  (`"paused": true`), and what its cutter keeps to (`cutter`: the least a goal on a figure may ask, the most task
  lines one cut changes, how many open tasks it aims at, the longest context of a task), which no run reads but for
  how many open tasks it aims at, below which a cut duty is dealt sooner ([cutter.md](cutter.md), "The gate"). A run reads this file, and the tasks, at the commit of the published branch its plan names,
  and a change acts from the run that plans after it ([hosting.md](hosting.md), "What a run reads, and when").

  **Every setting of that file is described, one by one, in `hive/settings.json`**: its key, its type, whether the
  file must give it or what the hive takes when the file says nothing, the bounds the hive enforces when it loads
  the file, and recommended values for three ways of opening a project (a trial with one account, a pilot by
  invitation, a project open to any account old enough: recommendations, which a project's lead may change within
  the bounds). The list also says what no project's file can change. A test of the hive holds the list to the
  code that reads the file (`TestTheSettingsList`): a setting the code reads and the list does not describe, a
  default or a bound that is not the code's, or a recommended file that does not load, fails it. What a project
  takes from one candidate and what a run spends (`limits`) are whole numbers, from 1 to a most for each that the
  hive's own table sets (`LIMITS_MOST`: what its machine and its workflows carry: one fetch of a fork writes four
  times `history_bytes`, a file is read whole, git is told how many commits to count, the plan's and the judging
  jobs have their own time), and `files` times `file_bytes` is 256 MiB at most: what all of a candidate's files may
  weigh together. A file that says otherwise, that names a setting the hive does not know (at its top, or under
  `limits`, `members`, `judge`, `cutter` or `trusted`: a key mistyped would leave a setting at its default), or that gives one of these
  blocks as anything but settings by name, does not load; `judge.options` are the project's plug-in's own and take
  any name, and `in_service` is a mark that `Bee-ruche/registre`'s own test read, which the hive does not read. The hive's own
  constants bound what a run does besides (the branches it lists of
  one fork, what all the fetches of a run leave, what a plan carries to the other steps). Presets name no guardian:
  what guardians may waive depends on a project's judge, and `members.per_guardian` has recommendations of its own
  for a project that names them.
- `hive/tasks.jsonl`, beside it, read at the same commit: one task per line: `id`, `title`, `files` (exact paths, or a
  folder ending with `/`), and optionally `size`, `tier`, `goal`, `options`, `context`, `closed`, and the links
  that make the project's map: `parent` (the task it was cut from), `needs` (the tasks to be done before it) and
  `kind` (`work`, `probe` or `hunt`), which name other tasks of the file and go round in no cycle, or the file is
  not run ([cutter.md](cutter.md), "The map: links between tasks"). A probe's goal is on a figure, and a probe alone
  may say how many `answers` it asks, a whole number from 1 to 5 ([cutter.md](cutter.md), "Probes"). Tasks are
  written by the project's maintainers or by its cutter ([cutter.md](cutter.md)); they are trusted data.
- Two more files under `hive/`, for the project's cutter: `hive/charter.md`, the architect's charter (the project's
  goal, what counts as progress, its directions), which no run reads, and `hive/backlog.jsonl`, the tasks the
  architect plans, as lines of the tasks file, which the cutter publishes once what they need is done and, for a goal
  « correct », once a run of the judge showed the tip fails them ([cutter.md](cutter.md), "The backlog and the
  charter", "The proof at the tip"). The judging and the write jobs read the backlog at the plan's commit, for that
  question alone; a backlog they cannot read is asked nothing. Like every file under `hive/`, no contribution may
  change them.

## What this version does not do yet

- Deal more often than it judges (a light run of `plan` and `record` between two full runs), so that a worker
  waits minutes, not up to an hour, for its first task.
- Judge in parallel (several candidates at once, then one confirming judgement), needed above a few thousand
  contributions a week.
- Read only the forks that changed since the last run.
- An "invited" mode for outside projects that want accepted work offered on a branch they pull from.
- In a project's needs: a GPU, a version « at least » (a version is a dotted prefix), and an archive unpacked by the
  tool (never: an archive is unpacked, if at all, by project code inside the sandbox).
