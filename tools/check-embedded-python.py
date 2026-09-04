#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Validate the Python that play-gui/freecad-gui.html ships inside JS string literals.

The startup warmup is a whole Python program embedded in a JS string. Two different
mistakes there are silent, and both were made on 2026-09-03 while fixing the Addon Manager:

1. A SYNTAX ERROR in the Python. The whole block dies and the only evidence is one line:

       <class 'SyntaxError'>: invalid syntax. Perhaps you forgot a comma? (<string>, line 35)

   Everything that block installs is then absent -- the UseVBO/SaveThumbnail preferences,
   the MainWindow wrapper pin, the addons proxy host, the JSPI dialog shim. The app still
   boots and looks normal, so it resurfaces later as unrelated bugs: native Qt dialogs
   instead of HTML ones, meshes on the slow immediate-mode path, the Addon Manager
   aborting the engine. Caused by writing a backslash escape in the payload: this is a JS
   string, so a backslash-n unescapes to a real newline and ends the Python string early.

2. AN UNBALANCED DOUBLE QUOTE. repr() switches to double quotes as soon as the text
   contains an apostrophe, and that quote closes the enclosing JS string. The Python
   compiles perfectly; the PAGE does not parse, and nothing loads at all:

       Uncaught SyntaxError: Unexpected identifier

   Compiling the payload cannot see this, which is why the quote count is checked too.

    python3 tools/check-embedded-python.py
"""
import pathlib
import re
import sys

HTML = pathlib.Path(__file__).resolve().parent.parent / "play-gui" / "freecad-gui.html"

BACKSLASH = chr(92)
QUOTE = chr(34)

# JS string escapes that matter inside these payloads.
UNESCAPE = [(BACKSLASH * 2, "\x00"), (BACKSLASH + "n", "\n"), (BACKSLASH + "t", "\t"),
            (BACKSLASH + QUOTE, QUOTE), (BACKSLASH + "'", "'"), ("\x00", BACKSLASH)]

STMT = re.compile(r'var\s+(code|py|src)\s*=\s*' + QUOTE)


def unescape(js):
    for a, b in UNESCAPE:
        js = js.replace(a, b)
    return js


def walk_js_concat(line, start):
    """Walk  "seg" + expr + "seg" ... ;  and report where it actually ends.

    Returns (ok, reason). Counting quotes cannot catch the failure this guards: repr()
    emits a matched PAIR of double quotes, so the total stays even while the first of them
    still closes the JS string early. Only walking the chain sees that the text after a
    segment is neither `+` nor `;`.
    """
    i = start
    while True:
        if i >= len(line) or line[i] != QUOTE:
            return False, "expected a string segment at offset %d" % i
        i += 1
        while i < len(line):                      # scan to the segment's closing quote
            if line[i] == BACKSLASH:
                i += 2
                continue
            if line[i] == QUOTE:
                break
            if line[i] == "\n":
                return False, "a string segment runs past the end of its line"
            i += 1
        else:
            return False, "unterminated string segment"
        i += 1                                    # past the closing quote
        while i < len(line) and line[i] in " \t\r\n":
            i += 1
        if i >= len(line):
            return False, "statement ends without a semicolon"
        if line[i] == ";":
            return True, ""
        if line[i] != "+":
            return False, ("after a string segment the statement continues with %r, which "
                           "means that segment closed early" % line[i:i + 30])
        i += 1                                    # past '+', skip the JS expression
        depth = 0
        while i < len(line):
            c = line[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            elif c == "'":                        # a quoted bit inside the expression
                i += 1
                while i < len(line) and line[i] != "'":
                    i += 1
            elif c == QUOTE and depth == 0:
                break
            elif c == "+" and depth == 0:
                pass
            i += 1
        while i < len(line) and line[i] in " \t\r\n+":
            i += 1


def check_quote_balance(text):
    """Every payload statement must end where the source says it does."""
    bad = []
    for m in STMT.finditer(text):
        ok, why = walk_js_concat(text, m.end() - 1)
        if not ok:
            bad.append((m.group(1), text[:m.start()].count("\n") + 1, why))
    return bad


def find_payloads(text):
    """Yield (label, python_source) for each embedded Python program."""
    pattern = re.compile(r'var\s+(code|py|src)\s*=\s*' + QUOTE + r'(.*?)' + QUOTE + r'\s*;',
                         re.S)
    for m in pattern.finditer(text):
        raw = m.group(2)
        # Join ADJACENT string literals first: ""a" + "b"" is one string, not an
        # expression, and folding it to a placeholder invents a syntax error that is not in
        # the shipped program (it did exactly that to the Addon Manager loader).
        raw = re.sub(QUOTE + r"\s*[+]\s*" + QUOTE, "", raw)
        # Fold `" + <expr> + "` into a placeholder so JS concatenation does not read as a
        # truncated string. Without this the checker invents errors that are not there.
        folded = re.sub(QUOTE + r'\s*\+.*?\+\s*' + QUOTE, "PLACEHOLDER", raw, flags=re.S)
        src = unescape(folded)
        if "import" in src or "print(" in src:
            yield ("var %s (line %d)" % (m.group(1), text[:m.start()].count("\n") + 1), src)


def main():
    text = HTML.read_text(encoding="utf-8", errors="surrogateescape")
    bad = 0

    for name, line, why in check_quote_balance(text):
        bad += 1
        print("::error::var %s at line %d: %s. The page will not parse at all. A Python "
              "literal containing an apostrophe causes this, because repr() then wraps it "
              "in double quotes -- keep quote characters out of the payload."
              % (name, line, why))

    payloads = list(find_payloads(text))
    if not payloads:
        print("::error::found no embedded Python in %s -- the extractor is broken, not the page"
              % HTML.name)
        return 1

    for label, src in payloads:
        try:
            compile(src, "<embedded:%s>" % label, "exec")
            print("  ok    %s  (%d lines)" % (label, src.count("\n") + 1))
        except SyntaxError as e:
            bad += 1
            print("::error::embedded Python in %s does not compile: %s (line %s)"
                  % (label, e.msg, e.lineno))
            lines = src.split("\n")
            for n in range(max(0, (e.lineno or 1) - 3), min(len(lines), (e.lineno or 1) + 2)):
                mark = ">>" if n == (e.lineno or 1) - 1 else "  "
                print("   %s %4d | %s" % (mark, n + 1, lines[n][:120]))

    if bad:
        print("\n%d problem(s) that would break startup silently." % bad)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
