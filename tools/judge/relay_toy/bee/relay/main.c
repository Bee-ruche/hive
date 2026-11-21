/* The toy's frame, the project's own (a candidate cannot change it): « run encode » and « run decode » read
   descriptor 3 to its end and write descriptor 4. The judge's gate opened both before the program started, and the
   program can open nothing itself. What lies between is the program's: toy_encode and toy_decode, in codec/, which
   return the bytes written, or (size_t)-1. */
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

size_t toy_encode(const unsigned char *in, size_t n, unsigned char *out, size_t cap);
size_t toy_decode(const unsigned char *in, size_t n, unsigned char *out, size_t cap);

#define MOST ((size_t)1 << 20)

int main(int argc, char **argv)
{
    unsigned char *in = malloc(MOST), *out = malloc(MOST);
    size_t n = 0, k, written = 0;
    int encode;

    if (argc != 2 || !in || !out)
        return 2;
    encode = !strcmp(argv[1], "encode");
    if (!encode && strcmp(argv[1], "decode"))
        return 2;
    while (n < MOST) {
        ssize_t got = read(3, in + n, MOST - n);
        if (got < 0)
            return 3;
        if (got == 0)
            break;
        n += (size_t)got;
    }
    k = encode ? toy_encode(in, n, out, MOST) : toy_decode(in, n, out, MOST);
    if (k == (size_t)-1 || k > MOST)
        return 1;
    while (written < k) {
        ssize_t put = write(4, out + written, k - written);
        if (put <= 0)
            return 5;
        written += (size_t)put;
    }
    return 0;
}
