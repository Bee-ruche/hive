/* The toy project's (rle) harness for the Bee common judge (tools/judge/).

   Compiled WITH the rle to judge, in a container without network, and runs only there. It judges nothing:
   it reads the inputs the host prepared, calls rle, and writes the raw outputs; the plugin
   (project.py, on the host) checks them with its own reference codec and compares them with the base's.

   Usage: execution, without argument; descriptor 0 carries a line
     « <mode> <input_folder> <output_folder> » (common judge, docs/common-judge.md).
     <input_folder>/list: « f NAME SIZE » (raw file f/NAME) or « z NAME BUFFER » (stream z/NAME,
                          BUFFER = size of the output buffer given to rle_decompress)
     modes: verify, compression, decompression; the work is the same in every mode, each input's side
     chooses it: for each f: c/NAME; for each z: d/NAME (bytes produced) and e/NAME (status), so that
     each output is checked the same way, whatever the mode.
   The judged code cannot tell whether it is verified or measured: before the first call to rle, the harness
   reads its parameters to the end of the pipe, copies them, then erases their text, its arguments and its
   environment.
   Exit code: 0 if all the outputs were written, 2 otherwise. */

#include "rle.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

extern char **environ;

static char inputs[256], outputs[256];

static void die(const char *message, const char *detail)
{
    fprintf(stderr, "execution: %s: %s\n", message, detail);
    exit(2);
}

static unsigned char *read_input(const char *type, const char *name, size_t *length)
{
    char p[4096];
    FILE *f;
    unsigned char *buffer = NULL;
    size_t size = 0, capacity = 0, got;
    snprintf(p, sizeof(p), "%s/%s/%s", inputs, type, name);
    f = fopen(p, "rb");
    if (!f)
        die("unreadable input", p);
    do {
        if (size == capacity) {
            capacity = capacity ? 2 * capacity : 65536;
            buffer = (unsigned char *)realloc(buffer, capacity);
            if (!buffer)
                die("out of memory", p);
        }
        got = fread(buffer + size, 1, capacity - size, f);
        size += got;
    } while (got > 0);
    fclose(f);
    *length = size;
    return buffer;
}

static void write_output(const char *folder, const char *name, const void *data, size_t length)
{
    char p[4096];
    FILE *f;
    snprintf(p, sizeof(p), "%s/%s", outputs, folder);
    if (mkdir(p, 0777) != 0 && errno != EEXIST)
        die("cannot make the folder", p);
    snprintf(p, sizeof(p), "%s/%s/%s", outputs, folder, name);
    f = fopen(p, "wb");
    if (!f || (length && fwrite(data, 1, length, f) != length) || fclose(f) != 0)
        die("cannot write", p);
}

static void compress_one(const char *name)
{
    size_t n, m;
    unsigned char *src = read_input("f", name, &n);
    size_t bound = rle_bound(n);
    unsigned char *dst;
    /* A harness never sizes a buffer from the judged code alone: the format's bound, known
       here, is a minimum (adversarial review of 28 October). */
    if (bound < 8 + n + n / 128 + 1)
        die("bound too small", name);
    dst = (unsigned char *)malloc(bound);
    if (!dst)
        die("out of memory", name);
    m = rle_compress(src, n, dst);
    write_output("c", name, dst, m);
    free(src);
    free(dst);
}

static void decompress_one(const char *name, size_t buffer)
{
    size_t n, produced = 0;
    unsigned char *src = read_input("z", name, &n);
    unsigned char *dst = (unsigned char *)malloc(buffer ? buffer : 1);
    int code;
    if (!dst)
        die("out of memory", name);
    code = rle_decompress(src, n, dst, buffer, &produced);
    write_output("d", name, dst, produced);
    {
        char text[64];
        int k = snprintf(text, sizeof(text), "%d %zu\n", code, produced);
        write_output("e", name, text, (size_t)k);
    }
    free(src);
    free(dst);
}

/* Reads the parameters on descriptor 0 to the end of the pipe, copies them, then erases their text, the
   arguments and the environment: afterwards, nothing in the process tells the mode. */
static void parameters(int argc, char **argv)
{
    char text[1024], mode[64];
    size_t n = 0;
    ssize_t got;
    int i, ok;
    char **e;
    while (n < sizeof(text) - 1 && ((got = read(0, text + n, sizeof(text) - 1 - n)) > 0 || (got < 0 && errno == EINTR)))
        n += got > 0 ? (size_t)got : 0;
    text[n] = 0;
    ok = n < sizeof(text) - 1 && sscanf(text, "%63s %255s %255s", mode, inputs, outputs) == 3 && (strcmp(mode, "verify") == 0
         || strcmp(mode, "compression") == 0 || strcmp(mode, "decompression") == 0);
    explicit_bzero(text, sizeof(text));
    explicit_bzero(mode, sizeof(mode));
    for (i = 0; i < argc; i++)
        explicit_bzero(argv[i], strlen(argv[i]));
    for (e = environ; e && *e; e++)
        explicit_bzero(*e, strlen(*e));
    if (environ)
        environ[0] = NULL;
    if (!ok || argc != 1)
        die("usage", "execution, parameters « <mode> <inputs> <outputs> » on descriptor 0");
}

int main(int argc, char **argv)
{
    char p[4096], line[256], type, name[64];
    unsigned long long size;
    FILE *list;
    umask(0); /* the host (another user) must be able to erase what the harness writes */
    parameters(argc, argv);
    snprintf(p, sizeof(p), "%s/list", inputs);
    list = fopen(p, "r");
    if (!list)
        die("unreadable list", p);
    while (fgets(line, sizeof(line), list)) {
        if (sscanf(line, " %c %63s %llu", &type, name, &size) != 3)
            continue;
        if (type == 'f')
            compress_one(name);
        else if (type == 'z')
            decompress_one(name, (size_t)size);
    }
    fclose(list);
    return 0;
}
