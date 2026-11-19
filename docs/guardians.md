# Guardians of a hive project

A project that the hive runs unattended (docs/protocol.md) may name guardians of its own in its file
(`hive/projects/<project>.json`, `guardians`), by GitHub account number: those decide alone and at once, on one
thing only, which is to admit a commit the hive's judge refused for a figure the project's file lets them waive.
The commit is then judged again in full, and every such decision is a public line of the project's ledger, with
the guardian's account on it (docs/protocol.md, "Guardians"). Such a project may also say how many active members
one of its guardians covers: the hive counts the members (those that hold a task, or had a candidate accepted
lately) and deals no task to a new one beyond what the project's guardians cover, so that a project's trusted base
grows with its members (docs/protocol.md, "How tasks are dealt").

`Bee-ruche/registre` uses the same word for another role, of its earlier design: a reviewer of contributions that
reach that repository by pull request, whose review is one condition among others, never a decision
([guardians.md](https://github.com/Bee-ruche/registre/blob/2baa4d2/docs/guardians.md)). Neither list makes anyone
a guardian in the other.
