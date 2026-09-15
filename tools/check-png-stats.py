# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Round-trip boot-gate.py's PNG reader against every filter type it claims to handle.

    python tools/check-png-stats.py

The `ui` scenario judges whether the application painted a window by decoding a Playwright
screenshot, and the gate container has nothing installed but playwright -- so that decoder
is hand-written, and a bug in it would show up as a rendering verdict rather than as a
decoder error. This writes PNGs with each of the five filter types, reads them back, and
checks that a blank frame is called blank.
"""
import importlib.util
import struct
import sys
import zlib


def load_png_stats():
    spec = importlib.util.spec_from_file_location('_bootgate', 'tools/boot-gate.py')
    mod = importlib.util.module_from_spec(spec)
    sys.modules['_bootgate'] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        # boot-gate.py imports playwright and the session helpers at module scope; neither
        # is present in the lint job, and neither is needed to exercise a pure function.
        pass
    return getattr(mod, 'png_stats', None)


def chunk(kind, body):
    return (struct.pack('>I', len(body)) + kind + body
            + struct.pack('>I', zlib.crc32(kind + body) & 0xFFFFFFFF))


def encode(width, height, channels, filt, pixels):
    stride = width * channels
    raw = bytearray()
    prev = bytearray(stride)
    for y in range(height):
        line = bytearray(pixels[y * stride:(y + 1) * stride])
        enc = bytearray(line)
        if filt == 1:
            for i in range(stride - 1, channels - 1, -1):
                enc[i] = (line[i] - line[i - channels]) & 0xFF
        elif filt == 2:
            for i in range(stride):
                enc[i] = (line[i] - prev[i]) & 0xFF
        elif filt == 3:
            for i in range(stride):
                left = line[i - channels] if i >= channels else 0
                enc[i] = (line[i] - ((left + prev[i]) >> 1)) & 0xFF
        elif filt == 4:
            for i in range(stride):
                a = line[i - channels] if i >= channels else 0
                b = prev[i]
                c = prev[i - channels] if i >= channels else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                enc[i] = (line[i] - pred) & 0xFF
        raw += bytes([filt]) + enc
        prev = line
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 6 if channels == 4 else 2, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr)
            + chunk(b'IDAT', zlib.compress(bytes(raw))) + chunk(b'IEND', b''))


def main():
    png_stats = load_png_stats()
    if png_stats is None:
        print('::error::tools/boot-gate.py no longer defines png_stats, which the ui '
              'scenario decodes its screenshots with')
        return 1

    width, height, channels = 40, 30, 4
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            pixels += bytes([(x * 6) % 256, (y * 8) % 256, (x * y) % 256, 255])

    rc = 0
    for filt in (0, 1, 2, 3, 4):
        st = png_stats(encode(width, height, channels, filt, pixels))
        if st is None or (st['w'], st['h']) != (width, height) or st['distinct'] < 50:
            print('::error::png_stats mis-read a filter-%d PNG: %r' % (filt, st))
            rc = 1
        else:
            print('  ok  filter %d: %dx%d, %d distinct colours'
                  % (filt, st['w'], st['h'], st['distinct']))

    blank = bytes([12, 12, 12, 255] * (width * height))
    st = png_stats(encode(width, height, channels, 0, blank))
    if not st or st['distinct'] != 1 or st['dominant'] != 1.0 or st['dark'] != 1.0:
        print('::error::png_stats did not recognise a blank frame as blank: %r' % (st,))
        rc = 1
    else:
        print('  ok  a blank frame reads as 1 colour over 100% of the image')

    if png_stats(b'not a png at all') is not None:
        print('::error::png_stats returned stats for something that is not a PNG')
        rc = 1
    else:
        print('  ok  non-PNG input returns None rather than a verdict')

    if rc == 0:
        print('png_stats reads all five filter types and calls a blank frame blank')
    return rc


if __name__ == '__main__':
    sys.exit(main())
