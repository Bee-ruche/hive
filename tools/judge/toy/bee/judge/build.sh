#!/bin/sh
# Build of a variant (A = base, B = PR) of the toy project, INSIDE the container without network.
# Run by the common judge (tools/judge/judge.py): build.sh <sources> <base_tooling> <output>
#   <sources>         the variant's rle.c and rle.h (read-only)
#   <base_tooling>    copy of the BASE: bee/judge/ and its headers in base/
#   <output>          writable folder: obj/ (one object per .c file of the project) and execution
# The harness is compiled with the BASE's rle.h; only the variant's rle.c is compiled with its own headers.
# The analysis surveys (nm, objdump) are then made by the common judge on every object of obj/.
set -eu
umask 000
sources="$1"
tooling="$2"
output="$3"
mkdir -p "$output/obj"
cc -O2 -g -std=gnu99 -I"$sources" -c "$sources/rle.c" -o "$output/obj/rle.o"
cc -O2 -g -std=gnu99 -Wall -Wextra -I"$tooling/base" "$tooling/bee/judge/execution.c" "$output/obj/rle.o" -o "$output/execution"
echo "build done"
