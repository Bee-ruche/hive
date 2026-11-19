# Hosting the hive in a project

*How a project's lead sets the hive up in the project's own repository. The run is
[`.github/workflows/run.yml`](../.github/workflows/run.yml) of `Bee-ruche/hive`, a reusable workflow that each project
calls from a short workflow of its own; this document explains it and does not repeat it. The hive holds no project:
a project holds its own settings, tasks, trusted accounts and state, and runs the protocol itself (decided on
19 November 2026, [decisions.md](decisions.md)). The two test projects, miniz and cjson, ran from `Bee-ruche/registre`
until then, with the setup that registry's
[hive-workflow.md](https://github.com/Bee-ruche/registre/blob/2baa4d2/docs/hive-workflow.md) describes (two GitHub Apps,
two environments, a state repository of its own): what follows replaces it, and a project moves to it by holding the
files below. What could not be tried is listed at the end.*

## What a project holds

All of it in the project's own repository. Copies of the first test project's are under
[`examples/project/`](../examples/project/).

1. **Its settings, `hive/project.json`, on the branch it publishes**, which is the repository's default branch: every
   setting is described in [`hive/settings.json`](../hive/settings.json), with its bounds and recommended values.
   Three of them are about this repository: `repo` names it (`owner/name`: a file that names another does not load),
   `published` names its default branch (the run reads the settings there, and a file that names another branch does
   not load), and `tasks` is `hive/tasks.jsonl`, always. `branch` names the branch the hive writes, which is never the
   published one.
2. **Its tasks, `hive/tasks.jsonl`**, beside the settings: one task per line ([protocol.md](protocol.md), "A
   project's files").
3. **The caller, `.github/workflows/hive.yml`**, on the default branch, copied from
   [`examples/project/.github/workflows/hive.yml`](../examples/project/.github/workflows/hive.yml) with two changes:
   the forty zeros replaced by the full id of the commit of `Bee-ruche/hive`'s main that the project runs, and the
   branch its `if` names set to the project's default branch. It asks GitHub to run the hive every hour (below, "GitHub
   starts it when it can"), and runs it by hand too, one run at a time, and gives the run's jobs the project's own token with no more than they ask for.
4. **The branch `hive-state`**, made once by the lead: a branch of its own history (none of the project's), which
   holds the hive's state (`ledger.jsonl`, `feed.json`, `ignored.json`, `accounts.json`, `stats.json`) at its root.
   The run writes it and reads it; it needs it to exist (its jobs check it out): for instance `git switch --orphan
   hive-state`, a README that says what it is, a commit, and `git push origin hive-state`.
5. **The branch the hive writes** (`branch` in the settings, `hive` for the test projects), made once by a maintainer
   from the published branch. What the judge accepted lands there, one commit per task; the maintainers move the
   published branch to what they have read, and bring to the hive's branch what they commit on the published one.
6. What the project's judge needs: its sandbox and its judge's tooling (`bee/`), named in the settings' `protected`
   list ([common-judge.md](common-judge.md), [reference-judge.md](reference-judge.md)). Every project protects
   `hive/**` from contributions besides: no candidate can change the settings, the tasks or the caller.

**Who can change the settings is whoever can write to the published branch.** A change acts at the next run that
plans after it (see "What a run reads, and when").

The repository is public: the run clones it, and lists and fetches its forks, without credentials, and the volunteers'
workers read its settings and its state the same way.

## The repository's settings

No secret, no GitHub App and no environment: the run's only key is the project's own `GITHUB_TOKEN`, which GitHub
makes for each job and whose reach is this repository alone.

- **Settings, Actions, General, "Actions permissions"**: actions and reusable workflows allowed. Where the list is
  limited to some, it must hold the reusable workflow `Bee-ruche/hive/.github/workflows/run.yml` and the three
  actions it uses, at the commits it names: `actions/checkout`, `actions/upload-artifact` and
  `actions/download-artifact`.
- **Settings, Actions, General, "Workflow permissions"**: the run's two jobs that write ask for `contents: write` (and
  `actions: read`) themselves, and the caller grants that to them; the setting is the default given to a workflow
  that asks for nothing, so "Read repository contents and packages permissions" can stay. Where an organization or
  an enterprise forbids its repositories' workflows to write with that token, the run cannot work there. (Not tried:
  see the end. If the first run's recording job is refused the push of `hive-state`, choose "Read and write
  permissions" here, and say so in an issue of `Bee-ruche/hive`.)
- **Same page, "Allow GitHub Actions to create and approve pull requests"**: off. The run opens none.
- **Settings, Rules, Rulesets.** The job's token may write any branch of the repository; what keeps it to the two the
  hive writes is a rule of the host's, and that rule is what holds if the settings' word were wrong:
  - on every branch but the hive's own (`branch`) and `hive-state`: "Restrict creations", "Restrict updates" and
    "Restrict deletions", with the maintainers in the bypass list and GitHub Actions not in it (the published branch
    then moves by the maintainers alone);
  - on the hive's own branch and on `hive-state`: "Block force pushes" and "Restrict deletions". The hive's pushes
    only add to them;
  - on tags: "Restrict creations".
  (The token cannot change a file under `.github/workflows/`: GitHub refuses that to the token of a workflow.)
  What a job's token could do if it leaked, while its job runs, is therefore what those rules let it: write the
  branch `hive-state` (the project's ledger and feed) and the hive's own branch (where accepted work lands, which
  the maintainers read before they publish it); nothing else of the repository. The steps that hold a token that
  writes run no contributor's code, and keep it in the two places git needs it (below).
- **Artifacts**: the run keeps each for three days.

## What each job may do

The protocol ([protocol.md](protocol.md), "Four jobs, each with one risk") gives each job one risk. The workflow keeps
them apart:

| Job | Runs | Its token | May read | May write | Never |
| --- | --- | --- | --- | --- | --- |
| `plan` | `hive.py plan` | reads | the project (its settings at its published branch's tip), its forks (public), the state | nothing: it uploads `plan.json` and the bundle, and publishes the plan's SHA-256 as a job output | runs code from a fork |
| `record` | `hive.py record` | writes | the plan, the project's settings at the plan's commit, the state | the branch `hive-state` | reads a fork; runs anyone's code; unpacks another job's archive |
| `judge` | `hive.py image`, `hive.py judge` | reads | the project, its settings at the plan's commit, the plan and the bundle, the state | nothing: it uploads `verdicts.json` | talks to a fork; has the network while a candidate's code runs |
| `apply` | `hive.py apply` | writes | the plan, the bundle, the verdicts, the project's settings at the plan's commit, the state | the hive's branch and the branch `hive-state` | reads a fork; runs anyone's code; unpacks another job's archive |

What carries it:

1. **The plan's SHA-256 is a job output**, not a file: `record`, `apply` and the judging job's two steps receive it
   from GitHub, not from an artifact a later job could have replaced, and refuse a plan that does not match. The
   bundle's SHA-256 is in the plan.
2. **A job that writes takes the earlier jobs' files itself, by name, before its token is written anywhere**
   (`tools/hive/artifact.py take`): it asks GitHub for the archive, reads from it the members it expects (their exact
   names, up to a size) and writes each under that name in a folder of its own, byte by byte accounted for; an
   archive that holds anything more is refused whole. No general tool unpacks an archive in such a job.
3. **The token is written where git needs it to push, and nowhere else**: in `record` and `apply`, the checkout of
   `hive-state` keeps it (the state is pushed with it); in `apply`, the project's clone gets it as a header for the
   project's address alone, masked in the log. Every other checkout keeps none. `plan` and `judge` are given a token
   that reads, and the judging job hands it to no step after the first.
4. **The hive's code runs at the run's own commit, of `Bee-ruche/hive` and of no other repository.** The first step
   of every job reads which repository and commit the workflow is (`job.workflow_repository`, `job.workflow_sha`: the
   called workflow's own, where the `github` context is the caller's), stops unless they are `Bee-ruche/hive` at a full
   commit that its main holds (GitHub's compare API: « identical » or « behind »), and checks the code out there.
5. **One run at a time**: the caller's concurrency group, never cancelled in progress by a newer run. Two runs that
   overlap are safe by the protocol (the jobs that write check the ledger the plan read) and wasteful. **A run that
   a person cancels pushes nothing**: `apply` runs unless the run was cancelled or `plan` did not succeed, so also
   when `record` or `judge` failed.

A project's guardians ([protocol.md](protocol.md), "Guardians") change nothing in this table, and bring no key: who
is one is a line of the project's settings, which changes as any line of them does.

## What a run reads, and when

- **The settings and the tasks are read at one commit for the whole run.** `plan` asks the project's repository which
  branch it publishes (its default branch) and where it is, reads `hive/project.json` and `hive/tasks.jsonl` at that
  commit, and names the commit in the plan (« settings »). The judging job's clone is the published branch's tip when
  it starts: unless it is the plan's commit, its two steps (`image`, `judge`) do nothing and nothing is judged; the
  judging reads the settings at that commit, and the image is made from that tree. `record` and `apply` ask
  the repository themselves where the published branch is now: if it is no longer at the plan's commit, they write
  nothing, to the state or to the project, and the next run plans on the settings as they are then. A plan that names
  any other commit (an older one, another branch's) is not the hive's. So a change to the settings (a task closed, an
  account banned, the project paused) acts from the run that plans after it, and a run in flight when it lands writes
  nothing more. Any commit to the published branch does the same to the run in flight, whether or not it changes
  `hive/`: maintainers who publish while the hive judges cost that run its answers, which the next run gives again.
- **The judge's image** is made by `hive.py image`, before any candidate's code is on the machine, for the kind of
  judge the settings name, from the project's tree as the judging job cloned it: the plan's commit (above).
- **The state** is the branch `hive-state` as each job checks it out when it starts: `judge` and `apply` start after
  `record` and read what it wrote. A push of the state only adds to the branch; one that finds it moved takes what
  was saved there and pushes again, a bounded number of times, and stops where the same file was written by both
  (two runs of one project, which the group forbids).

## Which version of the hive a project runs

**One commit of `Bee-ruche/hive`'s main, named in the caller**, by its full id. The hive's code, the judges' and the
run's text change for the project when a commit of its own changes that line, and at no other time.

**That line is the project's trust boundary.** Whatever commit it names runs with the project's token, and its own
`run.yml` decides what it checks. The run's first step refuses a commit that `Bee-ruche/hive`'s main does not hold, and
that catches an honest mistake, nothing more:

- **a hostile pin is not caught.** GitHub serves any commit of a repository's network by its id, under that
  repository's name, a fork's commit included: a commit from a fork of `Bee-ruche/hive`, named in the line, runs that
  fork's `run.yml`, which simply leaves the check out;
- **a downgrade is not caught** either: an older commit of main passes the check, with whatever that commit lacked.

So the lead copies the id from the main branch of `Bee-ruche/hive` itself, and a change of that line is reviewed as
code is: a `CODEOWNERS` line that names the project's maintainers for `.github/workflows/hive.yml`, with a ruleset on
the published branch that requires a pull request and the code owners' review, so that no one changes the pin alone.

## Stopping the hive

- **At once**: disable the workflow in the repository's Actions tab ("Hive", "Disable workflow"), and cancel a run in
  flight (its `apply` then does not run). Neither needs a commit.
- **Its work, not its runs**: `"paused": true` in `hive/project.json`, on the published branch. No fork is read,
  nothing is dealt, judged, integrated or written to the state, from the run that plans after it; a run in flight
  when it lands writes nothing more (the published branch moved).

**GitHub stops it by itself, too.** In a public repository, GitHub disables the scheduled workflows after 60 days
without activity in the repository; the run's own pushes may not count as activity, so a lead does not rely on them.
A project notices it on the workflow's page in the Actions tab, which then says that the scheduled workflow is
disabled, and in the feed, whose `generated_at` stops moving (the workers then wait on their asks). It is enabled
again on that same page ("Enable workflow"), or with `gh workflow enable hive.yml`; no commit is needed.

**GitHub starts it when it can.** A schedule is a request, not a promise: GitHub starts scheduled workflows as its
load allows and drops some at busy times. The registry's run, scheduled every hour at minute 17, started eleven
times from 16 to 19 November 2026, about three times a day. A worker then waits that long for its first task, and a
candidate that long for its judgement; the deals lose nothing by it, since a deal expires only at a run that finds
no candidate for it. A lead who wants a run sooner starts it by hand ("Run workflow" on the workflow's page, or
`gh workflow run hive.yml`).

## Notes on the file

- **No expression appears in a `run:` line**: a text never becomes code; values reach a step through its `env:`.
- `plan` prints `plan_sha256=…` on its standard output and its figures on its error output: the first goes to
  `$GITHUB_OUTPUT`.
- The run is held by a test of the file itself (`TestTheRunWorkflow` in `tools/hive/test_hive.py`): the four jobs word
  for word, and the rules they obey beside them (the permissions of each job, no secret, the pins, the protocol's
  commit and repository, the refusal of any other, the order in which a job that writes takes its files and keeps its
  token, the timeouts), and the example caller. The test reads the file with a reader of its own that refuses any
  spelling two readers could read differently: every number and every yes-or-no is written the one way (`true`,
  `false`, plain decimal digits), and no character is outside printable ASCII.
- The page (`tools/hive/page.py`) is not part of the run.
- A lighter run that plans and records more often would deal tasks sooner; it is not designed.

## What could not be tried here

The builder had no network when the run was moved into the projects (19 November 2026): nothing of what follows ran
on GitHub yet.

- **The whole run, called from a project.** The steps ran in the tests, on local repositories, as the workflow runs
  them (`TestTheStepsAsTheWorkflowRunsThem`, `TestTheProjectHoldsItsSettingsAndItsState`), and the protocol's step of
  each job ran with bash and a stand-in for `gh` (`TestTheRunWorkflow`).
- **`job.workflow_repository` and `job.workflow_sha` in a called workflow.** The registry's reusable judge
  ([judge.yml](https://github.com/Bee-ruche/registre/blob/2baa4d2/.github/workflows/judge.yml)) has read them since its
  second version, with the same refusal, and the forks' CI that called it at `judge-v4` produced verdicts: that is the
  evidence that GitHub gives them. Should a runner give them empty, every job stops on its first step and nothing
  runs.
- **Whether a workflow's explicit `contents: write` is granted under the repository's restricted default** ("Workflow
  permissions", above), and whether an organization's policy changes that.
- **That the token of a run started by `schedule` pushes `hive-state` and the hive's branch under the rulesets above**,
  and is refused elsewhere.
- What the registry's runs met for real still holds for the steps, which did not change: `artifact.py` on GitHub's own
  archives, the listing of forks with a read-only token, the judge's image made from a clone of the project, a push the
  project's repository declined (the registry's
  [hive-workflow.md](https://github.com/Bee-ruche/registre/blob/2baa4d2/docs/hive-workflow.md), "What could not be tried
  here").
