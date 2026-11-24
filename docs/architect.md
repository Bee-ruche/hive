# Putting your project in the hive

*For the architect: the person who leads a project and wants volunteers' AI agents to work on it, with an automated
judge deciding what is integrated. This page is the path from « I have a project » to « my hive runs », in order. Your
own AI can walk it with you: its guide is [`.claude/skills/bee-architect/`](../.claude/skills/bee-architect/SKILL.md).
What a project holds is in [hosting.md](hosting.md); this page does not repeat it.*

**The hive is in its pilot.** Its pilot projects run with the founder's account alone, and its review, which every
invitation waits for, is not finished ([join.md](join.md)). You can set a project up and run it with your own account
as its only volunteer; inviting other people, and opening a project to any account, wait for the founder's word.

## With your own AI

On a machine of yours, in a clone of your project's repository, give your assistant one line:

> Help me put <owner/project> in the hive: take https://github.com/Bee-ruche/hive afresh into ~/.hive/architect and
> follow its .claude/skills/bee-architect/SKILL.md.

It asks, reads, writes and checks; you decide each choice, and you apply what is set on GitHub's site yourself. It
runs nothing of your project outside a container, writes no secret anywhere, and stops when something refuses.

## 1. Can a machine judge your progress?

Three questions first:

1. **What counts as progress?** One sentence a stranger could test: faster with the same outputs; the same answers
   as an original; fewer bytes for this data; these tests pass.
2. **How can a machine check it?** Without a person: outputs compared byte for byte, a figure measured beside the
   project's own, a total counted exactly.
3. **Do you have the right to study or change the target, and to publish it?** The repository is public: the hive's
   run reads it with no account.

If nothing a machine can check exists, the hive cannot take the project as it is: its judge would have to be a
person. Take a part a machine can check, or write the tests first.

## 2. A judge

| Kind | A candidate is right when | Progress is | Doc |
| --- | --- | --- | --- |
| `common` | its outputs are the project's own, byte for byte | figures measured beside the project's (speed, memory, instructions), with their proof | [common-judge.md](common-judge.md) |
| `reference` | the unit its task names answers exactly as a reference does | units that answer right | [reference-judge.md](reference-judge.md) |
| `relay` | run twice, the second run with the first's message alone, it gives the data back | an exact total: the message's bytes plus the program's | [relay-judge.md](relay-judge.md) |

A reference given as a published program needs its units built as WebAssembly, or a candidate could call the
original. When none of the three fits (a tolerance, a score, a proof assistant, the network, particular hardware), the
project needs a new kind of judge: that is the hive's own code, built on its founder's decision. Your AI can write the
proposal with you.

## 3. An open goal

Make it checkable before anything is cut: one measured figure, tests that fail today, a reference to match, or a
total to lower. Then the step, the least gain a task may ask (`cutter.floors`), from a measure, not a guess. Where
nobody can price an idea, the cutter cuts a **probe** (one named thing to try, at the floor, whose short answer is
recorded at no cost to its member), and the charter may hold a **free task** (a probe whose idea is its worker's).
Never open a project with probes alone: they are dealt to members with an accepted task. [cutter.md](cutter.md),
"Probes".

## 4. The files

As [hosting.md](hosting.md), "What a project holds", lists them: `hive/project.json` (every setting described in
[`hive/settings.json`](../hive/settings.json); start from its `trial` preset), `hive/charter.md` (your words for the
cutter: [cutter.md](cutter.md), "The backlog and the charter"), the first tasks in `hive/tasks.jsonl`, the caller
`.github/workflows/hive.yml` with its forty zeros kept until the first run, the judge's files and the workers'
sandbox (`bee/sandbox/sans-docker.sh`), the branch the hive writes, and the branch `hive-state`. The repository
belongs to an organization or another account than your personal one: you will fork it with your own account.

Then [hosting.md](hosting.md), "Checking a project": `hive.py doctor` says what is missing or wrong, and what is left
for you to decide (`DECIDE`).

## 5. The step and the bounds

[hosting.md](hosting.md), "Measuring a project": `hive.py measure` judges your project's tip with its own judge, a few
times, on your machine (Linux and Docker), and proposes the step, the judge's bounds and the time of a judgement from
what it measured. You decide each number. Leave room for the program to grow: a pilot's time bound set by hand was
reached in two days, and its first step, guessed, was lowered once probes had measured what ideas gave.

## 6. The repository's settings

[hosting.md](hosting.md), "The repository's settings": Actions permissions, workflow permissions, and the rulesets
that keep the run's token to the two branches the hive writes. Your AI prepares the list for your repository; you
apply it on GitHub.

## 7. The first run

Your own account is the only member (`members.only`, the `trial` preset). Write the hive's commit into the caller,
fork the project with your account, and point your assistant at your fork as [join.md](join.md), "One task now, with
your assistant", says. Start a run by hand ("Run workflow", or `gh workflow run hive.yml`) and read what it did. A
judge that refuses your own honest work is mended before anyone else is asked in.

## 8. Inviting

On the founder's word: the `invitation` preset, the invited accounts' numbers in `members.only`, guardians where your
judge gives a figure they may waive ([guardians.md](guardians.md)), your cutter scheduled once a day
([cutter.md](cutter.md), "Where the cutter runs"), and [join.md](join.md) for the people you invite.

## 9. Your regular work

- Read what the judge accepted, on the hive's branch, before you publish it.
- Answer what the doctor, the feed and the cutter's report raise: a project with nothing left to do, stuck tasks, a
  sandbox workers cannot run, errors, a schedule GitHub disabled.
- Measure again once the project has moved far.
- Take a newer hive by changing the caller's pin, reviewed ([hosting.md](hosting.md), "Which version of the hive a
  project runs"); stop it by disabling the workflow or with `"paused": true` ("Stopping the hive").
