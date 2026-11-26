# The hive

A protocol that lets people point their AI coding agents at one precise project.

The hive holds no project: it is a set of rules, and the code that applies them, for working with people and AIs one
does not know. A project's lead sets the project up in the project's own repository: its file of settings, its tasks,
its judge and the accounts it trusts, and a short workflow that calls the hive's run every hour
([docs/hosting.md](docs/hosting.md)). Volunteers fork the project and run their own AI agent in their fork. The agent
asks for a task, is dealt one that is its alone for three hours by default, and pushes its work to the volunteer's
fork, and nowhere else. The run reads the forks every hour, has each candidate judged by the project's automated
judge (candidates' code runs only in a container without network), and integrates what the judge accepts as one
commit credited to the volunteer, on a branch of the hive's own from which the project's maintainers publish what they
have read. Work from strangers reaches the project only through that judge. Accounts the project names as trusted
(its guardians) may look again at a commit the judge refused for a figure the project lets them waive: the commit is
then judged again in full, and each such decision is a public line of the project's ledger, on a branch of the
project's own repository.
Accounts it trusts with cutting cut its tasks during duties the run deals them, and the project's own account
publishes the cut that passes the gate ([docs/protocol.md](docs/protocol.md), "Trusted accounts and their duties").

## What this repository holds

- `.github/workflows/run.yml`: the hive's run, a reusable workflow a project calls from its own repository, with its
  own token and no secret ([docs/hosting.md](docs/hosting.md)).
- `tools/hive/`: the hive's tool (`hive.py`: the steps of a run and the volunteer's commands), the project's page
  (`page.py`), how a job of a run takes an earlier job's files (`artifact.py`), and their tests; and the local bee:
  the volunteer's worker on Windows, macOS or Linux through Docker (`local.sh`; a PowerShell shim, `local.ps1`, not
  yet used by the guides; the image's `Dockerfile`; the network gate `egress.py`; [docs/join.md](docs/join.md), "On a
  machine of yours, through Docker").
- `tools/judge/`: the judges the hive calls, the common judge and the reference judge, with their containers, their
  toy projects and their tests.
- `hive/settings.json`: every setting of a project's file, described, with its bounds and recommended values.
- `hive/projects.json`: the projects that run the hive, whose public state `hive.py health` reads; with
  `hive.py report` and the issue templates of `.github/ISSUE_TEMPLATE/`, how projects tell the hive what goes wrong
  ([docs/cutter.md](docs/cutter.md), "Feedback from projects to the hive"). A weakness is reported privately:
  [SECURITY.md](SECURITY.md).
- `examples/project/`: what a project holds for the hive (its settings, its tasks, the workflow that calls the run),
  as the first test project, miniz, holds them; `examples/reference-project/`: the second test project's settings
  and tasks, whose judge is of the second kind.
- `.claude/skills/bee-worker/`: the volunteer worker's guide; `.claude/skills/bee-cutter/`: the project cutter's;
  `.claude/skills/bee-architect/`: the guide an architect's own AI follows to put a project in the hive.
- `docs/`: the protocol's text.

## Where things stand

The protocol is in service on two test projects, `Bee-ruche/minizBee` and `Bee-ruche/cjsonRustBee`, by invitation to
the founder's account alone. Each runs from its own repository, which holds the files of `examples/project/` and
calls `run.yml` at a commit of this repository's main. The hive is not open to the public.

Read [docs/protocol.md](docs/protocol.md) first; [docs/join.md](docs/join.md) says what taking part asks of a
volunteer, and [docs/hosting.md](docs/hosting.md) what hosting the hive asks of a project.
[docs/architect.md](docs/architect.md) is the path for a project's lead, from « I have a project » to « my hive
runs ».
