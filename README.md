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

## What this repository holds

- `.github/workflows/run.yml`: the hive's run, a reusable workflow a project calls from its own repository, with its
  own token and no secret ([docs/hosting.md](docs/hosting.md)).
- `tools/hive/`: the hive's tool (`hive.py`: the steps of a run and the volunteer's commands), the project's page
  (`page.py`), how a job of a run takes an earlier job's files (`artifact.py`), and their tests.
- `tools/judge/`: the judges the hive calls, the common judge and the reference judge, with their containers, their
  toy projects and their tests.
- `hive/settings.json`: every setting of a project's file, described, with its bounds and recommended values.
- `examples/project/`: what a project holds for the hive (its settings, its tasks, the workflow that calls the run),
  as the first test project, miniz, holds them; `examples/reference-project/`: the second test project's settings
  and tasks, whose judge is of the second kind.
- `.claude/skills/bee-worker/`: the volunteer worker's guide.
- `docs/`: the protocol's text.

## Where things stand

The protocol is in service on two test projects, miniz and cjson, by invitation to the founder's account alone.
Their hourly runs still start from `Bee-ruche/registre`, until each project's repository holds the files of
`examples/project/` and calls `run.yml`. The hive is not open to the public.

Read [docs/protocol.md](docs/protocol.md) first; [docs/join.md](docs/join.md) says what taking part asks of a
volunteer, and [docs/hosting.md](docs/hosting.md) what hosting the hive asks of a project.
