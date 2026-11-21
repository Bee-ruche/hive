/* The gate of Bee's third kind of judge (relay.py, docs/relay-judge.md): what stands between the hive's launcher
   (chrono.c) and a program under judgement, in a phase's container.

   A program of the judged project is native code: whatever its source's language promises, it must be taken for a
   process that makes any system call it likes. The container keeps it from the network, from other processes and
   from the judge's files. It does not keep it from the machine's own state: names it can look up, files of /proc and
   /sys, times, which pages are in memory. Two phases of one judgement run on one machine, one after the other, and
   whatever the first can change that the second can read is a way round the message.

   So the gate, a program of the hive compiled without a line of the project's:
   1. opens the one file the phase reads (descriptor 3) and creates the one file it writes (descriptor 4);
   2. installs a filter on system calls (seccomp) that leaves the process: reading and writing descriptors it already
      holds, its own memory, its own signals, and ending. Every other call is answered « not permitted » without
      being carried out: no path is ever looked up, no file of the machine opened, no state of the machine asked for,
      no process or thread made;
   3. starts the program, by the one call to execve the filter lets through.

   That one execve is told from any other by where its three arguments point: a page the gate maps at an address it
   draws from the system's randomness, which stops existing when the program's image replaces the gate's. Any other
   execve ends the process: there is one try. A signal is let through only to the process itself, and only SIGABRT
   (how a C library or a language's runtime aborts): a process that could stop itself (SIGSTOP) would wait.

   Before the filter, the gate also makes the processor's time-stamp counter fault for the process and its
   successor (prctl PR_SET_TSC: the setting survives execve). The time of day the kernel maps into every process
   (the vDSO) is read through that counter, so its fine clocks fault too; where the machine's clock is not read
   through it, the vDSO falls back to the system call, which the filter refuses. A TICK CLOCK IS LEFT, AND THE GATE
   CANNOT TAKE IT AWAY: the vDSO's coarse clocks (time(), CLOCK_REALTIME_COARSE, CLOCK_MONOTONIC_COARSE) read no
   counter, only the page the kernel updates at each tick (1 to 4 ms), as plain memory (tried: it reads, and moves).
   Whether some machines have other counters a process can read that this setting does not cover is not established.
   What it still has without a call, besides: the addresses the system draws for its memory (Docker's own filter does not let
   the gate switch that off) and sixteen bytes the kernel draws for every process; a program that writes them into
   its message is caught by the judge's two runs.

   Usage: gate <file to read> <file to write> <program> [arguments…]      (a phase: run by chrono)
          gate --build <seconds> <program> [arguments…]                   (a build: run by chrono)
   Exit: the program's own; 126 if the gate could not set itself up, 127 if the program could not be started.
   x86-64 only: on another machine it does not compile, and the judge fails to judge.

   THE BUILD. A build is many processes (a shell, a compiler, a linker), and the hive's launcher ends its own child
   alone: a compiler that outlived it would keep running, and keep the launcher waiting. So for a build the gate is
   the launcher's child: it becomes the reaper of every process the build leaves behind (PR_SET_CHILD_SUBREAPER),
   starts the build, and at <seconds> ends every process of the container but the launcher (kill(-1)), reaps them all,
   and ends itself by SIGKILL; when the build ends by itself, it ends whatever the build left running the same way,
   and exits with the build's status. Every process it reaped counts in what the launcher reads of it from the kernel
   (wait4 counts a child's own reaped children): the build's processor time is all of theirs, the killed ones too. No
   filter is installed for a build: it is the tip's own script, and compilers need the system. */

#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <signal.h>
#include <sys/random.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>

#if !defined(__x86_64__)
#error "the gate is written for x86-64"
#endif

#define PAGE 4096
#define INSTRUCTIONS 200
#define REFUSED (SECCOMP_RET_ERRNO | EPERM)

static struct sock_filter filter[INSTRUCTIONS];
static unsigned short count;

static void fail(const char *message)
{
    fprintf(stderr, "gate: %s\n", message);
    _exit(126);
}

static void emit(unsigned short code, unsigned char if_true, unsigned char if_false, unsigned int value)
{
    if (count >= INSTRUCTIONS)
        fail("the filter is longer than its table");
    filter[count].code = code;
    filter[count].jt = if_true;
    filter[count].jf = if_false;
    filter[count].k = value;
    count++;
}

static void load(unsigned int offset)
{
    emit(BPF_LD | BPF_W | BPF_ABS, 0, 0, offset);
}

static void answer(unsigned int value)
{
    emit(BPF_RET | BPF_K, 0, 0, value);
}

/* The call `number` is let through. (The number is the loaded word, here and after.) */
static void allow(unsigned int number)
{
    emit(BPF_JMP | BPF_JEQ | BPF_K, 0, 1, number);
    answer(SECCOMP_RET_ALLOW);
}

/* The call `number` is let through only when each of the `n` arguments named in `which` is exactly the value given;
   otherwise it is answered `otherwise`. An argument is 64 bits, two words, the low one first: `words` says whether
   both are held to the value (2: an address) or the low one alone (1: an int, whose high word a caller may leave
   as it finds it). */
static void allow_when(unsigned int number, int n, const int *which, const uint64_t *values, int words, unsigned int otherwise)
{
    int i;
    emit(BPF_JMP | BPF_JEQ | BPF_K, 0, (unsigned char)(3 * words * n + 1), number);
    for (i = 0; i < n; i++) {
        unsigned int at = (unsigned int)(offsetof(struct seccomp_data, args) + 8 * (size_t)which[i]);
        load(at);
        emit(BPF_JMP | BPF_JEQ | BPF_K, 1, 0, (unsigned int)(values[i] & 0xFFFFFFFFu));
        answer(otherwise);
        if (words == 2) {
            load(at + 4);
            emit(BPF_JMP | BPF_JEQ | BPF_K, 1, 0, (unsigned int)(values[i] >> 32));
            answer(otherwise);
        }
    }
    answer(SECCOMP_RET_ALLOW);
    load(offsetof(struct seccomp_data, nr)); /* the number again, for the tests that follow */
}

/* A page at an address nobody can guess, which holds what execve is given: the program's path, its arguments, an
   empty environment. */
static char *hidden_page(void)
{
    int tries;
    for (tries = 0; tries < 64; tries++) {
        uint64_t drawn;
        void *wanted, *got;
        if (getrandom(&drawn, sizeof drawn, 0) != (ssize_t)sizeof drawn)
            fail("the system gave no randomness");
        wanted = (void *)(uintptr_t)(drawn & 0x00007FFFFFFFF000ull);
        got = mmap(wanted, PAGE, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
        if (got == wanted && got != MAP_FAILED)
            return got;
        if (got != MAP_FAILED)
            munmap(got, PAGE);
    }
    fail("no page could be mapped at a drawn address");
    return NULL;
}

static volatile sig_atomic_t timed_out;

static void on_alarm(int received)
{
    (void)received;
    timed_out = 1;
}

/* Every process of the container but the launcher (process 1) and this one, ended and reaped. */
static void end_the_others(void)
{
    kill(-1, SIGKILL);
    while (waitpid(-1, NULL, 0) > 0 || errno == EINTR)
        ;
}

static int build(int argc, char **argv)
{
    struct sigaction action;
    unsigned seconds;
    int status = 0;
    pid_t child;

    if (argc < 4 || (seconds = (unsigned)strtoul(argv[2], NULL, 10)) == 0)
        fail("usage: gate --build <seconds> <program> [arguments]");
    if (prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0)
        fail("the build's processes could not be held");
    memset(&action, 0, sizeof action);
    action.sa_handler = on_alarm;
    sigaction(SIGALRM, &action, NULL); /* (no SA_RESTART: waitpid returns at the clock) */
    child = fork();
    if (child < 0)
        fail("fork failed");
    if (child == 0) {
        signal(SIGALRM, SIG_DFL);
        execv(argv[3], argv + 3);
        _exit(127);
    }
    alarm(seconds);
    while (waitpid(child, &status, 0) < 0) {
        if (timed_out) {
            end_the_others();
            signal(SIGKILL, SIG_DFL);
            kill(getpid(), SIGKILL); /* the launcher reads « stopped at the clock » */
            _exit(137);
        }
        if (errno != EINTR)
            fail("waitpid failed");
    }
    alarm(0);
    end_the_others(); /* whatever the build left running */
    if (WIFSIGNALED(status)) {
        signal(WTERMSIG(status), SIG_DFL);
        kill(getpid(), WTERMSIG(status));
        _exit(128 + WTERMSIG(status));
    }
    return WEXITSTATUS(status);
}

int main(int argc, char **argv)
{
    static const int allowed[] = {
        SYS_read, SYS_write, SYS_readv, SYS_writev, SYS_pread64, SYS_pwrite64, SYS_lseek, SYS_close, /* descriptors it holds */
        SYS_mmap, SYS_munmap, SYS_mprotect, SYS_mremap, SYS_brk,                                     /* its own memory */
        SYS_rt_sigaction, SYS_rt_sigprocmask, SYS_rt_sigreturn, SYS_sigaltstack,                     /* its own signals */
        SYS_arch_prctl, SYS_set_tid_address, SYS_set_robust_list, SYS_getpid, SYS_gettid,            /* what a C library's start asks */
        SYS_getrandom,                                                                               /* (or that start reads the clock instead) */
        SYS_exit, SYS_exit_group,
    };
    static const int first_three[] = {0, 1, 2}, first_and_third[] = {0, 2}, third[] = {2};
    struct sock_fprog program;
    uint64_t given[3], self[2], none = 0;
    char *page, **arguments, **environment;
    size_t used = 0, i;
    int in, out, null, fd;

    if (argc > 1 && !strcmp(argv[1], "--build"))
        return build(argc, argv);
    if (argc < 4)
        fail("usage: gate <file to read> <file to write> <program> [arguments]");

    /* 1. The two files, and nothing else open: 0 and 1 nowhere, 2 the launcher's pipe, 3 to read, 4 to write. */
    null = open("/dev/null", O_RDWR);
    in = open(argv[1], O_RDONLY | O_NOFOLLOW);
    out = open(argv[2], O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0644);
    if (null < 0 || in < 0 || out < 0)
        fail("the phase's files could not be opened");
    if (dup2(null, 0) < 0 || dup2(null, 1) < 0)
        fail("dup2 failed");
    /* (moved out of the way first, in case one of them sits where the other goes) */
    in = fcntl(in, F_DUPFD, 10);
    out = fcntl(out, F_DUPFD, 10);
    if (in < 0 || out < 0 || dup2(in, 3) != 3 || dup2(out, 4) != 4)
        fail("the phase's files could not be placed");
    if (syscall(SYS_close_range, 5U, ~0U, 0U) != 0) /* every other descriptor; a kernel without close_range: the first 1024 */
        for (fd = 5; fd < 1024; fd++)
            close(fd);

    /* Should memory run short, the kernel ends this process (the program) rather than the launcher that measures it. */
    fd = open("/proc/self/oom_score_adj", O_WRONLY);
    if (fd >= 0) {
        (void)!write(fd, "1000", 4); /* (if it fails, no harm: the kernel chooses the larger process anyway) */
        close(fd);
    }

    /* 2. What execve will be given, in a page at a drawn address. */
    page = hidden_page();
    arguments = (char **)(void *)(page + PAGE / 2);
    environment = arguments + (argc - 3) + 1;
    if ((size_t)(argc - 3 + 2) * sizeof(char *) > PAGE / 2)
        fail("too many arguments");
    for (i = 0; i + 3 < (size_t)argc; i++) {
        size_t length = strlen(argv[i + 3]) + 1;
        if (used + length > PAGE / 2)
            fail("the arguments are too long");
        memcpy(page + used, argv[i + 3], length);
        arguments[i] = page + used;
        used += length;
    }
    arguments[argc - 3] = NULL;
    environment[0] = NULL;

    /* The processor's time-stamp counter faults from now on, for this process and the program it becomes. */
    if (prctl(PR_SET_TSC, PR_TSC_SIGSEGV, 0, 0, 0) != 0)
        fail("the time-stamp counter could not be shut");

    /* 3. The filter. Another machine's calls, or the 32-bit ones in this machine's clothes: the process ends. */
    load(offsetof(struct seccomp_data, arch));
    emit(BPF_JMP | BPF_JEQ | BPF_K, 1, 0, AUDIT_ARCH_X86_64);
    answer(SECCOMP_RET_KILL_PROCESS);
    load(offsetof(struct seccomp_data, nr));
    emit(BPF_JMP | BPF_JGE | BPF_K, 0, 1, 0x40000000u);
    answer(SECCOMP_RET_KILL_PROCESS);
    for (i = 0; i < sizeof allowed / sizeof *allowed; i++)
        allow((unsigned int)allowed[i]);
    /* execve: this gate's own, once; any other ends the process. */
    given[0] = (uint64_t)(uintptr_t)page;
    given[1] = (uint64_t)(uintptr_t)arguments;
    given[2] = (uint64_t)(uintptr_t)environment;
    allow_when(SYS_execve, 3, first_three, given, 2, SECCOMP_RET_KILL_PROCESS);
    /* SIGABRT to itself (how a C library or a runtime aborts), and nothing else: no other process, no other signal. */
    self[0] = (uint64_t)getpid();
    self[1] = SIGABRT;
    allow_when(SYS_tgkill, 2, first_and_third, self, 1, REFUSED);
    /* poll, as a language's start asks whether its three descriptors are open: at once, never as a way to wait. */
    allow_when(SYS_poll, 1, third, &none, 1, REFUSED);
    answer(REFUSED);

    program.len = count;
    program.filter = filter;
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0 || prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &program) != 0)
        fail("the filter could not be installed");

    execve(page, arguments, environment);
    _exit(127);
}
