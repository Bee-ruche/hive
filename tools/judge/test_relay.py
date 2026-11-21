#!/usr/bin/env python3
"""Tests of Bee's judge of the third kind (tools/judge/relay.py, docs/relay-judge.md).

  python3 tools/judge/test_relay.py                          what needs no container
  BEE_JUDGE_INTEGRATION=1 python3 tools/judge/test_relay.py   + the whole judge, in containers, on the toy project
                                                             (tools/judge/relay_toy/), honest and HOSTILE
  BEE_JUDGE_NETWORK=host                                       the network of « docker build » (machines without a bridge)

The hostile programs below are texts of C written here, built and run ONLY in the judge's containers.
"""

import contextlib
import hashlib
import io
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "hive"))

import relay  # noqa: E402
from reading import JudgeError, MachineFailure, Refusal  # noqa: E402

TOY = HERE / "relay_toy"
MANIFEST = json.loads((TOY / "bee/relay/project.json").read_text())
DATA = (TOY / "bee/relay/data").read_bytes()
TIP_PROGRAM = (TOY / "codec/codec.c").read_text()
CONTAINERS = os.environ.get("BEE_JUDGE_INTEGRATION") == "1" and shutil.which("docker")

HEAD = """#define _GNU_SOURCE
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <signal.h>
#include <time.h>
#include <dirent.h>
#include <pthread.h>
#include <sys/auxv.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <netinet/in.h>
#include <arpa/inet.h>

static size_t store(const unsigned char *in, size_t n, unsigned char *out, size_t cap)
{
    if (n > cap)
        return (size_t)-1;
    memcpy(out, in, n);
    return n;
}

/* (plain system calls, as a program makes them when it means to reach a file) */
static void put(const char *path, const unsigned char *in, size_t n)
{
    int fd = open(path, O_WRONLY | O_CREAT | O_TRUNC, 0666);
    size_t done = 0;
    while (fd >= 0 && done < n) {
        ssize_t k = write(fd, in + done, n - done);
        if (k <= 0)
            break;
        done += (size_t)k;
    }
    if (fd >= 0)
        close(fd);
}

static size_t get(const char *path, unsigned char *out, size_t cap)
{
    int fd = open(path, O_RDONLY);
    size_t n = 0;
    if (fd < 0)
        return (size_t)-1;
    while (n < cap) {
        ssize_t k = read(fd, out + n, cap - n);
        if (k <= 0)
            break;
        n += (size_t)k;
    }
    close(fd);
    return n ? n : (size_t)-1;
}
"""


def program(encode="return store(in, n, out, cap);", decode="return store(in, n, out, cap);", before=""):
    """A program of the toy: the two functions the frame calls, with these bodies; `before` comes before them."""
    return (HEAD + before
            + "\nsize_t toy_encode(const unsigned char *in, size_t n, unsigned char *out, size_t cap)\n{\n    " + encode + "\n}\n"
            + "\nsize_t toy_decode(const unsigned char *in, size_t n, unsigned char *out, size_t cap)\n{\n    " + decode + "\n}\n")


STORE = program()  # the message is the data: right, and no door but the message
# Honest and better than the tip's pairs: literals in runs of their own (c < 128: c + 1 literals; else c - 125 times the next byte).
BETTER = """#include <stddef.h>
#include <string.h>

size_t toy_encode(const unsigned char *in, size_t n, unsigned char *out, size_t cap)
{
    size_t i = 0, k = 0, start = 0;
    for (;;) {
        size_t run = 1;
        while (i < n && i + run < n && run < 130 && in[i + run] == in[i])
            run++;
        if (i < n && run < 3) {
            i += run;
            continue;
        }
        while (start < i) {
            size_t literals = i - start < 128 ? i - start : 128;
            if (k + 1 + literals > cap)
                return (size_t)-1;
            out[k++] = (unsigned char)(literals - 1);
            memcpy(out + k, in + start, literals);
            k += literals;
            start += literals;
        }
        if (i >= n)
            return k;
        if (k + 2 > cap)
            return (size_t)-1;
        out[k++] = (unsigned char)(run + 125);
        out[k++] = in[i];
        i += run;
        start = i;
    }
}

size_t toy_decode(const unsigned char *in, size_t n, unsigned char *out, size_t cap)
{
    size_t i = 0, k = 0;
    while (i < n) {
        size_t c = in[i++];
        if (c < 128) {
            if (i + c + 1 > n || k + c + 1 > cap)
                return (size_t)-1;
            memcpy(out + k, in + i, c + 1);
            i += c + 1;
            k += c + 1;
        } else {
            if (i >= n || k + c - 125 > cap)
                return (size_t)-1;
            memset(out + k, in[i++], c - 125);
            k += c - 125;
        }
    }
    return k;
}
"""


def door(left_at, looked_for_at):
    """The encoder leaves the data at one place and an empty message; the decoder gives back what it finds at another."""
    return program(f'put("{left_at}", in, n); (void)out; (void)cap; return 0;',
                   f'(void)in; (void)n; return get("{looked_for_at}", out, cap);')


# Every place the first phase can write, or that the second might find the data at: each is a door (R1).
DOORS = [("/in/data", "/in/data"), ("/tmp/stash", "/tmp/stash"), ("/dev/shm/stash", "/dev/shm/stash"), ("/out/stash", "/out/stash"),
         ("/out/stash", "/in/stash"), ("/out/data", "/out/data"), ("/var/tmp/stash", "/var/tmp/stash"), ("/program/stash", "/program/stash"),
         ("/chrono/stash", "/chrono/stash"), ("/in/stash", "/in/stash"), ("/stash", "/stash")]
ENVIRONMENT = program('setenv("BEE_STASH", "kept", 1); put("/tmp/stash", in, n); (void)out; (void)cap; return 0;',
                      '(void)in; (void)n; return getenv("BEE_STASH") ? get("/tmp/stash", out, cap) : (size_t)-1;')
LAST_BYTE = program(decode="size_t k = store(in, n, out, cap); if (k && k != (size_t)-1) out[k - 1] ^= 1; return k;")
FIRST_BYTE = program(decode="size_t k = store(in, n, out, cap); if (k && k != (size_t)-1) out[0] ^= 0x80; return k;")
ONE_FEWER = program(decode="size_t k = store(in, n, out, cap); return k && k != (size_t)-1 ? k - 1 : k;")
ONE_MORE = program(decode="size_t k = store(in, n, out, cap - 1); if (k != (size_t)-1) out[k++] = 0; return k;")
TWICE = program(decode="size_t k = store(in, n, out, cap / 2); if (k != (size_t)-1) { memcpy(out + k, out, k); k *= 2; } return k;")
NOTHING = program(decode="(void)in; (void)n; (void)out; (void)cap; return 0;")
SPINS = "volatile unsigned long turns = 0; for (;;) turns++;"
NEVER_ENCODES = program(encode=SPINS + " (void)in; (void)n; (void)out; (void)cap; return 0;")
NEVER_DECODES = program(decode=SPINS + " (void)in; (void)n; (void)out; (void)cap; return 0;")
# It spins, and first writes what a measurement looks like wherever it can: the launcher's line is not the program's to write.
FORGES = program(encode='const char *line = "{\\"token\\": \\"0000000000000000\\", \\"label\\": \\"run\\", \\"code\\": 0, \\"signal\\": 0, '
                 '\\"user_s\\": 0.1, \\"system_s\\": 0.0, \\"wall_s\\": 0.1, \\"maxrss_kb\\": 1, \\"instructions\\": null}\\n"; '
                 'int fd; for (fd = 0; fd < 16; fd++) { if (fd != 4 && write(fd, line, strlen(line)) < 0) continue; } ' + SPINS
                 + " (void)in; (void)n; (void)out; (void)cap; return 0;")
# It means to wait an hour. Behind the gate no call waits: it goes on at once. Without the gate it waits, and the clock stops it.
SLEEPS = program(encode="sleep(3600); return store(in, n, out, cap);")
EATS_MEMORY = program(encode="size_t size = (size_t)1 << 30, i; volatile char *p = malloc(size); if (!p) return (size_t)-1; "
                      "for (i = 0; i < size; i += 1024) p[i] = (char)(i >> 10 | 1); return p[size - 1024] ? store(in, n, out, cap) : (size_t)-1;")
# The message carries eight bytes more, other at each run; its own decoder drops them: right at every run, never the same.
# Sixteen bytes the kernel draws for every process and hands it in its own memory: no call is needed to differ.
DRAWS = program(encode="size_t k = store(in, n, out, cap - 8); const void *drawn = (const void *)getauxval(AT_RANDOM); "
                "if (k == (size_t)-1 || !drawn) return (size_t)-1; memcpy(out + k, drawn, 8); return k + 8;",
                decode="return n < 8 ? (size_t)-1 : store(in, n - 8, out, cap);")
# The clock, which the kernel maps into every process: read without a call, so no filter takes it away.
CLOCK = program(encode="size_t k = store(in, n, out, cap - 8); struct timespec t; if (k == (size_t)-1) return k; "
                "if (clock_gettime(CLOCK_REALTIME, &t)) return (size_t)-1; memcpy(out + k, &t.tv_nsec, 8); return k + 8;",
                decode="return n < 8 ? (size_t)-1 : store(in, n - 8, out, cap);")
ADDRESS = program(encode="size_t k = store(in, n, out, cap - 8); void *here = &k; if (k == (size_t)-1) return k; memcpy(out + k, &here, 8); return k + 8;",
                  decode="return n < 8 ? (size_t)-1 : store(in, n - 8, out, cap);")
THREAD = "static void *work(void *nothing) { return nothing; }\n"
NEEDS_A_THREAD = program(before=THREAD, encode="pthread_t t; if (pthread_create(&t, NULL, work, NULL)) return (size_t)-1; "
                         "pthread_join(t, NULL); return store(in, n, out, cap);")
# Right only if it can start nothing: a phase has room for itself and no other process or thread.
WRONG_IF_IT_FORKS = program(encode="pid_t child = fork(); size_t k = store(in, n, out, cap); if (child == 0) _exit(0); "
                            "if (child > 0 && k && k != (size_t)-1) out[0] ^= 1; return k;")
WRONG_IF_IT_THREADS = program(before=THREAD, encode="pthread_t t; size_t k = store(in, n, out, cap); "
                              "if (!pthread_create(&t, NULL, work, NULL) && k && k != (size_t)-1) out[0] ^= 1; return k;")
CONNECT = ("struct sockaddr_in to; int s = socket(AF_INET, SOCK_STREAM, 0), reached; memset(&to, 0, sizeof to); to.sin_family = AF_INET; "
           'to.sin_port = htons(53); inet_pton(AF_INET, "1.1.1.1", &to.sin_addr); reached = s >= 0 && !connect(s, (struct sockaddr *)&to, sizeof to); ')
NEEDS_THE_NETWORK = program(encode=CONNECT + "return reached ? store(in, n, out, cap) : (size_t)-1;")
WRONG_IF_IT_REACHES_THE_NETWORK = program(encode=CONNECT + "{ size_t k = store(in, n, out, cap); if (reached && k && k != (size_t)-1) out[0] ^= 1; return k; }")
# What a program able to name a path does to the file it leaves (the gate lets none: these are for the reader behind it).
AT_EXIT = "static void swap(void) { unlink(\"/out/message\"); if (%s) _exit(9); }\n"
LINK_FOR_MESSAGE = program(before=AT_EXIT % 'symlink("/in/data", "/out/message")', encode="atexit(swap); return store(in, n, out, cap);")
PIPE_FOR_MESSAGE = program(before=AT_EXIT % 'mkfifo("/out/message", 0666)', encode="atexit(swap); return store(in, n, out, cap);")
FOLDER_FOR_MESSAGE = program(before=AT_EXIT % 'mkdir("/out/message", 0777)', encode="atexit(swap); return store(in, n, out, cap);")
# It fills the one file it may write, to the end of its room, before it answers.
FLOODS = program(encode="static char block[1 << 16]; while (write(4, block, sizeof block) == (ssize_t)sizeof block) { } return store(in, n, out, cap);")
# The build is asked for the data: by name, where the tip keeps it; a build is given the skeleton and the program alone.
BUILD_TAKES_THE_DATA = program(before='__asm__(".section .rodata\\nkept: .incbin \\"/src/bee/relay/data\\"\\n.previous");\n')
BUILD_BLOWS_UP = program(before="#define A0 1,1\n" + "".join(f"#define A{i} A{i - 1},A{i - 1}\n" for i in range(1, 34)) + "static int big[] = {A33};\n",
                         encode="(void)big; return store(in, n, out, cap);")

# Right only if the container it runs in holds nothing of any system: no file but those the judge put there (R1).
STRANGERS = """
static int strangers(const char *folder, int depth)
{
    static const char *known[] = {"/proc", "/sys", "/dev", "/etc", "/tmp", "/chrono", "/program", "/in", "/out", "/.root", "/.dockerenv"};
    DIR *d = opendir(folder);
    struct dirent *e;
    char path[512];
    int found = 0;
    size_t k;
    if (!d)
        return 0;
    while (depth < 8 && (e = readdir(d))) {
        int skip = !strcmp(e->d_name, ".") || !strcmp(e->d_name, "..");
        snprintf(path, sizeof path, "%s/%s", strcmp(folder, "/") ? folder : "", e->d_name);
        for (k = 0; k < sizeof known / sizeof *known; k++)
            skip |= !strcmp(path, known[k]);
        if (skip)
            continue;
        found += e->d_type == DT_DIR ? 1 + strangers(path, depth + 1) : 1;
    }
    closedir(d);
    return found;
}

static int a_system(void)
{
    DIR *root = opendir("/");
    if (!root)
        return 1; /* (it must be able to look: this program is for a container whose calls are not shut) */
    closedir(root);
    return strangers("/", 0) || !access("/bin/sh", F_OK) || !access("/usr", F_OK) || !access("/lib", F_OK) || !access("/lib64", F_OK)
           || !access("/etc/passwd", F_OK) || !access("/etc/os-release", F_OK) || !access("/usr/share/common-licenses/GPL-3", F_OK);
}
"""
WRONG_IF_IT_FINDS_A_SYSTEM = program(before=STRANGERS,
                                     encode="size_t k = store(in, n, out, cap); if (a_system() && k && k != (size_t)-1) out[0] ^= 1; return k;",
                                     decode="size_t k = store(in, n, out, cap); if (a_system() && k && k != (size_t)-1) out[0] ^= 2; return k;")

# R4. Every way a process has to ask the machine something or leave it something: names looked up under each folder it
# was given and elsewhere, the files of /proc and /sys, a file's times (its change and birth times among them), the
# times of the descriptors it holds, which pages are in memory, the clock and the wait as calls, other processes,
# new descriptors. How many of them were carried out.
REACHES = """
static int reaches(void)
{
    static const char *paths[] = {"/proc/uptime", "/proc/self/status", "/proc/loadavg", "/proc/1/cmdline", "/sys/kernel/btf/vmlinux",
                                  "/sys/fs/cgroup/memory.current", "/chrono/chrono", "/chrono/gate", "/chrono/no-such-name", "/program/run",
                                  "/program/no-such-name", "/in/data", "/in/message", "/in/no-such-name", "/out/message", "/out/data",
                                  "/out/no-such-name", "/etc/hostname", "/dev/urandom", "/dev/shm", "/tmp", "/", "."};
    struct stat seen;
    struct statx more;
    struct timespec now = {0, 1000};
    unsigned char page;
    char name[512];
    int reached = 0, fd;
    size_t i;
    for (i = 0; i < sizeof paths / sizeof *paths; i++) {
        fd = (int)syscall(SYS_openat, AT_FDCWD, paths[i], O_RDONLY);
        if (fd >= 0) {
            reached++;
            close(fd);
        }
        reached += syscall(SYS_newfstatat, AT_FDCWD, paths[i], &seen, 0) == 0;
        reached += syscall(SYS_statx, AT_FDCWD, paths[i], 0, STATX_BTIME | STATX_CTIME, &more) == 0;
        reached += syscall(SYS_faccessat, AT_FDCWD, paths[i], F_OK) == 0;
        reached += syscall(SYS_readlinkat, AT_FDCWD, paths[i], name, sizeof name) >= 0;
        reached += syscall(SYS_chdir, paths[i]) == 0;
    }
    for (fd = 0; fd < 5; fd++)
        reached += syscall(SYS_fstat, fd, &seen) == 0;
    reached += syscall(SYS_mincore, (void *)((size_t)&store & ~(size_t)4095), (size_t)4096, &page) == 0;
    reached += syscall(SYS_clock_gettime, CLOCK_MONOTONIC, &now) == 0;
    now.tv_sec = 0, now.tv_nsec = 1000;
    reached += syscall(SYS_nanosleep, &now, NULL) == 0;
    reached += syscall(SYS_getcwd, name, sizeof name) > 0;
    reached += syscall(SYS_kill, 1, 0) == 0;
    reached += syscall(SYS_getppid) > 0;
    reached += syscall(SYS_sched_yield) == 0;
    reached += syscall(SYS_times, NULL) != -1;
    reached += syscall(SYS_uname, name) == 0 ? 1 : 0;
    fd = (int)syscall(SYS_memfd_create, "kept", 0);
    if (fd >= 0) {
        reached++;
        close(fd);
    }
    fd = (int)syscall(SYS_socket, AF_UNIX, SOCK_STREAM, 0);
    if (fd >= 0) {
        reached++;
        close(fd);
    }
    return reached;
}
"""
WRONG_IF_A_CALL_REACHES_THE_MACHINE = program(before=REACHES,
                                              encode="size_t k = store(in, n, out, cap); if (reaches() && k && k != (size_t)-1) out[0] ^= 1; return k;",
                                              decode="size_t k = store(in, n, out, cap); if (reaches() && k && k != (size_t)-1) out[0] ^= 2; return k;")
# The one execve the gate lets through was the gate's own: another ends the process.
ANOTHER_EXECVE = program(encode='char *words[] = {"/program/run", "decode", NULL}, *none[] = {NULL}; execve("/program/run", words, none); '
                         "return store(in, n, out, cap);")

# Behind the gate: what a program has without a call, and what it tries with one that the filter must refuse.
# It stops itself: let through, it would wait, using no processor, until the clock; refused, it goes on (and is right).
STOPS_ITSELF = program(encode="if (syscall(SYS_tgkill, getpid(), gettid(), SIGSTOP) == 0) return (size_t)-1; return store(in, n, out, cap);")
# It aborts, as a C library does on a fault it finds: the one signal let through, to itself (ended by SIGABRT, 6).
ABORTS = program(encode="abort();")
# A call by its x32 number (the same machine, another set of calls): the process ends (SIGSYS, 31).
X32 = program(encode="syscall(0x40000000 | SYS_getpid); return store(in, n, out, cap);")
# The 32-bit entry (int 0x80, getpid's number there): the process ends (SIGSYS, 31).
ENTRY_32 = program(encode='long r; __asm__ volatile ("int $0x80" : "=a"(r) : "a"(20L) : "memory"); (void)r; return store(in, n, out, cap);')
# The processor's time-stamp counter, read with no call: behind the gate it faults (SIGSEGV, 11).
# The coarse clocks of the kernel's mapped time read no counter: the page the kernel updates at each tick, read as plain
# memory. Right only if that clock reads AND moves while the program runs: it pins the fact that a tick clock is left.
# It reads until the clock moves (one tick, a few milliseconds of the machine's time), not for a fixed count of turns,
# so that a slow machine does not bring it near its bound; it gives up, wrong, after a hundred million reads.
TICK_CLOCK_MOVES = program(encode="struct timespec a, b; unsigned long i; "
                           "if (clock_gettime(CLOCK_MONOTONIC_COARSE, &a)) return (size_t)-1; "
                           "for (i = 0; i < 100000000UL; i++) { if (clock_gettime(CLOCK_MONOTONIC_COARSE, &b)) return (size_t)-1; "
                           "if (b.tv_sec != a.tv_sec || b.tv_nsec != a.tv_nsec) return store(in, n, out, cap); } return (size_t)-1;")
COUNTER = program(encode="unsigned int low, high; size_t k = store(in, n, out, cap - 8); __asm__ volatile (\"rdtsc\" : \"=a\"(low), \"=d\"(high)); "
                  "if (k == (size_t)-1) return k; memcpy(out + k, &low, 4); memcpy(out + k + 4, &high, 4); return k + 8;",
                  decode="return n < 8 ? (size_t)-1 : store(in, n - 8, out, cap);")


def gate_without(*what):
    """The kind's own gate with some of its walls taken out, for the tests alone (to open a door on purpose and see
    what then stops a program): « filter » (the system's calls left open), « counter » (the clock left readable),
    « filter fails » (the filter's installation made to fail, as on a machine that cannot install one)."""
    text = (HERE / "gate.c").read_text()
    changes = {"filter": ("if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0 || prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &program) != 0)",
                          "if ((void)program, 0)"),
               "counter": ("if (prctl(PR_SET_TSC, PR_TSC_SIGSEGV, 0, 0, 0) != 0)", "if (0)"),
               "filter fails": ("prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &program)", "prctl(PR_SET_SECCOMP, 99, &program)")}
    for name in what:
        old, new = changes[name]
        if text.count(old) != 1:
            raise AssertionError(f"gate.c no longer holds the line the tests take out ({name})")
        text = text.replace(old, new)
    return text


# A toy tip whose build also runs a script of the program's own, when the program holds one: so that a candidate's
# files can make its build start processes, as a compiler would, and the tests see what ends them.
BUILD_WITH_A_HOOK = "#!/bin/sh\nset -eu\nif [ -f /src/codec/build.sh ]; then sh /src/codec/build.sh; fi\ncc -O2 -std=gnu99 -static -o /out/run /src/bee/relay/main.c /src/codec/*.c\n"
BURNS_IN_A_CHILD = "sh -c 'while :; do :; done' &\nwait\n"
WAITS_IN_A_CHILD = "sleep 600 &\nwait\n"


def table_of(data):
    return "static const unsigned char kept[] = {" + ",".join(str(byte) for byte in data) + "};\n"


def embedded(data):
    """The data moved into the program: an empty message, and a decoder that holds every byte in its own source."""
    return program(before=table_of(data), encode="(void)in; (void)n; (void)out; (void)cap; return 0;",
                   decode="(void)in; (void)n; if (sizeof kept > cap) return (size_t)-1; memcpy(out, kept, sizeof kept); return sizeof kept;")


def pairs(data):
    """The message the toy's tip writes, built here: (count, byte)."""
    out, i = bytearray(), 0
    while i < len(data):
        run = 1
        while i + run < len(data) and run < 255 and data[i + run] == data[i]:
            run += 1
        out += bytes([run, data[i]])
        i += run
    return bytes(out)


def write_tree(target, changes=None, source=TOY):
    """A copy of a tree with files written, removed (None) or made otherwise (a function of their path)."""
    shutil.copytree(source, target, symlinks=True)
    for relative, text in (changes or {}).items():
        path = Path(target) / relative
        if text is None:
            shutil.rmtree(path) if path.is_dir() else path.unlink()
        elif callable(text):
            path.parent.mkdir(parents=True, exist_ok=True)
            text(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text if isinstance(text, bytes) else text.encode())
    for folder, _, _ in os.walk(target):
        os.chmod(folder, 0o755)
    return Path(target)


class Reached(Exception):
    """Raised in place of a step a test stops at: the steps before it let the judgement through."""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get("BEE_TEST_TMP"))
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        os.chmod(self.root, 0o755)


class TestTheManifest(Base):
    """The manifest is the project's, at its tip: data. Every field is checked before anything is done with it."""

    def test_the_toys_manifest_is_taken_as_it_is(self):
        manifest = relay.check_manifest(MANIFEST)
        self.assertEqual((manifest["program"], manifest["skeleton"], manifest["image"], manifest["data"]["path"], manifest["data"]["bytes"]),
                         (["codec"], ["bee/relay/build", "bee/relay/main.c"], "common", "bee/relay/data", len(DATA)))
        self.assertEqual(manifest["data"]["sha256"], hashlib.sha256(DATA).hexdigest(), "the toy's manifest names the toy's data")
        self.assertEqual(relay.read_manifest(str(TOY)), manifest)

    def test_anything_else_is_a_failure_to_judge(self):
        fetched = {"url": "https://example.org/dc/data.zip", "fetched_bytes": 10, "fetched_sha256": "a" * 64, "member": "data",
                   "bytes": 20, "sha256": "b" * 64}
        self.assertEqual(relay.check_manifest({**MANIFEST, "data": fetched})["data"], fetched)
        self.assertIsNone(relay.check_manifest({**MANIFEST, "data": {**fetched, "member": None}})["data"]["member"])
        plain = {**fetched, "url": "http://example.org/dc/data.zip"}  # held to its fingerprint all the same
        self.assertEqual(relay.check_manifest({**MANIFEST, "data": plain})["data"]["url"], plain["url"])
        wrong = [
            ("a field more", {**MANIFEST, "runs": 2}), ("a field less", {k: v for k, v in MANIFEST.items() if k != "memory_mb"}),
            ("not a mapping", [MANIFEST]), ("an image of its own", {**MANIFEST, "image": "ubuntu:latest"}),
            ("a number that is a text", {**MANIFEST, "encode_seconds": "4"}), ("a yes for a number", {**MANIFEST, "encode_seconds": True}),
            ("no time at all", {**MANIFEST, "decode_seconds": 0}), ("a day", {**MANIFEST, "encode_seconds": 86400}),
            ("memory beyond the kind's cap", {**MANIFEST, "memory_mb": 1 << 20}), ("a program heavier than the count takes", {**MANIFEST, "program_bytes": 1 << 30}),
            ("a skeleton without the build", {**MANIFEST, "skeleton": ["bee/relay/main.c"]}),
            ("a path that climbs", {**MANIFEST, "program": ["../codec"]}), ("a hidden path", {**MANIFEST, "program": [".codec"]}),
            ("an absolute path", {**MANIFEST, "program": ["/codec"]}), ("no program", {**MANIFEST, "program": []}),
            ("a program listed twice", {**MANIFEST, "program": ["codec", "codec"]}), ("a program under another", {**MANIFEST, "program": ["codec", "codec/more"]}),
            ("the program is the skeleton", {**MANIFEST, "program": ["bee/relay/main.c"]}),
            ("the program holds the skeleton", {**MANIFEST, "program": ["bee"]}), ("the program is the project's tooling", {**MANIFEST, "program": ["bee/other"]}),
            ("the program is the hive's settings", {**MANIFEST, "program": ["hive/tasks.jsonl"]}),
            ("the data given to the build", {**MANIFEST, "skeleton": ["bee/relay"]}),
            ("the data in the program", {**MANIFEST, "data": {**MANIFEST["data"], "path": "codec/data"}}),
            ("the data both in the tree and fetched", {**MANIFEST, "data": {**MANIFEST["data"], **fetched}}),
            ("data without a fingerprint", {**MANIFEST, "data": {"path": "bee/relay/data", "bytes": 4270}}),
            ("a fingerprint in capitals", {**MANIFEST, "data": {**MANIFEST["data"], "sha256": "A" * 64}}),
            ("no data", {**MANIFEST, "data": None}), ("empty data", {**MANIFEST, "data": {**MANIFEST["data"], "bytes": 0}}),
            ("data heavier than one file may be read", {**MANIFEST, "data": {**MANIFEST["data"], "bytes": 1 << 30}}),
            ("an address that is neither http nor https", {**MANIFEST, "data": {**fetched, "url": "ftp://example.org/data.zip"}}),
            ("an address with a port", {**MANIFEST, "data": {**fetched, "url": "https://example.org:8443/data.zip"}}),
            ("a fingerprint of zeros: a placeholder", {**MANIFEST, "data": {**MANIFEST["data"], "sha256": "0" * 64}}),
            ("a fetched fingerprint of zeros", {**MANIFEST, "data": {**fetched, "fetched_sha256": "0" * 64}}),
            ("an address with a name and a password", {**MANIFEST, "data": {**fetched, "url": "https://me:secret@example.org/data.zip"}}),
            ("an address with a question", {**MANIFEST, "data": {**fetched, "url": "https://example.org/data.zip?token=1"}}),
            ("a file's address", {**MANIFEST, "data": {**fetched, "url": "file:///etc/passwd"}}),
            ("a member that climbs", {**MANIFEST, "data": {**fetched, "member": "../data"}}),
        ]
        for name, raw in wrong:
            with self.subTest(wrong=name), self.assertRaises(JudgeError):
                relay.check_manifest(raw)
        for name, text in (("no manifest", None), ("not JSON", b"{"), ("too deep", b"[" * 100000), ("not UTF-8", b"\xff\xfe")):
            tip = write_tree(self.root / name.replace(" ", "-"), {"bee/relay/project.json": text})
            with self.subTest(wrong=name), self.assertRaises(JudgeError):
                relay.read_manifest(str(tip))
        linked = write_tree(self.root / "linked", {"bee/relay/project.json": lambda path: (path.unlink(), path.symlink_to("/etc/hostname"))})
        with self.assertRaisesRegex(JudgeError, "cannot be read"):
            relay.read_manifest(str(linked))

    def test_the_bounds_add_up_to_a_whole_judgements_worst_case(self):
        manifest = relay.check_manifest(MANIFEST)
        clock = relay.wall_of(4)
        self.assertEqual((clock, relay.tip_bound(4), relay.wall_of(300), relay.tip_bound(300)), (11, 5, 455, 375),
                         "a phase's clock is half as much again as its processor time; the tip's own program is given a quarter more")
        self.assertEqual(relay.budget(manifest),
                         relay.LAUNCHER_SECONDS + relay.OVERHEAD + 3 * (relay.wall_of(60) + relay.REAPER + relay.OVERHEAD) + 10 * (clock + relay.OVERHEAD)
                         + relay.DATA_SECONDS,
                         "the launcher's build and three more (the tip's, run twice at most, and the candidate's), each to its clock and the "
                         "launcher's wait after it; six encodings (the tip's two, each run twice at most, the candidate's two) and four decodings "
                         "(the tip's one, run twice at most, the candidate's two)")
        self.assertLess(relay.budget(manifest), 1200, "the toy's worst case fits the time the base gives it in test_through_the_base")
        with mock.patch.object(relay, "the_data") as data, self.assertRaisesRegex(JudgeError, r"add up to \d+ s, above the 100 s"):
            relay.judge(mock.Mock(tip=str(TOY), task_file=None, budget=100, tip_itself=True), str(self.root))
        data.assert_not_called()

    def test_a_task_names_the_programs_paths_and_no_other(self):
        for files, taken in ((["codec/codec.c"], True), (["codec/"], True), (["codec"], True), (["codec/new.c", "codec/codec.c"], True),
                             (["bee/relay/main.c"], False), (["codec/codec.c", "README.md"], False), (["codecs/x.c"], False), ([""], False),
                             (["codec/../bee/relay/main.c"], False), (["/codec"], False), (["codec//x.c"], False)):
            with self.subTest(files=files), mock.patch.object(relay, "tip_is_ready", side_effect=Reached):
                with self.assertRaises(Reached if taken else JudgeError):
                    relay.judge(mock.Mock(tip=str(TOY), task_file=files, budget=3600, tip_itself=True), str(self.root))


class TestTreesOnTheHost(Base):
    """What is told of a candidate without running anything: its tree is the tip's but for the program, read as bytes."""

    def test_only_the_programs_files_may_differ(self):
        tip = write_tree(self.root / "tip")
        right = [{"codec/codec.c": BETTER}, {"codec/more.c": "int more;\n"}, {"codec/codec.c": None, "codec/other.c": BETTER}, {}]
        for i, changes in enumerate(right):
            with self.subTest(right=sorted(changes)):
                relay.only_the_program_differs(str(tip), str(write_tree(self.root / f"right-{i}", changes, source=tip)), ["codec"])
        wrong = [
            {"bee/relay/main.c": "int main(void) { return 0; }\n"}, {"bee/relay/build": "#!/bin/sh\ncp /src/x /out/run\n"},
            {"bee/relay/project.json": json.dumps({**MANIFEST, "encode_seconds": 900})}, {"bee/relay/data": DATA[:-1]},
            {"README.md": "changed\n"}, {"new-file": "x"}, {"bee/relay/data": None}, {"codec2/codec.c": BETTER},
            {"bee/relay/main.c": lambda path: path.chmod(path.stat().st_mode ^ 0o111)},{"README.md": lambda path: (path.unlink(), path.symlink_to("codec/codec.c"))},
            {"bee/relay/extra": lambda path: path.mkdir()},
        ]
        for i, changes in enumerate(wrong):
            with self.subTest(wrong=sorted(changes)), self.assertRaisesRegex(Refusal, "something else than the program's files"):
                relay.only_the_program_differs(str(tip), str(write_tree(self.root / f"wrong-{i}", changes, source=tip)), ["codec"])

    def test_a_tree_too_large_is_the_candidates_and_a_tree_that_cannot_be_read_is_nobodys(self):
        tip = write_tree(self.root / "tip")
        other = write_tree(self.root / "other", {"codec/codec.c": BETTER})
        for wrong in (JudgeError("too many entries"), RecursionError("maximum recursion depth exceeded"), OSError(36, "File name too long")):
            with self.subTest(wrong=type(wrong).__name__):
                with mock.patch.object(relay, "snapshot", side_effect=[{}, wrong]), self.assertRaisesRegex(Refusal, "too many entries, or is nested too deep"):
                    relay.only_the_program_differs(str(tip), str(other), ["codec"])
                with mock.patch.object(relay, "snapshot", side_effect=wrong), self.assertRaises(JudgeError) as raised:
                    relay.only_the_program_differs(str(tip), str(other), ["codec"])  # the tip's own tree: the project's
                self.assertNotIsInstance(raised.exception, Refusal)
        deep = write_tree(self.root / "deep", {"codec/" + "d/" * relay.DEPTH + "more.c": ""})
        with self.assertRaisesRegex(Refusal, f"nested deeper than {relay.DEPTH} folders"):
            relay.only_the_program_differs(str(tip), str(deep), ["codec"])
        relay.only_the_program_differs(str(tip), str(write_tree(self.root / "not-so-deep", {"codec/" + "d/" * (relay.DEPTH - 2) + "more.c": ""})), ["codec"])
        with mock.patch.object(relay, "same_bytes", side_effect=PermissionError("denied")), self.assertRaisesRegex(JudgeError, "cannot be read"):
            relay.only_the_program_differs(str(tip), str(other), ["codec"])

    def test_a_programs_files_are_plain_files_within_the_projects_bounds(self):
        manifest = relay.check_manifest(MANIFEST)
        tip = write_tree(self.root / "tip", {"codec/b.c": "b", "codec/a.c": "a"})
        self.assertEqual(relay.program_files(str(tip), manifest, Refusal), [("codec/a.c", b"a"), ("codec/b.c", b"b"), ("codec/codec.c", TIP_PROGRAM.encode())])
        wrong = [
            ("a link", {"codec/link.c": lambda path: path.symlink_to("/etc/hostname")}, "not a plain file or folder"),
            ("a link to the data", {"codec/codec.c": lambda path: (path.unlink(), path.symlink_to("../bee/relay/data"))}, "not a plain file or folder"),
            ("a pipe", {"codec/pipe": lambda path: os.mkfifo(path)}, "not a plain file or folder"),
            ("the folder is a link", {"codec": lambda path: (shutil.rmtree(path), path.symlink_to("bee/relay"))}, "not a plain file or folder"),
            ("no program", {"codec": None}, "not a plain file or folder"),
            ("too many files", {f"codec/f{i}.c": "" for i in range(9)}, "holds 10 files, the project's bound is 8"),
            ("too heavy", {"codec/big.c": "x" * 65536}, "weigh more than the project's bound"),
            ("a name that is not plain", {"codec/a b.c": "x"}, "not a plain name"),
        ]
        for name, changes, said in wrong:
            tree = write_tree(self.root / name.replace(" ", "-"), changes)
            for blame in (Refusal, JudgeError):
                with self.subTest(wrong=name, blame=blame.__name__), self.assertRaisesRegex(blame, said) as raised:
                    relay.program_files(str(tree), manifest, blame)
                self.assertIs(type(raised.exception), blame)
        within = write_tree(self.root / "within", {"codec/codec.c": "x" * 65536})
        self.assertEqual(len(relay.program_files(str(within), manifest, Refusal)[0][1]), 65536, "exactly the bound is within it")

    def test_a_build_is_given_the_skeleton_and_one_program_and_nothing_else(self):
        manifest = relay.check_manifest(MANIFEST)
        tip = write_tree(self.root / "tip", {"codec/codec.c": lambda path: path.chmod(0o777)})
        target = relay.sources_of(str(tip), manifest, [("codec/codec.c", b"theirs"), ("codec/deep/more.c", b"")], str(self.root / "sources"))
        seen = sorted(os.path.relpath(os.path.join(folder, name), target) for folder, _, names in os.walk(target) for name in names)
        self.assertEqual(seen, ["bee/relay/build", "bee/relay/main.c", "codec/codec.c", "codec/deep/more.c"], "neither the data nor the manifest")
        self.assertEqual((Path(target) / "codec/codec.c").read_bytes(), b"theirs")
        self.assertEqual({oct(os.stat(os.path.join(target, name)).st_mode & 0o777) for name in seen if name.startswith("codec/")}, {"0o644"},
                         "a file brings its path and its bytes: no mode of its own")
        self.assertEqual({int(os.stat(os.path.join(target, name)).st_mtime) for name in seen}, {relay.container.TIME}, "and no time of its own")
        broken = write_tree(self.root / "broken", {"bee/relay/main.c": lambda path: (path.unlink(), path.symlink_to("/etc/hostname"))})
        with self.assertRaisesRegex(JudgeError, "the tip's skeleton"):
            relay.sources_of(str(broken), manifest, [], str(self.root / "other"))

    def test_what_the_tip_must_hold(self):
        manifest = relay.check_manifest(MANIFEST)
        relay.tip_is_ready(str(TOY), manifest)
        for name, changes in (("a repository", {".git/HEAD": "ref: refs/heads/main\n"}), ("no program", {"codec": None})):
            with self.subTest(wrong=name), self.assertRaises(JudgeError):
                relay.tip_is_ready(str(write_tree(self.root / name.replace(" ", "-"), changes)), manifest)


class TestTheData(Base):
    """The data is the tip's own file, or fetched once at the image step: held to the manifest's fingerprint each time."""

    def test_the_tips_file_is_held_to_its_fingerprint(self):
        manifest = relay.check_manifest(MANIFEST)
        self.assertEqual(relay.the_data(str(TOY), manifest), DATA)
        for name, change in (("a byte changed", DATA[:-1] + b"!"), ("a byte more", DATA + b"\n"), ("missing", None),
                             ("a link", lambda path: (path.unlink(), path.symlink_to("/etc/hostname")))):
            with self.subTest(wrong=name), self.assertRaises(JudgeError):
                relay.the_data(str(write_tree(self.root / name.replace(" ", "-"), {"bee/relay/data": change})), manifest)

    def test_what_is_fetched_is_held_to_its_fingerprint_and_fetched_at_the_image_step_only(self):
        packed = io.BytesIO()
        with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("other", b"not this one")
            archive.writestr("data", DATA)
        packed = packed.getvalue()
        data = {"url": "https://example.org/dc/data.zip", "fetched_bytes": len(packed), "fetched_sha256": hashlib.sha256(packed).hexdigest(),
                "member": "data", "bytes": len(DATA), "sha256": hashlib.sha256(DATA).hexdigest()}
        manifest = relay.check_manifest({**MANIFEST, "data": data})

        def served(body):
            answer = mock.MagicMock()
            answer.__enter__.return_value.read = io.BytesIO(body).read
            return mock.patch.object(relay.urllib.request, "urlopen", return_value=answer)

        with served(packed) as asked:
            self.assertEqual(relay.fetch(manifest["data"]), DATA)
        self.assertEqual(asked.call_args[0][0], data["url"])
        with served(DATA):
            self.assertEqual(relay.fetch({**manifest["data"], "member": None, "fetched_bytes": len(DATA), "fetched_sha256": data["sha256"]}), DATA,
                             "no member: what is fetched is the data")
        for name, body, changed in (("another archive", packed[:50] + bytes([packed[50] ^ 1]) + packed[51:], {}),("a byte more", packed + b"\0", {}), ("cut short", packed[:100], {}),
                                    ("another member", packed, {"member": "other"}), ("no such member", packed, {"member": "absent"}),
                                    ("not an archive", DATA, {"fetched_bytes": len(DATA), "fetched_sha256": data["sha256"]}),
                                    ("the right archive, other data", packed, {"sha256": "1" * 64})):
            with self.subTest(wrong=name), served(body), self.assertRaises(JudgeError):
                relay.fetch({**manifest["data"], **changed})
        with mock.patch.object(relay.urllib.request, "urlopen", side_effect=OSError("no route")), self.assertRaisesRegex(JudgeError, "could not be fetched"):
            relay.fetch(manifest["data"])
        # while judging nothing is fetched: data the image step did not keep is a failure to judge
        tip = write_tree(self.root / "tip", {"bee/relay/project.json": json.dumps({**MANIFEST, "data": data})})
        with mock.patch.object(relay, "kept_data", return_value=None), mock.patch.object(relay.urllib.request, "urlopen") as asked:
            with self.assertRaisesRegex(JudgeError, "image step"):
                relay.the_data(str(tip), manifest)
        asked.assert_not_called()
        self.assertEqual(relay.data_label(manifest["data"]), "bee-relay-data:" + data["sha256"][:32])


class TestWhatAnOutcomeMeans(unittest.TestCase):
    """The kind says what a phase's measurement means: the launcher's figures are not verdicts."""

    @staticmethod
    def measurement(**changed):
        return {"token": "t" * 32, "label": "encode", "code": 0, "signal": 0, "user_s": 1.0, "system_s": 0.5, "wall_s": 1.6, "maxrss_kb": 900,
                "instructions": None, **changed}

    def test_time_memory_and_exit_are_the_programs_and_a_starved_machine_is_nobodys(self):
        ended = self.measurement
        relay.outcome(ended(), 4, 11, Refusal, "the phase")
        relay.outcome(ended(user_s=3.5, system_s=0.5), 4, 11, Refusal, "the phase")  # exactly its bound
        for blame in (Refusal, JudgeError):
            for name, m, said in (
                    ("past its time and ended", ended(user_s=4.0, system_s=0.01), r"took 4\.0 s of processor time; its bound is 4 s"),
                    ("stopped by the clock, its time used", ended(signal=9, user_s=10.5, wall_s=11.0), r"stopped after 11.0 s of processor time"),
                    ("killed before the clock", ended(signal=9, wall_s=2.0), r"ended by signal 9 \(killed: past its memory bound, most likely\)"),
                    ("it aborts", ended(signal=6), r"ended by signal 6\. said : :warning: : \?\[31m"),
                    ("it fails", ended(code=3), r"exit status 3\. said")):
                with self.subTest(outcome=name, blame=blame.__name__), self.assertRaisesRegex(blame, "the phase: " + said) as raised:
                    relay.outcome(m, 4, 11, blame, "the phase", b"said ::warning:: \x1b[31m")
                self.assertIs(type(raised.exception), blame)
            # the clock stopped it and it had used a tenth of its time: the machine starved it, or it waits; never a refusal
            with self.assertRaisesRegex(JudgeError, "the judge cannot say which") as raised:
                relay.outcome(ended(signal=9, user_s=0.3, system_s=0.1, wall_s=11.02), 4, 11, blame, "the phase")
            self.assertIs(type(raised.exception), JudgeError)
        # on the tip's side: what its bytes do not decide (its time, a signal) is Wavered, run once more; an exit status is not
        for name, m, again in (("past its time and ended", ended(user_s=4.0, system_s=0.01), True),
                               ("stopped by the clock, its time used", ended(signal=9, user_s=10.5, wall_s=11.0), True),
                               ("killed before the clock", ended(signal=9, wall_s=2.0), True), ("it aborts", ended(signal=6), True),
                               ("it fails", ended(code=3), False)):
            with self.subTest(tip=name), self.assertRaises(relay.TipFault) as raised:
                relay.outcome(m, 4, 11, relay.TipFault, "the tip's phase")
            self.assertIs(type(raised.exception), relay.Wavered if again else relay.TipFault)
        with self.assertRaises(JudgeError) as raised:  # and the machine's doubt stays the machine's, on the tip's side too
            relay.outcome(ended(signal=9, user_s=0.3, system_s=0.1, wall_s=11.02), 4, 11, relay.TipFault, "the tip's phase")
        self.assertIs(type(raised.exception), JudgeError)

    def test_the_launchers_line_is_the_only_measurement(self):
        def ran(code, out):
            return subprocess.CompletedProcess(["chrono"], code, out, b"")

        line = json.dumps(self.measurement()).encode() + b"\n"
        self.assertEqual(relay.measured(ran(0, line), "t" * 32, "encode", Refusal, "the phase")["maxrss_kb"], 900)
        # ended with 137 and no line, and Docker's own record says the kernel ended it for its memory (container.Docker.launch
        # hands that back as `oom_killed`): the program's (or the tip's)
        def killed(oom_killed):
            answer = ran(137, b"")
            if oom_killed is not None:
                answer.oom_killed = oom_killed
            return answer

        for blame, kind in ((Refusal, Refusal), (JudgeError, JudgeError), (relay.TipFault, relay.Wavered)):
            with self.assertRaisesRegex(blame, "its container was ended by the kernel for its memory") as raised:
                relay.measured(killed(True), "t" * 32, "encode", blame, "the phase")
            self.assertIs(type(raised.exception), kind, "the tip's is run once more")
        # the same without that record (Docker restarted, a run cancelled): the machine's
        for record in (False, None, "true", 1):
            with self.subTest(oom_killed=record), self.assertRaises(JudgeError) as raised:
                relay.measured(killed(record), "t" * 32, "encode", Refusal, "the phase")
            self.assertNotIsInstance(raised.exception, Refusal)
        for name, answer in (("the launcher failed", ran(2, line)), ("no line", ran(0, b"")), ("two lines", ran(0, line + line)),
                             ("another token", ran(0, line.replace(b"tttt", b"uuuu"))), ("another phase's", ran(0, line.replace(b"encode", b"decode"))),
                             ("not JSON", ran(0, b"{\n")), ("a list", ran(0, b"[]\n")), ("a figure missing", ran(0, line.replace(b'"wall_s"', b'"wall"'))),
                             ("a figure that is a text", ran(0, line.replace(b"900", b'"900"')))):
            with self.subTest(wrong=name), self.assertRaises(JudgeError) as raised:
                relay.measured(answer, "t" * 32, "encode", Refusal, "the phase")
            self.assertNotIsInstance(raised.exception, Refusal)

    def test_how_what_came_back_differs(self):
        data = bytes(range(256)) * 1000
        self.assertEqual(relay.how_it_differs(data[:-1], data), "255999 bytes where the data holds 256000")
        self.assertEqual(relay.how_it_differs(data + b"\0", data), "256001 bytes where the data holds 256000")
        for at in (0, 65535, 65536, 200001, 255999):
            changed = bytearray(data)
            changed[at] ^= 1
            self.assertEqual(relay.how_it_differs(bytes(changed), data), f"the same length, another byte at offset {at}")

    def test_the_command_line(self):
        with self.assertRaises(JudgeError):
            relay.main(["--tip", "t"])
        with mock.patch.object(relay, "image_of", return_value="sha256:" + "0" * 64) as image, mock.patch.object(relay, "kept_data") as kept, \
                mock.patch.object(relay, "bare_image", return_value="sha256:" + "1" * 64) as bare:
            self.assertEqual(relay.main(["--tip", str(TOY), "--image-only"]), 0)
        self.assertEqual(image.call_args[0][0]["image"], "common")
        bare.assert_called_once_with()  # the empty image the phases run in, made at the image step too
        kept.assert_not_called()  # the toy's data is its tip's own file: nothing to fetch


def unpairs(message):
    """The data the toy's tip gives back for its message (pairs, read back)."""
    return b"".join(bytes([message[i + 1]]) * message[i] for i in range(0, len(message), 2))


class TestAStepOfTheTipsRunOnceMore(Base):
    """A step of the tip's (its build, one of its phases) that fails in a way its bytes do not decide is run once more
    before the failure is said to be on the tip's side; what its bytes decide is not, and a candidate's steps never
    are. Docker's launch alone is played here, and the memory file systems are plain folders: the judgement's steps,
    the launcher's line and what it means are the kind's own."""

    PROGRAM = b"\x7fELF: the toy's program, as a build leaves it"

    def judge_with(self, ends, candidate=False):
        """One judgement of the toy, every container played: the n-th container of a step (« build », « encode »,
        « decode », counted from 1 over the whole judgement) ends as `ends` says: {step: {n: the launcher's figures
        changed, or « memory » (status 137, no line, Docker's record of a kill for memory), or « another message »}};
        the others do what the toy's program does. Returns (the figures, or the error raised; what the judge logged;
        how many containers of each step were started)."""
        started = {"build": 0, "encode": 0, "decode": 0}

        def launch(docker, command, mounts, pids=2, entry=None, timeout_seconds=3600):
            lines = entry.decode().split("\n")
            token, words = lines[0], lines[2].split("\t")[2:]
            step = "build" if "--build" in words else words[-1]
            started[step] += 1
            folders = {target: host for host, target, _ in mounts}
            end = ends.get(step, {}).get(started[step], {})
            if end == "memory":
                ran = subprocess.CompletedProcess(command, 137, b"", b"")
                ran.oom_killed = True
                return ran
            if step == "build":
                Path(folders["/out"], "run").write_bytes(self.PROGRAM)
            else:
                name, wanted = relay.PHASES[step]
                given = Path(folders["/in"], name).read_bytes()
                left = bytearray(pairs(given) if step == "encode" else unpairs(given))
                if end == "another message":
                    left[-1] ^= 1  # (the same length: another message, or data with its last byte changed)
                Path(folders["/out"], wanted).write_bytes(bytes(left))
            line = {"token": token, "label": "run", "code": 0, "signal": 0, "user_s": 0.2, "system_s": 0.0, "wall_s": 0.3, "maxrss_kb": 1000,
                    **(end if isinstance(end, dict) else {})}
            return subprocess.CompletedProcess(command, 0, json.dumps(line).encode() + b"\n", b"")

        def mount_point(*command):  # a plain folder for a memory file system: emptied where it would be unmounted
            if command[0] == "umount":
                shutil.rmtree(command[-1])
                os.mkdir(command[-1])

        tip = write_tree(self.root / f"tip-{len(list(self.root.iterdir()))}")
        other = write_tree(self.root / f"candidate-{len(list(self.root.iterdir()))}") if candidate else None
        work = self.root / f"work-{len(list(self.root.iterdir()))}"
        work.mkdir()
        args = mock.Mock(tip=str(tip), candidate=str(other) if other else None, task_file=None, budget=3600, tip_itself=not candidate)
        said = io.StringIO()
        with mock.patch.object(relay.container.Docker, "launch", launch), mock.patch.object(relay.container, "mount_point", mount_point), \
                mock.patch.object(relay, "image_of", return_value="sha256:" + "0" * 64), \
                mock.patch.object(relay, "bare_image", return_value="sha256:" + "1" * 64), \
                mock.patch.object(relay, "launcher_of", return_value={"chrono": b"launcher", "gate": b"gate"}), contextlib.redirect_stderr(said):
            try:
                result = relay.judge(args, str(work))
            except (JudgeError, Refusal) as error:
                result = error
        return result, said.getvalue(), started

    def test_a_failure_its_bytes_do_not_decide_is_run_once_more_and_the_judgement_goes_on(self):
        clock = relay.wall_of(MANIFEST["build_seconds"])
        for name, ends, said, builds, runs in (
                ("the build stopped at its clock, its time used", {"build": {1: {"signal": 9, "user_s": 80.0, "wall_s": clock}}},
                 r"the tip's build: stopped after 80\.0 s of processor time; its bound is 60 s", 2, 3),
                ("the first encoding ended by a signal", {"encode": {1: {"signal": 9, "wall_s": 1.0}}},
                 r"the tip's first encoding: ended by signal 9 \(killed: past its memory bound, most likely\)", 1, 4),
                ("the second encoding past its processor time", {"encode": {2: {"user_s": 6.0}}},
                 r"the tip's second encoding: took 6\.0 s of processor time; its bound is 5 s", 1, 4),
                ("the decoding's container ended for its memory", {"decode": {1: "memory"}},
                 r"the tip's decoding: its container was ended by the kernel for its memory", 1, 4)):
            with self.subTest(failed=name):
                figures, log, _ = self.judge_with(ends)
                self.assertIsInstance(figures, dict, figures)
                self.assertEqual((figures["total_bytes"], figures["builds"], figures["runs"]), (len(pairs(DATA)) + len(self.PROGRAM), builds, runs),
                                 "the judgement goes on with the second run, and counts both")
                self.assertEqual(log.count(relay.ONCE_MORE), 1, log)
                self.assertRegex(log, re.escape(relay.ONCE_MORE) + ": " + said)
        # the same with a candidate: judged as if nothing had happened, the tip's step that was run twice counted
        figures, log, _ = self.judge_with({"encode": {1: {"signal": 11, "wall_s": 1.0}}}, candidate=True)
        self.assertEqual((figures["sure_total_bytes"], figures["builds"], figures["runs"]), (0, 2, 8), figures)
        self.assertIn(relay.ONCE_MORE, log)

    def test_the_same_failure_twice_is_on_the_tips_side(self):
        for name, ends, said, started_then in (
                ("the first encoding killed twice", {"encode": {1: {"signal": 9, "wall_s": 1.0}, 2: {"signal": 9, "wall_s": 1.0}}},
                 "the tip's first encoding: ended by signal 9", {"build": 1, "encode": 2, "decode": 0}),
                ("the build past its time, then killed for memory", {"build": {1: {"user_s": 70.0}, 2: "memory"}},
                 "the tip's build: its container was ended by the kernel for its memory", {"build": 2, "encode": 0, "decode": 0})):
            with self.subTest(failed=name):
                error, log, started = self.judge_with(ends, candidate=True)
                self.assertIs(type(error), relay.TipFault, error)
                self.assertIn(said, str(error))
                self.assertIn("run twice", str(error))
                self.assertEqual(log.count(relay.ONCE_MORE), 1, log)
                self.assertEqual(started, started_then, "the step twice, and nothing after it")

    def test_what_its_bytes_decide_is_not_run_again_and_a_candidates_step_never_is(self):
        for name, ends, said, started_then in (
                ("an exit status", {"encode": {1: {"code": 3}}}, "the tip's first encoding: exit status 3", {"build": 1, "encode": 1, "decode": 0}),
                ("a build that fails", {"build": {1: {"code": 1}}}, "the tip's build: exit status 1", {"build": 1, "encode": 0, "decode": 0}),
                ("two encodings that differ", {"encode": {2: "another message"}}, "the tip's own two encodings of the data are not the same bytes",
                 {"build": 1, "encode": 2, "decode": 0}),
                ("a decoding that is not the data", {"decode": {1: "another message"}}, "the tip's own program does not give the data back",
                 {"build": 1, "encode": 2, "decode": 1})):
            with self.subTest(failed=name):
                error, log, started = self.judge_with(ends, candidate=True)
                self.assertIs(type(error), relay.TipFault, error)
                self.assertIn(said, str(error))
                self.assertNotIn(relay.ONCE_MORE, log)
                self.assertEqual(started, started_then)
        # the candidate's first encoding killed: refused at once, never run again
        error, log, started = self.judge_with({"encode": {3: {"signal": 9, "wall_s": 1.0}}}, candidate=True)
        self.assertIs(type(error), Refusal, error)
        self.assertIn("the candidate's first encoding: ended by signal 9", str(error))
        self.assertNotIn(relay.ONCE_MORE, log)
        self.assertEqual(started, {"build": 2, "encode": 3, "decode": 1})


@unittest.skipUnless(CONTAINERS, "the whole judge: BEE_JUDGE_INTEGRATION=1 and Docker")
class TestTheJudgeInContainers(Base):
    """The whole judge, in containers, on the toy project: honest programs, then hostile ones."""

    def judge(self, candidate=None, tip=None, files=None, budget=3600):
        """(exit status, the report, what the judge said) of one judgement, run as the base runs it."""
        self.count = getattr(self, "count", 0) + 1
        out = self.root / f"report-{self.count}.json"
        command = [sys.executable, "-B", str(HERE / "relay.py"), "--tip", str(tip or self.tip), "--budget", str(budget), "--json", str(out),
                   "--workdir", str(self.root / "work")]
        for path in files or ["codec/"]:
            command += ["--task-file", path]
        command += ["--candidate", str(candidate)] if candidate else ["--tip-itself"]
        ran = subprocess.run(command, capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
        report = json.loads(out.read_text())
        self.assertEqual(report["code"], ran.returncode, ran.stderr)
        self.assertEqual(os.listdir(self.root / "work"), [], "nothing of a judgement stays")
        self.assertNotIn(str(self.root), Path("/proc/mounts").read_text(), "nothing stays mounted")
        return ran.returncode, report, ran.stderr

    def candidate(self, changes, tip=None):
        self.made = getattr(self, "made", 0) + 1
        return write_tree(self.root / f"candidate-{self.made}", changes, source=tip or self.tip)

    def setUp(self):
        super().setUp()
        self.tip = write_tree(self.root / "tip")

    def answered(self, text, code, said=None, **options):
        got, report, err = self.judge(self.candidate({"codec/codec.c": text}, options.get("tip")), **options)
        self.assertEqual(got, code, err)
        if said:
            self.assertRegex(report["reason"], said)
        return report

    def refused(self, text, said, **options):
        return self.answered(text, 1, said, **options)

    def with_a_door_open(self, text, gate_open=False, shared=None, launched=None, gate=None):
        """One judgement run HERE, so that a test can open a door on purpose and see what then stops a program, or no
        longer does: the gate without its filter and with the clock readable (`gate_open`), or another text of the gate
        (`gate`), a folder of the host given to every phase (`shared`). `launched` collects the mounts of every
        container the judge starts, as Docker is given them. Returns (code, what the judge said)."""
        arguments = ["--tip", str(self.tip), "--candidate", str(self.candidate({"codec/codec.c": text})), "--workdir", str(self.root / "work")]
        sees, launch = relay.Judgement.sees, relay.container.Docker.launch
        if gate_open:
            gate = gate_without("filter", "counter")

        def given(judgement, root):
            return sees(judgement, root) + ([(str(shared), "/shared", False)] if shared else [])

        def recorded(docker, command, mounts, **options):
            if launched is not None:
                launched.append(list(mounts))
            return launch(docker, command, mounts, **options)

        with contextlib.ExitStack() as doors:
            doors.enter_context(mock.patch.object(relay.Judgement, "sees", given))
            doors.enter_context(mock.patch.object(relay.container.Docker, "launch", recorded))
            if gate is not None:
                source = self.root / f"gate-{len(list(self.root.glob('gate-*.c')))}.c"
                source.write_text(gate)
                doors.enter_context(mock.patch.object(relay, "GATE_SOURCE", str(source)))
            try:
                relay.main(arguments)
                return 0, ""
            except Refusal as refusal:
                return 1, str(refusal)
            except JudgeError as error:
                return 2, str(error)

    def test_an_honest_program_is_right_and_measured_and_the_tip_against_itself_too(self):
        tip_message = len(pairs(DATA))
        code, report, err = self.judge()
        tip_total = tip_message + report["program_bytes"]
        self.assertEqual((code, report["message_bytes"], report["total_bytes"], report["tip_total_bytes"], report["gain_total_bytes"],
                          report["sure_total_bytes"], report["builds"], report["runs"], report["step"]),
                         (0, tip_message, tip_total, tip_total, 0.0, 0, 1, 3, 4), err)
        self.assertGreater(report["program_bytes"], 4096, "the program weighs what the build left: a whole executable")
        better = self.answered(BETTER, 0)
        self.assertEqual((better["tip_total_bytes"], better["builds"], better["runs"], better["step"]), (tip_total, 2, 7, 7),
                         "the tip encodes twice and decodes once; the candidate encodes twice and decodes twice")
        self.assertLess(better["message_bytes"], tip_message)
        self.assertEqual(better["total_bytes"], better["message_bytes"] + better["program_bytes"], "the figure is the message and the program")
        self.assertEqual((better["gain_total_bytes"], better["sure_total_bytes"]), (math.floor((1 - better["total_bytes"] / tip_total) * 1e6) / 1e6, 1),
                         "the gain is written rounded down: never larger than it is")
        self.assertTrue(0 <= better["encode_seconds"] < 4 and 0 <= better["decode_seconds"] < 4 and better["encode_memory_kb"] > 0)
        # the tip judged as a candidate (the hive's question about the tip): right, the same figure, and no proof of a gain
        same = self.answered(TIP_PROGRAM, 0)
        self.assertEqual((same["total_bytes"], same["gain_total_bytes"], same["sure_total_bytes"], same["runs"]), (tip_total, 0.0, 0, 7))
        # what does not reach the built program weighs nothing: a comment of a thousand letters is the same program
        commented = self.answered(TIP_PROGRAM + "/* " + "".join(random.Random(3).choice("abcdefghij") for _ in range(1000)) + " */\n", 0)
        self.assertEqual((commented["total_bytes"], commented["sure_total_bytes"]), (tip_total, 0))
        # a right program whose message is longer than the tip's: correct, and the figures say it is no gain
        worse = self.answered(STORE, 0)
        self.assertEqual(worse["message_bytes"], len(DATA))
        self.assertTrue(worse["total_bytes"] > tip_total and worse["gain_total_bytes"] < 0 and worse["sure_total_bytes"] == 0, worse)
        # the better program once it is the tip's: the next candidate is measured against it
        accepted = write_tree(self.root / "accepted", {"codec/codec.c": BETTER})
        self.assertEqual(self.judge(tip=accepted)[1]["total_bytes"], better["total_bytes"], "the same figure when it is the tip's own")
        back = self.answered(TIP_PROGRAM, 0, tip=accepted)
        self.assertEqual((back["tip_total_bytes"], back["sure_total_bytes"]), (better["total_bytes"], 0))

    def test_the_decoder_finds_the_data_nowhere_but_in_the_message(self):
        """R1 and R4. An encoder leaves the data wherever it can name a place and an empty message; a decoder looks there."""
        store = self.answered(STORE, 0)
        self.assertEqual(store["message_bytes"], len(DATA), "the same program with the message as its door is right")
        for left_at, looked_for_at in DOORS:
            with self.subTest(left_at=left_at, looked_for_at=looked_for_at):
                self.refused(door(left_at, looked_for_at), r"the candidate's first decoding: exit status 1")
        self.refused(ENVIRONMENT, r"the candidate's first decoding: exit status 1")

    def test_each_phase_has_a_file_system_of_its_own_and_an_image_that_holds_nothing(self):
        """R1, with the gate's filter LEFT OUT on purpose: a program free to make any call still finds nothing. Each
        phase is given a memory file system made for it and gone after it, and an image without a file."""
        for left_at, looked_for_at in DOORS:
            with self.subTest(left_at=left_at, looked_for_at=looked_for_at):
                code, said = self.with_a_door_open(door(left_at, looked_for_at), gate_open=True)
                self.assertEqual((code, "first decoding: exit status 1" in said), (1, True), said)
        self.assertEqual(self.with_a_door_open(ENVIRONMENT, gate_open=True)[0], 1)
        # it looks through every folder it can read, and is right only if it finds no file of any system
        self.assertEqual(self.with_a_door_open(WRONG_IF_IT_FINDS_A_SYSTEM, gate_open=True), (0, ""))
        # no folder of the host is given to two containers: seven phases, seven file systems, and every folder Docker is
        # given for a phase's container lies inside that phase's own file system; none is left after
        def phases(launched):
            """(the phase's root, the host folders Docker was given for it), for each container that ran a phase."""
            found = []
            for mounts in launched:
                targets = {target.rsplit("/", 1)[-1]: host for host, target, _ in mounts}
                if "program" in targets:
                    found.append((os.path.dirname(targets["chrono"]), [host for host, _, _ in mounts]))
            return found

        def strays(launched):
            return [host for root, hosts in phases(launched) for host in hosts if not host.startswith(root + os.sep)]

        launched = []
        self.assertEqual(self.with_a_door_open(BETTER, launched=launched), (0, ""))
        roots = [root for root, _ in phases(launched)]
        self.assertEqual((len(roots), len(set(roots))), (7, 7), "the tip's two encodings and its decoding, the candidate's two and two")
        self.assertEqual(strays(launched), [])
        self.assertFalse(any(os.path.lexists(root) for root in roots), "each is unmounted and removed when its phase ends")
        # the same check sees a host folder given to every phase, when one is (the door opened on purpose)
        launched = []
        self.with_a_door_open(BETTER, shared=self.root, launched=launched)
        self.assertEqual(strays(launched), [str(self.root)] * 7)
        self.assertNotIn(str(self.root), Path("/proc/mounts").read_text())

    def test_the_same_program_is_right_once_both_doors_are_opened_on_purpose(self):
        """The control of the two tests above. With the gate's filter left out AND one folder of the host given to
        every phase, the decoder that looks there is taken for right: the cheat works, and what refuses it in the
        judge is that neither door exists. One door alone is not enough for it."""
        shared = self.root / "shared"
        shared.mkdir()
        os.chmod(shared, 0o777)
        cheat = door("/shared/stash", "/shared/stash")
        self.assertEqual(self.with_a_door_open(cheat, gate_open=True, shared=shared), (0, ""))
        self.assertEqual((shared / "stash").read_bytes(), DATA)
        (shared / "stash").unlink()
        code, said = self.with_a_door_open(cheat, shared=shared)  # the folder is there; the gate lets no call name it
        self.assertEqual((code, "first decoding: exit status 1" in said, os.listdir(shared)), (1, True, []), said)
        code, said = self.with_a_door_open(cheat, gate_open=True)  # any call may be made; there is no folder to find
        self.assertEqual((code, "first decoding: exit status 1" in said), (1, True), said)

    def test_a_phase_makes_no_call_that_reaches_the_machine(self):
        """R4. A program that tries every way to ask the machine something or leave it something (names under each
        folder, /proc and /sys, a file's times, which pages are in memory, the clock and the wait as calls, other
        processes) and is right only if NONE was carried out."""
        self.answered(WRONG_IF_A_CALL_REACHES_THE_MACHINE, 0)
        # the control: with the gate's filter left out the same program reaches the machine, and its data is wrong
        code, said = self.with_a_door_open(WRONG_IF_A_CALL_REACHES_THE_MACHINE, gate_open=True)
        self.assertEqual((code, "does not give the data back" in said), (1, True), said)
        # the gate's own execve was the only one: another ends the process, at once
        self.refused(ANOTHER_EXECVE, r"the candidate's first encoding: ended by signal 31")
        # it means to wait an hour: no call waits, so it goes on, and is right (and no longer than any other)
        waited = self.answered(SLEEPS, 0)
        self.assertLess(waited["encode_seconds"], 4)
        # without the filter it does wait, uses no processor, and the clock stops it: the judge cannot say whose doing
        code, said = self.with_a_door_open(SLEEPS, gate_open=True)
        self.assertEqual((code, "stopped by the clock at 11 s" in said), (2, True), said)
        # it stops itself (SIGSTOP to itself): refused, so it goes on and is right; let through, it would be the clock's
        self.answered(STOPS_ITSELF, 0)
        code, said = self.with_a_door_open(STOPS_ITSELF, gate_open=True)
        self.assertEqual((code, "stopped by the clock at 11 s" in said), (2, True), said)
        # SIGABRT to itself is let through: a program that aborts ends by it
        self.refused(ABORTS, r"the candidate's first encoding: ended by signal 6")
        # another machine's calls in this machine's clothes, and the 32-bit entry: the process ends
        self.refused(X32, r"the candidate's first encoding: ended by signal 31")
        # (a kernel built without the 32-bit entry ends it with SIGSEGV before any filter sees it: refused all the same)
        self.refused(ENTRY_32, r"the candidate's first encoding: ended by signal (31|11)")
        # a filter that cannot be installed: the gate stops before the program, and the tip, judged first, says so
        code, said = self.with_a_door_open(BETTER, gate=gate_without("filter fails"))
        self.assertEqual((code, "the tip's first encoding: exit status 126" in said), (2, True), said)

    def test_a_phase_has_a_tick_clock_and_no_finer_one(self):
        """Behind the gate the time-stamp counter faults (the gate shut it before the program started), and with it
        the fine clocks of the time the kernel maps into every process; the clock call is refused besides. A TICK CLOCK
        IS LEFT, KNOWN AND NOT CLOSED: the coarse clocks read the page the kernel updates at each tick (1 to 4 ms), as
        plain memory, and nothing the gate can do takes that away. This test pins it, so that nobody reads the suite
        as proof that a phase has no clock."""
        self.refused(COUNTER, r"the candidate's first encoding: ended by signal 11")
        self.refused(CLOCK, r"the candidate's first encoding: (ended by signal 11|exit status 1)")
        self.answered(TICK_CLOCK_MOVES, 0)  # a tick clock is left: known, not closed
        # the control: with the counter left readable (the filter in place), the clock is read without a call, and
        # what catches a message that follows it is the judge's two runs
        said = rf"two encodings of the same data are not the same bytes \({len(DATA) + 8} and {len(DATA) + 8} bytes\)"
        for text in (COUNTER, CLOCK):
            code, reason = self.with_a_door_open(text, gate=gate_without("counter"))
            self.assertEqual((code, re.search(said, reason) is not None), (1, True), reason)

    def test_what_is_given_back_is_the_data_byte_for_byte(self):
        """A round trip that loses or adds one byte, anywhere, is no round trip."""
        self.refused(LAST_BYTE, rf"first decoding does not give the data back: the same length, another byte at offset {len(DATA) - 1}")
        self.refused(FIRST_BYTE, r"first decoding does not give the data back: the same length, another byte at offset 0")
        self.refused(ONE_FEWER, rf"first decoding does not give the data back: {len(DATA) - 1} bytes where the data holds {len(DATA)}")
        self.refused(ONE_MORE, rf"first decoding does not give the data back: {len(DATA) + 1} bytes where the data holds {len(DATA)}")
        self.refused(TWICE, r"first decoding: /out/data: output too large")
        self.refused(NOTHING, rf"first decoding does not give the data back: 0 bytes where the data holds {len(DATA)}")

    def test_bytes_moved_into_the_program_are_counted_there(self):
        """R2. The data in the source and an empty message: right, and every byte of it is in the program that is counted."""
        accepted = write_tree(self.root / "accepted", {"codec/codec.c": BETTER})
        tip = self.judge(tip=accepted)[1]
        report = self.answered(embedded(DATA), 0, tip=accepted)
        self.assertEqual((report["message_bytes"], report["total_bytes"]), (0, report["program_bytes"]), "nothing is free: the whole figure is the program now")
        self.assertGreater(report["program_bytes"], tip["program_bytes"] + len(DATA) - 1024, "the data is in the executable, byte for byte")
        self.assertEqual((report["sure_total_bytes"], report["gain_total_bytes"] < 0), (0, True), "heavier than a tip that codes the data at all")
        # the same bytes in a second file of the program, under a name that says nothing: the same weight, give or take the linker's rounding
        table = table_of(DATA).replace("static const", "const") + "const unsigned long kept_size = sizeof kept;\n"
        elsewhere = program(before="extern const unsigned char kept[];\nextern const unsigned long kept_size;\n",
                            encode="(void)in; (void)n; (void)out; (void)cap; return 0;",
                            decode="(void)in; (void)n; if (kept_size > cap) return (size_t)-1; memcpy(out, kept, kept_size); return kept_size;")
        code, other, err = self.judge(self.candidate({"codec/codec.c": elsewhere, "codec/zz.c": table}, accepted), tip=accepted)
        self.assertEqual((code, other["message_bytes"], other["sure_total_bytes"]), (0, 0, 0), err)
        self.assertLess(abs(other["program_bytes"] - report["program_bytes"]), 512)

    def test_a_candidate_is_the_tips_tree_but_for_the_program(self):
        """R2. Nothing but the program's files may differ: not the build, the frame, the manifest, the data, a new path."""
        for name, changes in (("the frame", {"bee/relay/main.c": (TOY / "bee/relay/main.c").read_text() + "/* changed */\n"}),
                              ("the build", {"bee/relay/build": "#!/bin/sh\ncc -O2 -DKEPT -o /out/run /src/bee/relay/main.c /src/codec/*.c\n"}),
                              ("the manifest", {"bee/relay/project.json": json.dumps({**MANIFEST, "encode_seconds": 900})}),
                              ("the data", {"bee/relay/data": b"short\n"}), ("a file elsewhere", {"kept/data": DATA}),
                              ("a link in the program", {"codec/data": lambda path: path.symlink_to("../bee/relay/data")}),
                              ("too many files", {f"codec/f{i}.c": "" for i in range(9)}), ("no program", {"codec": None}),
                              ("folders nested forty deep", {"codec/" + "d/" * 40 + "more.c": ""})):
            with self.subTest(changed=name):
                code, report, err = self.judge(self.candidate({"codec/codec.c": BETTER, **changes}))
                self.assertEqual((code, report["step"]), (1, 2), err)
        self.refused(BUILD_TAKES_THE_DATA, r"the candidate's build: exit status")
        self.refused("int toy_encode;\n", r"the candidate's build: exit status")

    def test_a_build_is_ended_whole_at_its_clock(self):
        """A build is many processes. At its clock every process of it is ended, a compiler its shell started too, and
        the processor time of all of them is counted: past its bound, the candidate's doing (1); its time unused (a
        build that waits), the machine's doubt (2). The tip's own, the project's (2)."""
        hooked = write_tree(self.root / "hooked", {"bee/relay/build": BUILD_WITH_A_HOOK,
                                                   "bee/relay/project.json": json.dumps({**MANIFEST, "build_seconds": 5})})
        # run HERE, so that the build's own container is timed, and nothing else of the judgement (whose length is the machine's)
        timed, took = relay.Judgement.timed, {}

        def clocked(judgement, *arguments, **named):
            started = time.monotonic()
            try:
                return timed(judgement, *arguments, **named)
            finally:
                took[arguments[-1] if "what" not in named else named["what"]] = time.monotonic() - started

        burner = self.candidate({"codec/build.sh": BURNS_IN_A_CHILD}, hooked)
        with mock.patch.object(relay.Judgement, "timed", clocked), \
                self.assertRaisesRegex(Refusal, r"the candidate's build: stopped after \d+\.\d s of processor time; its bound is 5 s"):
            relay.main(["--tip", str(hooked), "--candidate", str(burner), "--workdir", str(self.root / "work")])
        # ended at the gate's clock (12 s), not at the launcher's, fifteen seconds later, nor at the container's after that
        self.assertGreater(took["the candidate's build"], relay.wall_of(5) - 1)
        self.assertLess(took["the candidate's build"], relay.wall_of(5) + relay.REAPER, "ended at its clock, not at the launcher's or the container's")
        code, report, err = self.judge(self.candidate({"codec/build.sh": WAITS_IN_A_CHILD}, hooked), tip=hooked)
        self.assertEqual(code, 2, err)
        self.assertRegex(report["reason"], r"the candidate's build: stopped by the clock at 12 s with \d+\.\d s of processor time used")
        burning = write_tree(self.root / "burning", {"codec/build.sh": BURNS_IN_A_CHILD}, source=hooked)
        code, report, err = self.judge(tip=burning)
        self.assertEqual(code, 2, err)
        self.assertRegex(report["reason"], r"the tip's build: stopped after .*run twice")
        self.assertEqual(err.count(relay.ONCE_MORE), 1, "the tip's build past its time is run once more before it is said")
        # an honest build through the same hook is right, and its processes are all counted, not left running
        self.answered(BETTER, 0, tip=hooked)
        self.refused(BUILD_BLOWS_UP, r"the candidate's build: (exit status|ended by signal|stopped after)")

    def test_a_figure_that_changes_from_one_run_to_the_next_is_no_figure(self):
        """R3. Right at each run, and never the same message: bytes the kernel draws for each process, an address the
        system draws. Neither needs a call, and Docker's own filter does not let the gate switch addresses off: two
        runs catch them. (The clock, the third, the gate takes away: test_a_phase_has_no_clock.)"""
        said = rf"two encodings of the same data are not the same bytes \({len(DATA) + 8} and {len(DATA) + 8} bytes\)"
        self.refused(DRAWS, said)
        if Path("/proc/sys/kernel/randomize_va_space").read_text().strip() != "0":
            self.refused(ADDRESS, said)

    def test_a_phase_has_its_time_its_memory_and_one_process(self):
        """R4. Past its processor time, past its memory, a second process, a thread, the network: the candidate's doing."""
        self.refused(NEVER_ENCODES, r"the candidate's first encoding: stopped after \d+\.\d s of processor time; its bound is 4 s")
        self.refused(FORGES, r"the candidate's first encoding: stopped after \d+\.\d s of processor time; its bound is 4 s")
        self.refused(NEVER_DECODES, r"the candidate's first decoding: stopped after \d+\.\d s of processor time; its bound is 4 s")
        self.refused(EATS_MEMORY, r"the candidate's first encoding: (ended by signal 9 \(killed: past its memory bound, most likely\)"
                                  r"|its container was ended by the kernel)")
        self.refused(NEEDS_A_THREAD, r"the candidate's first encoding: exit status 1")
        self.refused(NEEDS_THE_NETWORK, r"the candidate's first encoding: exit status 1")
        for text in (WRONG_IF_IT_FORKS, WRONG_IF_IT_THREADS, WRONG_IF_IT_REACHES_THE_NETWORK):
            self.answered(text, 0)
        # the one file it may write has room for a message and no more
        self.refused(FLOODS, r"the candidate's first encoding: (exit status 5|/out/message: output too large)")

    def test_what_a_program_able_to_name_a_path_does_to_the_file_it_leaves(self):
        """Behind the gate a program can put nothing in the message's place. Should the gate fail, the reader behind
        it follows nothing: a link, a pipe, a folder where the message should be are refused (the filter left out)."""
        for text, said in ((LINK_FOR_MESSAGE, "/out/message: invalid output (link or special file)"),
                           (PIPE_FOR_MESSAGE, "/out/message: invalid output (not a regular file)"), (FOLDER_FOR_MESSAGE, "/out/message: invalid output")):
            code, reason = self.with_a_door_open(text, gate_open=True)
            self.assertEqual((code, said in reason), (1, True), reason)
            self.assertEqual(self.judge(self.candidate({"codec/codec.c": text}))[0], 1, "and behind the gate it cannot even try: it ends with a status")

    def test_what_is_the_projects_or_the_machines_own_fault_is_a_failure_to_judge(self):
        """Nothing the tip gets wrong is held against a candidate: a failure to judge, for the tip itself as well."""
        for name, changes, said in (
                ("a program that does not build", {"codec/codec.c": "int toy_encode;\n"}, "the tip's build: exit status"),
                ("a program past its time", {"codec/codec.c": NEVER_ENCODES}, "the tip's first encoding: stopped after"),
                ("a program whose message changes from one run to the next", {"codec/codec.c": DRAWS}, "the tip's own two encodings of the data are not the same bytes"),
                ("a program whose decoder is wrong", {"codec/codec.c": LAST_BYTE}, "the tip's own program does not give the data back"),
                ("a build script that leaves nothing", {"bee/relay/build": "#!/bin/sh\nexit 0\n"}, "the tip's build left no /out/run"),
                ("a build script that leaves a program in need of a library", {"bee/relay/build": "#!/bin/sh\ncc -O2 -o /out/run /src/bee/relay/main.c /src/codec/*.c\n"},
                 "the tip's first encoding: exit status 127"),
                ("data that is not the manifest's", {"bee/relay/data": DATA[:-1] + b"!"}, "the tip's data: not the 4270 bytes"),
                ("bounds beyond a judgement's time", {"bee/relay/project.json": json.dumps({**MANIFEST, "encode_seconds": 900, "decode_seconds": 900})}, "add up to")):
            tip = write_tree(self.root / name.replace(" ", "-").replace("'", ""), changes)
            with self.subTest(tip=name):
                for candidate in (None, self.candidate({"codec/codec.c": BETTER}, tip)):
                    code, report, err = self.judge(candidate, tip=tip)
                    self.assertEqual(code, 2, err)
                    self.assertRegex(report["reason"], said)
                    # the tip's build and phases: said to be on the tip's side, in words a report can be searched for
                    tips_own = not name.startswith(("data", "bounds"))
                    self.assertEqual(("on the tip's side (not the candidate's)" in report["reason"], report.get("fault")),
                                     (tips_own, "tip" if tips_own else None), report["reason"])
                    # past its time is run once more first; what the tip's bytes decide is not
                    self.assertEqual(relay.ONCE_MORE in err, name == "a program past its time", err)
        code, report, err = self.judge(self.candidate({"codec/codec.c": BETTER}), files=["bee/relay/main.c"])
        self.assertEqual(code, 2, err)
        self.assertRegex(report["reason"], "the task lists a path that is not the program's")

    def test_through_the_base(self):
        """The judge as the hive's judging step makes it and calls it, once the hive holds the kind."""
        import hive
        if "relay" not in hive.JUDGES:
            self.skipTest("this hive does not hold the kind yet (JUDGES)")
        judge = hive.judge_of(str(HERE.parent.parent), {"kind": "relay", "timeout_seconds": 1200}, str(self.root / "work"))
        task = {"id": "toy-0001", "files": ["codec/"]}
        trees = self.root / "trees"
        base = write_tree(trees / "base")
        itself = judge(base, base, task, "T" * 40, "T" * 40)
        tip_total = itself["report"]["total_bytes"]
        self.assertEqual((itself["code"], itself["report"]["message_bytes"], itself["report"]["sure_total_bytes"], itself["report"]["runs"]),
                         (0, len(pairs(DATA)), 0, 3))
        answer = judge(base, write_tree(trees / "right", {"codec/codec.c": BETTER}), task, "T" * 40, "C" * 40)
        self.assertEqual((answer["code"], answer["report"]["sure_total_bytes"], answer["report"]["tip_total_bytes"]), (0, 1, tip_total))
        self.assertEqual(answer["report"]["gain_total_bytes"], math.floor((1 - answer["report"]["total_bytes"] / tip_total) * 1e6) / 1e6)
        self.assertTrue(all(type(value) in (int, float) for value in answer["report"].values()), "numbers only")
        self.assertEqual(judge(base, write_tree(trees / "wrong", {"codec/codec.c": LAST_BYTE}), task, "T" * 40, "D" * 40), {"code": 1, "report": {}})
        self.assertEqual(judge(base, write_tree(trees / "more", {"codec/codec.c": BETTER, "README.md": "x"}), task, "T" * 40, "E" * 40), {"code": 1, "report": {}})
        self.assertEqual(judge(base, base, {**task, "files": ["bee/relay/main.c"]}, "T" * 40, "T" * 40)["code"], 2, "a task that is not the program's files")
        self.assertEqual(subprocess.run(hive.judge_image(str(HERE.parent.parent), "relay", str(base))).returncode, 0)


if __name__ == "__main__":
    unittest.main()
