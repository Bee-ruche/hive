# The hive

A protocol that lets people point their AI coding agents at one precise project.

A project's lead sets the project up: its file of settings, its tasks and its judge. Volunteers fork the project
and run their own AI agent in their fork. The agent asks for a task, is dealt one that is its alone for three hours
by default, and pushes its work to the volunteer's fork, and nowhere else. An unattended run reads the forks every
hour, has each candidate judged by the project's automated judge (candidates' code runs only in a container without
network), and integrates what the judge accepts as one commit credited to the volunteer, on a branch of the hive's
own from which the project's maintainers publish what they have read. Work from strangers reaches the project only
through that judge. Accounts the project names as trusted (its guardians) may look again at a commit the judge
refused for a figure the project lets them waive: the commit is then judged again in full, and each such decision
is a public line of the project's ledger.

## What this repository holds

- `tools/hive/`: the hive's tool (`hive.py`: the four steps of a run and the volunteer's commands), the project's
  page (`page.py`), how a job of a run takes an earlier job's files (`artifact.py`), and their tests.
- `tools/judge/`: the judges the hive calls, the common judge and the reference judge, with their containers, their
  toy projects and their tests.
- `hive/settings.json`: every setting of a project's file, described, with its bounds and recommended values.
  `hive/projects/` and `hive/tasks/`: the two test projects' files and tasks, which the tool reads there for now.
- `.claude/skills/bee-worker/`: the volunteer worker's guide.
- `docs/`: the protocol's text.
- `examples/workflows/`: copies of the workflows the tests read; they never run here (`examples/README.md`).

## Where things stand

The protocol is in service on two test projects, miniz and cjson, by invitation to the founder's account alone.
Their hourly runs still start from `Bee-ruche/registre`. In a coming step, a project will hold its own settings,
tasks and trusted accounts in its own repository. The hive is not open to the public.

Read [docs/protocol.md](docs/protocol.md) first; [docs/join.md](docs/join.md) says what taking part asks of a
volunteer.
