# Reference copies

The files under `workflows/` are copied unchanged from `Bee-ruche/registre` at commit 2baa4d2. They sit outside
`.github/`, so they never run here, and every repository and path they name is `Bee-ruche/registre`'s.

- `workflows/hive.yml` and `workflows/hive-cjson.yml`: the hourly runs of the hive's two test projects (miniz and
  cjson), as `Bee-ruche/registre` runs them. They are kept here as the reference the hive's tests read (each job's
  `timeout-minutes`, and the paths each step is given: `tools/hive/test_hive.py`) until the protocol's own reusable
  workflow replaces them.
- `workflows/judge.yml`: the reusable workflow through which a fork's own CI calls the common judge
  (`docs/common-judge.md`). The judge's tests read it here (`TestJudgeWorkflow` in `tools/judge/test_judge.py`).
