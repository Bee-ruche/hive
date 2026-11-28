# Putting your project in the hive

*For the architect: the person who leads a project and wants volunteers' AI agents to work on it, with an automated
judge deciding what is integrated. This page is the path from « I have a project » to « my hive runs », in order. Your
own AI can walk it with you: its guide is [`.claude/skills/bee-architect/`](../.claude/skills/bee-architect/SKILL.md).
What a project holds is in [hosting.md](hosting.md); this page does not repeat it.*

**The hive is in its pilot.** Its pilot projects run with the founder's account alone, and its review, which every
invitation waits for, is not finished ([join.md](join.md)). You can set a project up and run it with your own account
as its only volunteer; inviting other people, and opening a project to any account, wait for the founder's word.

## Is the hive the right tool for this?

The hive pays when the work can be cut into many pieces, each a task a machine judges alone: volunteers' agents take
them side by side, and the judge decides each without you. What it costs you comes first, before any task: a judge,
its files, a measure, the repository's settings, and your reading of what it accepts. So, before section 1:

- **A small change.** One or two files that you, or your own assistant, can change in an hour, with no measure to
  climb and nothing to explore: the hive would likely cost more than the work. Your assistant says so and asks
  whether you want the hive anyway; you decide. One or two files with a figure to lower (one hot file, a
  compressor) can be what probes pay for.
- **No judge can be written.** Nothing to measure, no reference to match, no test the project fails today: not yet a
  hive project. Write the judge first, or the tests it will hold the work to. The judge is the specification: a task
  can ask only what it checks (section 1).
- **Several parts that need different judges** (a library and its application, two formats, a server and its
  client): one project per part, each its own repository with its own `hive/project.json` and its own judge. A
  project has one judge, and each part needs the one that fits it. Independent files one judge decides stay one
  project: the cutter spreads tasks over files.
- **An open goal**, where nobody knows yet what will help, is fine: the cutter cuts probes, one named thing to try
  each, as long as each answer is a figure the judge measures. So a `common` or `relay` judge (a `reference` judge
  measures nothing), a floor for that figure (`cutter.floors`), and first tasks that are ordinary work tasks: probes
  go only to members with an accepted task (section 3).
- **Many pieces, each judged by a machine**: go on.

## With your own AI

On a machine of yours, start your assistant in a folder that holds no clone of your project, neither inside nor
above it (an assistant loads the agent files of the folder it starts in before it reads you), and give it one line:

> Help me put <owner/project> in the hive: take https://github.com/Bee-ruche/hive afresh into ~/.hive/architect and
> follow its .claude/skills/bee-architect/SKILL.md. The clone is at <path>.

It asks, reads, writes and checks; you decide each choice, and you apply what is set on GitHub's site yourself. It
runs nothing of your project outside a container, writes no secret anywhere, invites and writes to no one, and stops
when something refuses.

Your project already runs in the hive? Give it this line instead (section 10):

> Tell me where <owner/project> stands in the hive: take https://github.com/Bee-ruche/hive afresh into ~/.hive/architect
> and follow section 10 of its .claude/skills/bee-architect/SKILL.md. The clone is at <path>.

## 1. Can a machine judge your progress?

Three questions first:

1. **What counts as progress?** One sentence a stranger could test: faster with the same outputs; the same answers
   as an original; fewer bytes for this data; these tests pass.
2. **How can a machine check it?** Without a person: outputs compared byte for byte, a figure measured beside the
   project's own, a total counted exactly.
3. **Do you have the right to study or change the target, and to publish it?** The repository is public: the hive's
   run reads it with no account.

If nothing a machine can check exists, the hive cannot take the project as it is: its judge would have to be a
person. Take a part a machine can check, or write the tests first: tests the project fails today are the
`reference` kind's route (section 3).

## 2. A judge

| Kind | A candidate is right when | Progress is | Doc |
| --- | --- | --- | --- |
| `common` | its outputs are the project's own, byte for byte | figures measured beside the project's (speed, memory, instructions), with their proof | [common-judge.md](common-judge.md) |
| `reference` | the unit its task names answers exactly as a reference does | units that answer right | [reference-judge.md](reference-judge.md) |
| `relay` | run twice, the second run with the first's message alone, it gives the data back | an exact total: the message's bytes plus the program's | [relay-judge.md](relay-judge.md) |

A reference given as a published program needs its units built as WebAssembly, or a candidate could call the
original. Every kind mounts memory file systems for its containers, as root or through `sudo` without a password
(as GitHub's default hosted runners allow), and the relay judge's gate and the common judge's instruction analysis are for
x86-64. When none of the three fits (a tolerance, a score, a proof assistant, the network, particular hardware), the
project needs a new kind of judge: that is the hive's own code, built on its founder's decision. Your AI can write the
proposal with you.

## 3. An open goal

Make it checkable before anything is cut: one measured figure, a reference to match, a total to lower, or tests the
project fails today (the `reference` kind's route: the common judge compares a candidate with the project itself).
Then the step, the least gain a task may ask (`cutter.floors`), from a measure, not a guess. Where nobody can price an
idea, the cutter cuts a **probe** (one named thing to try, at the floor, whose short answer is recorded at no cost to
its member), once the hive's commit your project pins holds probes. Your charter may also ask for a **free task**, a
probe whose idea is its worker's: a practice the cutter applies, not a mechanism of the hive. Never open a project
with probes alone: they are dealt to members with an accepted task. [cutter.md](cutter.md), "Probes".

## 4. The files

As [hosting.md](hosting.md), "What a project holds", lists them: `hive/project.json` (every setting described in
[`hive/settings.json`](../hive/settings.json); start from its `trial` preset, your own account number in
`members.only` from the first commit, so that the project is never open to anyone, and `"paused": true` until the
first run), `hive/charter.md` (your words for the
cutter: [cutter.md](cutter.md), "The backlog and the charter"), the first tasks in `hive/tasks.jsonl`, the caller
`.github/workflows/hive.yml` with its forty zeros kept until the first run, the judge's files and the workers'
sandbox (`bee/sandbox/sans-docker.sh`), the branch the hive writes, and the branch `hive-state`. The repository
belongs to an organization or another account than your personal one: you will fork it with your own account.

Then [hosting.md](hosting.md), "Checking a project": `hive.py doctor` says what is missing or wrong, and what is left
for you to decide (`DECIDE`).

## 5. The step and the bounds

[hosting.md](hosting.md), "Measuring a project": `hive.py measure` judges your project's tip with its own judge, a few
times, on your machine (Linux, Docker, and root or `sudo` without a password), and proposes the step, the judge's
bounds and the time of a judgement from what it measured. You run it, and decide each number. Leave room for the
program to grow. One pilot's experience, as its charter says it (`hive/charter.md` of
[Bee-ruche/squeezeBee](https://github.com/Bee-ruche/squeezeBee)): its tip took 54 seconds to encode by 23 November
2026, the whole margin of its 90-second bound, which was raised to 150; and its floor went from 0.25 % to 0.1 % once
probes had measured what ideas gave.

## 6. The repository's settings

[hosting.md](hosting.md), "The repository's settings": Actions permissions, workflow permissions, and the rulesets
that keep the run's token to the two branches the hive writes. Your AI prepares the list for your repository; you
apply it on GitHub. One choice goes with the rule that asks a review on your published branch: your cutter runs with
your account, so either your account is in that rule's bypass list and the cutter publishes directly (and that
account can change anything there), or your charter asks the cutter to open a pull request for each cut, from a
branch `cutter/<the date>` your account must then be allowed to create.

## 7. The first run

Your own account is the only member (`members.only`, the `trial` preset). Write the hive's commit into the caller, check
with the doctor that it is on the hive's main (`hive-commit` must read OK), then take `"paused"` out; fork the project with your account, and point your assistant at your fork as [join.md](join.md), "One task now, with
your assistant", says. Start a run by hand ("Run workflow", or `gh workflow run hive.yml`) and read what it did. A
judge that refuses your own honest work is mended before anyone else is asked in.

## 8. Inviting

On the founder's word: the `invitation` preset, the invited accounts' numbers in `members.only`, guardians where your
judge gives a figure they may waive ([guardians.md](guardians.md)), your cutter scheduled once a day
([cutter.md](cutter.md), "Where the cutter runs"; its prompt says whether your pinned commit holds probes), and
[join.md](join.md), which you send to the people you invite.

**The models your bees declare.** Your settings' `models` lists the model identifiers your project keeps statistics
for; the feed carries the list, and a bee reads it there. A bee declares its own whatever the list holds: one not
listed is counted as undeclared. Name each as its maker does, in lower case, dots kept (`claude-opus-5-5`,
`gpt-6.2-sol`, `gemini-2.5-pro`): a bee gives the identifier exactly as your list writes it, and one that does not
know its own gives the one of your list that names its maker and family. Add those of the bees you invite.

**A new file is a plain one.** The hive integrates a file a bee adds as a plain file, never an executable one,
whatever the bee's machine shows (a Windows or macOS machine shows every file executable to a container); a file
your project holds keeps its mode. A file you mean to be executable needs a person's `chmod +x`, on your branch.
Bees run a new script as `sh <file>`. The doctor counts the files your hive's branch holds as executable that your
published branch does not (`NOTE modes`), for those an older worker's tool sent so.

**A warning beside the line, wherever you post it.** Pasting the one line of join.md ("One task now") is a
volunteer's consent: their assistant tells them in a few lines what it is about to do, and goes on without asking.
So, wherever you post the line (a page, a message, an issue), put next to it what pasting it does, and that it is
for a project one trusts. A text you may use, with your project's name:

> **Before you paste this line:** it asks your AI assistant to work one task of `<owner/project>` for the hive, on
> your quota. It waits in your session, up to 90 minutes each time, so keep it open. It pushes only to branches
> named `hive/…` of your own fork, and your GitHub login and the commit are made public in the project's ledger. It
> opens no pull request or issue and writes to no one. The project's code runs only in a sandbox with no network.
> With the line « on this machine with Docker », Docker also builds images on your machine, and the work uses the
> GitHub account your git pushes as. Pasting it is your consent: your assistant says what it is about to do and does
> not ask again. Paste it only for a project you trust, after reading
> https://github.com/Bee-ruche/hive/blob/main/docs/join.md.

## 9. Your regular work

- Read what the judge accepted, on the hive's branch, before you publish it.
- Answer what the doctor, the feed and the cutter's report raise: a project with nothing left to do, stuck tasks, a
  sandbox workers cannot run, errors, a schedule GitHub disabled.
- Measure again once the project has moved far.
- Take a newer hive by changing the caller's pin, reviewed ([hosting.md](hosting.md), "Which version of the hive a
  project runs"); stop it by disabling the workflow or with `"paused": true` ("Stopping the hive").

## 10. An existing project

Your project already runs in the hive, and you want to know where it stands. Five readings, none of which pushes or
runs anything of your project (git only fetches into your clone); your AI runs and reads them with you
([its guide](../.claude/skills/bee-architect/SKILL.md), section 10, gives the commands for Linux):

- **`hive.py doctor`**: whether the project is well formed now, and its tasks in one line (`left to do`, `open`,
  `dealable now`, `stuck`, `short of members`). Four CANNOT lines, always there, are your repository's settings, which
  it cannot see; `hive-commit` says how many commits behind the hive's main your pin is, and is a NOTE when the run
  it pins lacks what main's worker tool uses (the bees' signals, duties, publish-cut, the page), naming each.
- **`hive.py tally`**: each task's deals, acceptances, refusals, errors and deals given back, and for the project
  whether it starves, which tasks are stuck, and what the members signalled ([cutter.md](cutter.md), "Signals").
- **`hive.py cut`**, dry: what the cutter's rules would do now (tasks closed, added, held back and why). It writes
  one file and pushes nothing. A backlog line held back gives what holds it back of its own first (`gate`, `needs`,
  `parent`, `files`, `shown_passing`, `not_shown_failing`), and `enough_open` or `changes` only when nothing else does.
- **The pin's age**: the commits of the hive's main after the one your caller pins. A run at an old pin lacks what
  came after.
- **The state's own files** on your branch `hive-state`: `feed.json`'s `generated_at` (a time that stops moving is a
  schedule GitHub disabled), and, for a `reference` project alone, `tip.json`, the judge's answers about the tip for
  planned tasks ([cutter.md](cutter.md), "The proof at the tip"). No command prints them.

`hive.py health` reads only the projects the hive lists (`hive/projects.json`); for another it says so and stops.
Listing your project is the founder's decision; the tally gives your project's numbers meanwhile.

Then section 9: what you read decides what you do next.

## On Windows or macOS

The hive's commands run on Linux. On Windows or macOS, the doctor, the tally and a dry cut run in a container of the
hive's tool image (the image the local bee's launcher builds), with nothing of your machine shown to it: the
container takes the hive, your project and its state afresh from GitHub, as a fetch would. You need Docker (Docker
Desktop) and git, and a bash: Git Bash on Windows (not PowerShell, which reads neither `<` nor `<<'EOF'`), Terminal
on macOS. Tried on Windows 11, in Git Bash with Docker Desktop, on 27 November 2026; not yet tried on macOS, nor on
a Mac with Apple silicon, where the image may need `--platform linux/amd64` on the `docker build` and `docker run`
lines.

Write your project's `owner/name` on the first line, then paste the whole block; it stops at the first step that
fails, and says which. Docker builds the image the first time (a few minutes, its output shown), and `docker run`
never pulls one (`--pull=never`); `MSYS_NO_PATHCONV=1` keeps Git Bash from turning the container's paths into
Windows ones, and changes nothing elsewhere.

```bash
PROJECT='<owner/project>'
(
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_CONFIG_COUNT GIT_CONFIG_PARAMETERS
[[ "$PROJECT" =~ ^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$ ]] || { echo "PROJECT is not owner/name: stop" >&2; exit 1; }
mkdir -p ~/.hive
if [ -d ~/.hive/architect/.git ]; then
  git -C ~/.hive/architect fetch --quiet origin main && git -C ~/.hive/architect reset --quiet --hard FETCH_HEAD \
    && git -C ~/.hive/architect clean -ffdx --quiet
else
  git clone --quiet https://github.com/Bee-ruche/hive ~/.hive/architect
fi || { echo "the hive could not be taken: stop" >&2; exit 1; }
HIVE_COMMIT=$(git -C ~/.hive/architect rev-parse HEAD)
IMAGE="hive-tool:$(git -C ~/.hive/architect rev-parse HEAD:tools/hive/Dockerfile)"
docker image inspect "$IMAGE" > /dev/null 2>&1 \
  || git -C ~/.hive/architect show HEAD:tools/hive/Dockerfile | docker build --tag "$IMAGE" - \
  || { echo "the image could not be built (its output is above): stop" >&2; exit 1; }
MSYS_NO_PATHCONV=1 docker run --pull=never --rm -i --init --read-only --tmpfs /tmp:rw,exec,size=1g --pids-limit 4096 \
  --cpus 2 --memory 2g --cap-drop ALL --security-opt no-new-privileges -e HOME=/tmp -e PROJECT="$PROJECT" \
  -e HIVE_COMMIT="$HIVE_COMMIT" -w /tmp "$IMAGE" sh -s > ~/.hive/architect-status.txt 2>&1 <<'EOF'
hive() { python3 -I /tmp/hive/tools/hive/hive.py "$@"; }
git clone --quiet https://github.com/Bee-ruche/hive /tmp/hive && git -C /tmp/hive checkout --quiet --detach "$HIVE_COMMIT" || exit 2
git clone --quiet "https://github.com/$PROJECT" /tmp/repo || exit 2
git -C /tmp/repo ls-remote --exit-code --heads origin hive-state > /dev/null; listed=$?
if [ "$listed" -eq 0 ]; then
  git clone --quiet --depth 1 --branch hive-state "https://github.com/$PROJECT" /tmp/state || exit 2
elif [ "$listed" -eq 2 ]; then
  echo "== no branch hive-state on GitHub"; mkdir /tmp/state
else
  echo "== GitHub could not be asked for the branch hive-state"; exit 2
fi
echo "== doctor"; hive doctor --project "$PROJECT" --repo /tmp/repo; echo "== exit $?"
echo "== tally"; hive tally --project "$PROJECT" --repo /tmp/repo --state /tmp/state; echo "== exit $?"
echo "== cut, dry"; hive cut --project "$PROJECT" --repo /tmp/repo --state /tmp/state --out /tmp/proposal.jsonl; echo "== exit $?"
pin=$(git -C /tmp/repo grep -h -i -o -E 'bee-ruche/hive/\.github/workflows/run\.yml@[0-9a-f]{40}' origin/HEAD -- .github/workflows | head -n 1 | cut -d@ -f2)
echo "== the pin: ${pin:-none found}"; [ -z "$pin" ] || git -C /tmp/hive log --first-parent --oneline "$pin..origin/main" || echo "the hive's clone does not hold the pin"
echo "== generated_at"; python3 -I -c 'import json, sys; print(json.load(open(sys.argv[1])).get("generated_at"))' /tmp/state/feed.json 2>/dev/null || echo none
echo "== tip.json (its first 20000 bytes)"; if [ -f /tmp/state/tip.json ]; then head -c 20000 /tmp/state/tip.json; echo; else echo "none (a reference project alone has one)"; fi
EOF
echo "written: ~/.hive/architect-status.txt (the container ended with $?)"
)
```

Read `~/.hive/architect-status.txt` (`less ~/.hive/architect-status.txt`), or give it to your AI with section 10 of
its guide. A line « the container ended with » other than 0, or a file that begins with an error rather than a
line `==`, says what failed: Docker, the network, or a project GitHub does not serve. Your project's repository is
public, so the container needs no account and holds no credential (on your machine, git takes the hive with your own
git's settings); it runs the hive's tool, never your project's code, with its files read-only but for a `/tmp` in
memory, and is removed as it ends.

**Not yet possible off Linux**, and what is missing:
- `hive.py measure`: it starts the judge's own containers, so it needs Docker and root or `sudo` without a password
  on the machine that runs it; the tool's container has neither. Run it on a Linux machine with Docker.
- The cutter's check and publication (`cut-check`, the commit and the push of the cutter's guide): they need the
  proposal written on your machine shown to the tool, then your own git's push, and no launcher does both yet (the
  local bee's launcher, `tools/hive/local.sh`, runs the worker's commands alone). Schedule the cutter where it runs
  on Linux ([cutter.md](cutter.md), "Where the cutter runs").
