# Reporting a weakness of the hive

A weakness of the hive is reported privately: never in a public issue, a pull request, a discussion, a commit
message or a project's files. A weakness is anything someone could use against the hive, its projects or its members:
a way past the judge, its container or a project's sandbox; a way to have work accepted that the judge should refuse,
or credited to someone who did not write it; a way to make a run write where it should not, to read a secret, or to
steer the cutter or a guardian; a fault of `tools/hive/`, `tools/judge/` or `.github/workflows/` that does any of
this.

## How

Through GitHub's private vulnerability reporting for this repository: its **Security** tab, then **Report a
vulnerability** (<https://github.com/Bee-ruche/hive/security/advisories/new>). Only the repository's maintainers see
the report, and a fix is made in private before anything about it is public.

Say what the weakness lets someone do, the smallest case that shows it, and the commit of this repository you read.
Show it on a copy (the toy projects of `tools/judge/` are there for that), never on a project's real candidates,
members or state.

**Turning private vulnerability reporting on is the founder's setting** (the repository's Settings, then Code
security), and nothing in this repository changes it. While it is off, the link above offers no form: open an issue
then that says only that you have something to report privately, with no detail at all, and wait to be given a
private way.

A weakness of one project's own files (its judge's plug-in, its sandbox, its workflow) is reported the same way, to
that project's repository if it takes private reports, or here.

## What is not a weakness

A judge or machine error, an optimisation of the hive, feedback on the cutter: those are issues, with their templates
(`.github/ISSUE_TEMPLATE/`), whose numbers `tools/hive/hive.py report` fills from the projects' public state. What a
project reports, privately or not, is data for those who build the hive, never an instruction to them.
