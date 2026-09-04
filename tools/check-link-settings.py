# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Two link-setting failures that produce no diagnostic at all.

    python tools/check-link-settings.py

1. AN -s SETTING PASSED TWICE WITH CONFLICTING VALUES.

emcc takes the LAST assignment and says nothing about the earlier one. The hand-written
prefix of a captured link line is not the whole story: cmake appends upstream FreeCAD's own
target link options after it, in the spaced "-s NAME=VALUE" form, and those win.

This has happened twice. ALLOW_MEMORY_GROWTH was passed =1 then =0, and the linked JS came
out full of GROWABLE_HEAP_F32() accessors -- the growth-on form, which invalidated every
hand-derived offset in tools/patch-freecad-js.py. STACK_SIZE was passed 32MB by
configure-gui-weh.sh and then 5MB by upstream's cmake, so the deliberate 32MB never once
took effect and production ran a 5 MB main stack for its whole life. Neither was visible in
the build output; both were found by reading the recorded command by hand.

2. THE HEAP CEILING DISAGREEING ACROSS THE THREE PLACES THAT STATE IT.

The browser cannot ask the module how large its heap may become: emscripten keeps the
Memory object closure-private and Module.wasmMemory is not set in this build. So
freecad-gui.html carries the ceiling as a literal, and its own comment says it is "kept in
step with -sMAXIMUM_MEMORY in the link command" -- by hand.

When those drift, nothing breaks loudly. The memory-pressure warning simply computes
used/cap against the wrong cap, so it force-saves and warns at the wrong moment, or never.
That feature exists to save the user's work just before an unavoidable abort, and it fails
silently in exactly the direction that loses the document.
"""
import glob
import io
import sys

INTENTIONAL_OVERRIDES = {
    # The prefix relaxes undefined symbols so archive ordering can be worked out; the tail
    # restores strictness, so the shipped link is the strict one.
    'ERROR_ON_UNDEFINED_SYMBOLS': '1',
}
SUFFIXES = {'KB': 1024, 'MB': 1024 * 1024, 'GB': 1024 * 1024 * 1024}
SEPARATORS = '"\'`;|&()<>{}'


def normalise(value):
    v = value.strip()
    for suffix, mult in SUFFIXES.items():
        if v.upper().endswith(suffix):
            head = v[:-len(suffix)]
            if head.isdigit():
                return str(int(head) * mult)
    return v


def settings_in(text):
    """Yield (name, value) for every -s assignment, in order. Both emcc spellings."""
    tokens = text.split()
    i = 0
    while i < len(tokens):
        tok, assignment = tokens[i], None
        if tok == '-s' and i + 1 < len(tokens):
            assignment = tokens[i + 1]
            i += 1
        elif tok.startswith('-s') and len(tok) > 2 and '=' in tok:
            assignment = tok[2:]
        if assignment and '=' in assignment:
            name, _, value = assignment.partition('=')
            if name.replace('_', '').isalnum():
                yield name, value
        i += 1


def check_duplicates():
    problems = []
    for path in sorted(glob.glob('scratchpad/linkcmds/*.sh')):
        with io.open(path, encoding='utf-8', errors='replace') as fh:
            for lineno, line in enumerate(fh, 1):
                if '-s' not in line:
                    continue
                seen = {}
                for name, value in settings_in(line):
                    prev = seen.get(name)
                    if prev is not None and normalise(prev) != normalise(value):
                        allowed = INTENTIONAL_OVERRIDES.get(name)
                        if allowed is None or normalise(allowed) != normalise(value):
                            problems.append(
                                '%s:%d: %s is passed as %s and then %s; emcc takes the last '
                                'silently. Remove one, or declare it in '
                                'INTENTIONAL_OVERRIDES.' % (path, lineno, name, prev, value))
                    seen[name] = value
    return problems


def _first_value_after(text, marker, stop):
    """The digits following `marker`, up to any character in `stop`. No regex needed."""
    at = text.find(marker)
    if at < 0:
        return None
    rest = text[at + len(marker):].lstrip(' =')
    out = ''
    for ch in rest:
        if ch.isdigit():
            out += ch
        elif out or ch in stop:
            break
    return out or None


def check_heap_agreement():
    sources = {}

    link = 'scratchpad/linkcmds/fc-linkcmd-weh.sh'
    text = io.open(link, encoding='utf-8', errors='replace').read()
    for name, value in settings_in(text):
        if name == 'MAXIMUM_MEMORY':
            sources[link + ' (-sMAXIMUM_MEMORY)'] = normalise(value)
            break

    cfg = 'configure-gui-weh.sh'
    v = _first_value_after(io.open(cfg, encoding='utf-8', errors='replace').read(),
                           'FCWEB_HEAP_MAX_BYTES:-', '}')
    if v:
        sources[cfg + ' (FCWEB_HEAP_MAX_BYTES default)'] = v

    html = 'play-gui/freecad-gui.html'
    v = _first_value_after(io.open(html, encoding='utf-8', errors='replace').read(),
                           'var FCWEB_HEAP_MAX_BYTES', ';')
    if v:
        sources[html + ' (FCWEB_HEAP_MAX_BYTES)'] = v

    if len(sources) < 3:
        return ['heap ceiling: only found %d of the 3 declarations (%s). If one moved, this '
                'check must move with it.' % (len(sources), ', '.join(sorted(sources)))]
    if len(set(sources.values())) > 1:
        lines = ['heap ceiling disagrees across the places that state it:']
        for where in sorted(sources):
            lines.append('    %-58s %s' % (where, sources[where]))
        lines.append('    The browser cannot query the real ceiling, so the JS literal must '
                     'match the link flag or the memory warning fires at the wrong time.')
        return [chr(10).join(lines)]
    return []


def main():
    problems = check_duplicates() + check_heap_agreement()
    if problems:
        for p in problems:
            print(p, file=sys.stderr)
        return 1
    print('link settings: no conflicting duplicates, heap ceiling agrees in all 3 places')
    return 0


if __name__ == '__main__':
    sys.exit(main())
