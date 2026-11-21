---
name: A judge or machine error
about: The judge or the hive's machine failed on a project's candidates, with the project's numbers
title: "Error: "
---

<!-- Not for a weakness. A way past the judge, its container, a sandbox or the hive's rules is reported privately,
never in an issue: see SECURITY.md. -->

**Project** (owner/name):

**What happened**, in your own words: the run, the task (its id), what the judge or the machine did or did not do.

**What you expected instead.**

**The numbers.** `python3 tools/hive/hive.py report --template error --project <owner/name>` prints this issue with
the part below filled from the project's public branches: numbers, codes and ids, no member and no text a volunteer
wrote. Read what it prints before you post it.

<!-- numbers -->
Not filled: run the command above, or leave this part out.
<!-- end of numbers -->
