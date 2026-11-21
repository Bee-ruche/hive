/* The toy's program at its tip: pairs (count, byte). Long runs shrink; everything else doubles. */
#include <stddef.h>
#include <string.h>

size_t toy_encode(const unsigned char *in, size_t n, unsigned char *out, size_t cap)
{
    size_t i = 0, k = 0;
    while (i < n) {
        size_t run = 1;
        while (i + run < n && run < 255 && in[i + run] == in[i])
            run++;
        if (k + 2 > cap)
            return (size_t)-1;
        out[k++] = (unsigned char)run;
        out[k++] = in[i];
        i += run;
    }
    return k;
}

size_t toy_decode(const unsigned char *in, size_t n, unsigned char *out, size_t cap)
{
    size_t i, k = 0;
    if (n % 2)
        return (size_t)-1;
    for (i = 0; i < n; i += 2) {
        size_t run = in[i];
        if (!run || k + run > cap)
            return (size_t)-1;
        memset(out + k, in[i + 1], run);
        k += run;
    }
    return k;
}
