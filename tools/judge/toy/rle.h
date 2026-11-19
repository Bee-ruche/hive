/* rle: a small run-length codec, the toy project of the Bee common judge's meta-tests (tools/judge/).

   Format: the original's length (4 bytes, little-endian), then blocks, then the original's CRC-32
   (4 bytes, little-endian, zlib's polynomial). A block starts with a byte c:
     c < 128   : c + 1 literal bytes follow;
     c >= 128  : the next byte is repeated c - 125 times (3 to 130 times). */
#ifndef RLE_H
#define RLE_H

#include <stddef.h>

#define RLE_OK 0
#define RLE_INVALID (-1)
#define RLE_BUFFER_TOO_SMALL (-2)

/* Largest size of rle_compress's output for n bytes. */
size_t rle_bound(size_t n);

/* Compresses src (n bytes) into dst (at least rle_bound(n) bytes); returns the size written. */
size_t rle_compress(const unsigned char *src, size_t n, unsigned char *dst);

/* Decompresses src (n bytes) into dst (cap bytes). *produced receives the number of bytes written, even on
   an error. Returns RLE_OK, RLE_INVALID or RLE_BUFFER_TOO_SMALL. */
int rle_decompress(const unsigned char *src, size_t n, unsigned char *dst, size_t cap, size_t *produced);

#endif
