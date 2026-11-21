# The relay kind's toy project

The smallest project the third kind of judge can judge (`tools/judge/relay.py`, `docs/relay-judge.md`), and the
subject of its tests (`tools/judge/test_relay.py`). It is nobody's project: it is here to be built, run and attacked.

| Path | Whose | What |
| --- | --- | --- |
| `bee/relay/project.json` | the project's | the manifest: data, checked field by field |
| `bee/relay/data` | the project's | the data: 4,270 bytes of text, long runs and sixteen-letter noise |
| `bee/relay/build`, `bee/relay/main.c` | the project's | the skeleton: the build script (it links the program statically), and the frame that reads descriptor 3 and writes descriptor 4 |
| `codec/codec.c` | a candidate's | the program: `toy_encode` and `toy_decode`, pairs (count, byte) at the tip |

A candidate changes `codec/` and nothing else. The tests write honest programs (a better coding of the runs) and
hostile ones (a decoder that looks for the data everywhere but in the message, a program that tries every system
call that could reach the machine, data moved into the source, a figure
that changes from one run to the next, a program that needs more than its time, its memory or its one process), as
texts of C built and run only in the judge's containers.
