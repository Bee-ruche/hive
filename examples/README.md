# Examples

- `project/`: what a project holds in its own repository for the hive ([docs/hosting.md](../docs/hosting.md)):
  `hive/project.json` (its settings) and `hive/tasks.jsonl` (its tasks), on its default branch, as the first test
  project, `Bee-ruche/minizBee`, holds them; and `.github/workflows/hive.yml`, the workflow that calls the hive's run
  every hour (its forty zeros stand for the commit of `Bee-ruche/hive`'s main the project runs: nothing runs until a
  project writes one there). The hive's tests load the settings and the tasks (`TestProjectFiles`) and hold the
  workflow (`TestTheRunWorkflow`). These files never run here.
- `page/`: the same caller with one job more, which makes the project's public page again after each run and hands
  it to GitHub Pages ([docs/hosting.md](../docs/hosting.md), "The project's page, after each run"); a project copies
  it in place of the first once its Pages source is GitHub Actions. `TestThePageWorkflow` (tools/hive/test_page.py)
  holds it. It never runs here.
- `reference-project/`: the settings and tasks of the second test project, `Bee-ruche/cjsonRustBee`, whose judge is
  of the second kind ([docs/reference-judge.md](../docs/reference-judge.md)). Its caller would be the first
  project's, with its own default branch.
