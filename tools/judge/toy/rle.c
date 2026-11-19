/* rle: the toy project's reference implementation (see rle.h). Simple and slow on purpose. */
#include "rle.h"

#include <string.h>

static void rle_crc_table(unsigned long table[256])
{
    unsigned long n, k, c;
    for (n = 0; n < 256; n++) {
        c = n;
        for (k = 0; k < 8; k++)
            c = (c & 1) ? (0xEDB88320UL ^ (c >> 1)) : (c >> 1);
        table[n] = c;
    }
}

static unsigned long rle_crc(const unsigned long table[256], const unsigned char *p, size_t n)
{
    unsigned long c = 0xFFFFFFFFUL;
    size_t i;
    for (i = 0; i < n; i++)
        c = table[(c ^ p[i]) & 0xFF] ^ (c >> 8);
    return (c ^ 0xFFFFFFFFUL) & 0xFFFFFFFFUL;
}

static void rle_write32(unsigned char *p, unsigned long v)
{
    p[0] = (unsigned char)(v & 0xFF);
    p[1] = (unsigned char)((v >> 8) & 0xFF);
    p[2] = (unsigned char)((v >> 16) & 0xFF);
    p[3] = (unsigned char)((v >> 24) & 0xFF);
}

static unsigned long rle_read32(const unsigned char *p)
{
    return (unsigned long)p[0] | ((unsigned long)p[1] << 8) | ((unsigned long)p[2] << 16) | ((unsigned long)p[3] << 24);
}

size_t rle_bound(size_t n)
{
    return 8 + n + n / 128 + 1;
}

static size_t rle_literals(const unsigned char *src, size_t start, size_t end, unsigned char *dst, size_t o)
{
    while (start < end) {
        size_t k = end - start;
        if (k > 128)
            k = 128;
        dst[o++] = (unsigned char)(k - 1);
        memcpy(dst + o, src + start, k);
        o += k;
        start += k;
    }
    return o;
}

size_t rle_compress(const unsigned char *src, size_t n, unsigned char *dst)
{
    unsigned long table[256];
    size_t i = 0, start = 0, o = 4;
    rle_crc_table(table);
    rle_write32(dst, (unsigned long)n);
    while (i < n) {
        size_t run = 1;
        while (i + run < n && run < 130 && src[i + run] == src[i])
            run++;
        if (run >= 3) {
            o = rle_literals(src, start, i, dst, o);
            dst[o++] = (unsigned char)(run + 125);
            dst[o++] = src[i];
            i += run;
            start = i;
        } else {
            i += run;
        }
    }
    o = rle_literals(src, start, n, dst, o);
    rle_write32(dst + o, rle_crc(table, src, n));
    return o + 4;
}

int rle_decompress(const unsigned char *src, size_t n, unsigned char *dst, size_t cap, size_t *produced)
{
    unsigned long table[256];
    size_t i = 4, o = 0, length;
    *produced = 0;
    if (n < 8)
        return RLE_INVALID;
    length = rle_read32(src);
    if (length > cap)
        return RLE_BUFFER_TOO_SMALL;
    while (i < n - 4 && o < length) {
        unsigned c = src[i++];
        if (c < 128) {
            size_t k = (size_t)c + 1;
            if (i + k > n - 4 || o + k > length) {
                *produced = o;
                return RLE_INVALID;
            }
            memcpy(dst + o, src + i, k);
            i += k;
            o += k;
        } else {
            size_t k = (size_t)c - 125;
            if (i >= n - 4 || o + k > length) {
                *produced = o;
                return RLE_INVALID;
            }
            memset(dst + o, src[i++], k);
            o += k;
        }
    }
    *produced = o;
    if (o != length || i != n - 4)
        return RLE_INVALID;
    rle_crc_table(table);
    if (rle_crc(table, dst, o) != rle_read32(src + n - 4))
        return RLE_INVALID;
    return RLE_OK;
}
