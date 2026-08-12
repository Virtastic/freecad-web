#!/usr/bin/env python3
"""Compare two screenshots. The renderer must be pixel-identical after an optimisation
that is only supposed to remove no-op GL calls; report the worst channel difference and
how many pixels differ at all, so a real regression cannot hide behind an average."""
import sys
from PIL import Image, ImageChops


def main():
    a = Image.open(sys.argv[1]).convert('RGB')
    b = Image.open(sys.argv[2]).convert('RGB')
    if a.size != b.size:
        print('SIZE MISMATCH %s vs %s' % (a.size, b.size))
        return 1
    d = ImageChops.difference(a, b)
    bbox = d.getbbox()
    worst = max(d.getextrema(), key=lambda t: t[1])[1]
    hist = d.convert('L').histogram()
    differing = sum(hist[1:])
    total = a.size[0] * a.size[1]
    print('worst channel delta = %d, differing pixels = %d/%d (%.3f%%), bbox=%s'
          % (worst, differing, total, 100.0 * differing / total, bbox))
    return 0 if worst == 0 else 2


if __name__ == '__main__':
    sys.exit(main())
