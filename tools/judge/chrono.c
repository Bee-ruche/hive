/* Launcher and stopwatch of Bee's common judge (docs/common-judge.md; first written for minizBee's isolated judge).

   A program of the BASE, compiled without a line of the PR. It runs as process 1 of a container without
   network and launches, one by one, the commands of a plan the host wrote. Each command (the harness
   linked to the miniz being judged) is a child process: its processor time and its maximum memory are read
   by wait4, that is, measured by the kernel, not declared by the measured code.

   What the child cannot do:
   - write on the container's standard output, which carries the measurements: its descriptor 1 is /dev/null,
     2 a pipe read by chrono (its end goes to the container's error output); this process declares itself not
     « dumpable » (prctl), so that /proc/1/fd and /proc/1/mem are closed to it;
   - launch other processes: the container is limited to two processes (--pids-limit 2);
   - forge a measurement line: each line carries a token read on standard input before the first
     fork, which the child never sees;
   - know in which mode it runs (ruche-0037): whatever the mode, the same arguments, a fixed environment,
     current folder « / », 0 = a pipe carrying its parameters (fixed size); chrono has neither argument nor file.

   Instruction count (valgrind at 1): the command is valgrind --tool=cachegrind, whose summary
   (« I refs: N ») is the LAST line written on the child's error output. chrono reads that output
   through a pipe and takes the last non-empty line. The measured code can write on the same output, but
   only BEFORE the summary, which Valgrind writes last, once the program has ended; if it kills the
   process to prevent the summary, the signal is recorded and the host refuses the measurement. The file
   cachegrind.out is not read: the measured code could forge it.

   Usage: chrono; standard input gives the token (a line of 16 to 64 hexadecimal characters), a line
     « <timeout in seconds> <valgrind: 0 or 1> », then the plan: one command per line, fields separated by
     tabs: label (letters, digits, « _ » and « - »), parameters, program, arguments.
   Output: one JSON line per command, in the plan's order:
     {"token": "...", "label": "...", "code": 0, "signal": 0, "user_s": 0.0, "system_s": 0.0,
      "wall_s": 0.0, "maxrss_kb": 0, "instructions": null}
   Exit code: 0 if the plan was read and all the commands launched (whatever their code), 2 otherwise. */

#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define FIELDS_MAX 32
#define LINE_MAX_BYTES 4096
#define TAIL_MAX 65536
#define PARAMETERS 256 /* the child's parameters: a record of fixed size, whatever the mode */

static char *const ENVIRONMENT[] = {"HOME=/tmp", "LC_ALL=C", "PATH=/usr/bin:/bin", NULL}; /* the same for each child */
static volatile pid_t current_child = 0;

static void on_alarm(int received_signal)
{
    (void)received_signal;
    if (current_child > 0)
        kill(current_child, SIGKILL);
}

static void die(const char *message)
{
    fprintf(stderr, "chrono: %s\n", message);
    exit(2);
}

static double seconds(struct timeval t)
{
    return (double)t.tv_sec + (double)t.tv_usec * 1e-6;
}

static double now(void)
{
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (double)t.tv_sec + (double)t.tv_nsec * 1e-9;
}

/* Last non-empty line of the error output: « ==PID== I refs: 1,234,567 » (Cachegrind's summary).
   Returns the number, or -1 if the last line is not a well-formed summary. */
static long long instructions_read(const char *text, size_t n)
{
    size_t end = n, start;
    const char *p;
    long long total = 0;
    int digits = 0;
    while (end > 0 && (text[end - 1] == '\n' || text[end - 1] == '\r' || text[end - 1] == ' '))
        end--;
    start = end;
    while (start > 0 && text[start - 1] != '\n')
        start--;
    p = strstr(text + start, "I refs:");
    if (!p || p >= text + end)
        return -1;
    for (p += 7; p < text + end; p++)
    {
        if (*p == ' ' && !digits)
            continue;
        if (*p == ',')
            continue;
        if (*p < '0' || *p > '9' || total > 100000000000000000LL)
            return -1;
        total = total * 10 + (*p - '0');
        digits++;
    }
    return digits ? total : -1;
}

static int valid_label(const char *e)
{
    if (!*e || strlen(e) > 64)
        return 0;
    for (; *e; e++)
        if (!((*e >= 'a' && *e <= 'z') || (*e >= 'A' && *e <= 'Z') || (*e >= '0' && *e <= '9') || *e == '_' || *e == '-'))
            return 0;
    return 1;
}

int main(int argc, char **argv)
{
    char token[80], line[LINE_MAX_BYTES];
    unsigned timeout = 0;
    int valgrind = 0;
    static char tail[TAIL_MAX + 1];
    char (*lines)[LINE_MAX_BYTES] = NULL;
    size_t count = 0, capacity = 0, i, n;
    int null_fd;
    struct sigaction action;

    umask(0); /* inherited by the child: the host must be able to erase what it writes (another user) */
    /* First: nobody (same uid) opens /proc/<this process>/fd or /mem any more. */
    if (prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) != 0)
        die("prctl(PR_SET_DUMPABLE) failed");

    (void)argv;
    if (argc != 1 || chdir("/") != 0)
        die("usage: chrono, without argument (token, options and plan on standard input)");

    if (!fgets(token, sizeof(token), stdin))
        die("token missing on standard input");
    token[strcspn(token, "\r\n")] = 0;
    n = strlen(token);
    if (n < 16 || n > 64 || strspn(token, "0123456789abcdef") != n)
        die("invalid token");
    if (!fgets(line, sizeof(line), stdin) || sscanf(line, "%u %d", &timeout, &valgrind) != 2)
        die("options missing (timeout, valgrind)");

    while (fgets(line, sizeof(line), stdin))
    {
        line[strcspn(line, "\r\n")] = 0;
        if (!line[0])
            continue;
        if (count == capacity)
        {
            capacity = capacity ? 2 * capacity : 16;
            lines = realloc(lines, capacity * sizeof(*lines));
            if (!lines)
                die("out of memory");
        }
        memcpy(lines[count++], line, LINE_MAX_BYTES);
    }

    null_fd = open("/dev/null", O_RDWR | O_CLOEXEC);
    if (null_fd < 0)
        die("/dev/null not found");
    /* Standard input (the pipe that carried the token) closes here: the child does not inherit it. */
    if (dup2(null_fd, 0) < 0)
        die("dup2 failed");

    memset(&action, 0, sizeof(action));
    action.sa_handler = on_alarm;
    sigaction(SIGALRM, &action, NULL);

    for (i = 0; i < count; i++)
    {
        char *fields[FIELDS_MAX + 1], *saved = NULL, *piece, parameters[PARAMETERS];
        int nfields = 0, wait_status = 0, err_pipe[2] = {-1, -1}, in_pipe[2] = {-1, -1};
        size_t filled = 0;
        long long instructions = -1;
        struct rusage ru;
        double start, end;
        pid_t pid;

        for (piece = strtok_r(lines[i], "\t", &saved); piece && nfields < FIELDS_MAX;
             piece = strtok_r(NULL, "\t", &saved))
            fields[nfields++] = piece;
        fields[nfields] = NULL;
        if (nfields < 3 || !valid_label(fields[0]))
            die("invalid plan line");

        /* The parameters (the mode included): PARAMETERS bytes, the line padded with spaces and ended by a line
           feed, in a pipe the child reads, then closes. */
        n = strlen(fields[1]);
        if (n >= PARAMETERS)
            die("parameters too long");
        memset(parameters, ' ', PARAMETERS - 1);
        memcpy(parameters, fields[1], n);
        parameters[PARAMETERS - 1] = '\n';
        if (pipe2(err_pipe, O_CLOEXEC) != 0 || pipe2(in_pipe, O_CLOEXEC) != 0 || write(in_pipe[1], parameters, PARAMETERS) != PARAMETERS
            || close(in_pipe[1]) != 0)
            die("pipes failed");
        fflush(stdout);
        start = now();
        pid = fork();
        if (pid < 0)
            die("fork failed");
        if (pid == 0)
        {
            if (dup2(in_pipe[0], 0) < 0 || dup2(null_fd, 1) < 0 || dup2(err_pipe[1], 2) < 0)
                _exit(126);
            execve(fields[2], fields + 2, ENVIRONMENT);
            _exit(127);
        }
        current_child = pid;
        close(in_pipe[0]);
        if (timeout)
            alarm(timeout);
        {
            /* Reads everything the child writes on its error output; keeps only the end. */
            char chunk[8192];
            close(err_pipe[1]);
            for (;;)
            {
                ssize_t got = read(err_pipe[0], chunk, sizeof(chunk));
                if (got < 0 && errno == EINTR)
                    continue;
                if (got <= 0)
                    break;
                if ((size_t)got >= TAIL_MAX)
                {
                    memcpy(tail, chunk + got - TAIL_MAX, TAIL_MAX);
                    filled = TAIL_MAX;
                }
                else
                {
                    if (filled + (size_t)got > TAIL_MAX)
                    {
                        size_t keep = TAIL_MAX - (size_t)got;
                        memmove(tail, tail + filled - keep, keep);
                        filled = keep;
                    }
                    memcpy(tail + filled, chunk, (size_t)got);
                    filled += (size_t)got;
                }
            }
            close(err_pipe[0]);
            tail[filled] = 0;
            if (valgrind)
                instructions = instructions_read(tail, filled);
            fwrite(tail, 1, filled, stderr); /* the child's log, for the host */
        }
        while (wait4(pid, &wait_status, 0, &ru) < 0)
            if (errno != EINTR)
                die("wait4 failed");
        alarm(0);
        current_child = 0;
        end = now();

        printf("{\"token\": \"%s\", \"label\": \"%s\", \"code\": %d, \"signal\": %d, \"user_s\": %.6f, "
               "\"system_s\": %.6f, \"wall_s\": %.6f, \"maxrss_kb\": %ld, \"instructions\": ",
               token, fields[0], WIFEXITED(wait_status) ? WEXITSTATUS(wait_status) : -1,
               WIFSIGNALED(wait_status) ? WTERMSIG(wait_status) : 0, seconds(ru.ru_utime), seconds(ru.ru_stime),
               end - start, ru.ru_maxrss);
        if (instructions >= 0)
            printf("%lld}\n", instructions);
        else
            printf("null}\n");
        fflush(stdout);
    }
    free(lines);
    return 0;
}
