#!/usr/bin/env python3
"""Rewrite CalculiX's Fortran into something f2c (FORTRAN 77 only) can parse.

CalculiX writes F90 constructs into fixed-form .f files. f2c rejects them, which is the
only thing standing between ccx and a wasm build. Three transformations, all local and
mechanical:

  1. `!` comments            -> `C` comments (or dropped, if trailing). Skipped inside
                                character literals.
  2. `cycle` / `cycle name`  -> `goto <label>` where the label sits immediately BEFORE the
                                loop terminator, so the iteration finishes normally.
  3. `exit`  / `exit name`   -> `goto <label>` where the label sits immediately AFTER the
                                loop terminator.

Handles all three loop forms ccx uses: block `do ... enddo`, labelled `do 100 ...` ending
on `100 continue`, and named `outer: do ... enddo outer`. Both statements also appear as
the action of a logical IF (`if (x) cycle`), which is handled by rewriting the trailing
token rather than the whole line.

Emitted labels start at 8000 and skip any label already present in the file.
(Not 90000: f2c mis-resolves 5-digit labels, even though F77 allows them.)

Usage: f77ify.py <in.f> <out.f>
"""
import re
import sys

# statement-level matches (applied to the code part of a non-comment line)
RE_NAMED_DO = re.compile(r'^\s*([A-Za-z]\w*)\s*:\s*do\b', re.I)
RE_LABELED_DO = re.compile(r'^\s*do\s+(\d+)\b', re.I)
RE_DO_WHILE = re.compile(r'^\s*do\s+while\s*\((.*)\)\s*$', re.I)
RE_BARE_DO = re.compile(r'^\s*do\s*$', re.I)
RE_BLOCK_DO = re.compile(r'^\s*do\b', re.I)
RE_ENDDO = re.compile(r'^\s*end\s*do\b\s*(\w+)?\s*$', re.I)
RE_CYCLE = re.compile(r'\bcycle\b\s*([A-Za-z]\w*)?\s*$', re.I)
RE_EXIT = re.compile(r'\bexit\b\s*([A-Za-z]\w*)?\s*$', re.I)


def split_fixed(line):
    """Return (label, cont, code, is_comment) for a fixed-form line."""
    if not line.strip():
        return '', ' ', '', False
    if line[0] in 'cC*!dD' and not line[:1].isspace():
        # d/D is a debug-line marker in some dialects; treat only c/C/*/! as comment
        if line[0] in 'cC*!':
            return '', ' ', line, True
    label = line[:5] if len(line) >= 5 else line.ljust(5)
    cont = line[5] if len(line) > 5 else ' '
    code = line[6:] if len(line) > 6 else ''
    return label, cont, code, False


def strip_bang(code):
    """Drop a trailing `!` comment, honouring character literals."""
    out, quote = [], None
    for ch in code:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
            out.append(ch)
            continue
        if ch == '!':
            break
        out.append(ch)
    return ''.join(out).rstrip()


def used_labels(lines):
    seen = set()
    for ln in lines:
        lab, _, _, is_c = split_fixed(ln)
        if is_c:
            continue
        lab = lab.strip()
        if lab.isdigit():
            seen.add(int(lab))
    return seen



def split_top(text, sep=','):
    """Split on `sep` at paren depth 0, ignoring character literals."""
    parts, buf, depth, quote = [], [], 0, None
    for ch in text:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
            continue
        if ch in "'\"":
            quote = ch
        elif ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append(''.join(buf))
            buf = []
            continue
        buf.append(ch)
    parts.append(''.join(buf))
    return parts


def open_quote_after(code, quote):
    """Quote state at end of `code`, given the state on entry. Fixed-form string
    literals continue across lines, so this has to be threaded, not restarted."""
    for ch in code:
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\'\"":
            quote = ch
        elif ch == '!':
            break
    return quote


def split_semicolons(text):
    """`a=1;b=2` on one line -> two lines. F90 lets ccx pack statements; f2c does not.

    A `;` inside a character literal is not a separator -- and ccx has literals that
    open on one line and close on a continuation line, so quote state is carried."""
    out, quote = [], None
    for raw in text.splitlines():
        label, cont, code, is_c = split_fixed(raw)
        if is_c or not raw.strip():
            out.append(raw)
            continue
        if cont in (' ', '0'):
            quote = None                      # new statement, fresh quote state
        entry, quote = quote, open_quote_after(code, quote)
        if entry is not None or ';' not in strip_bang(code):
            out.append(raw)
            continue
        pieces = [p.strip() for p in split_top(strip_bang(code), ';') if p.strip()]
        if not pieces:
            out.append(raw)
            continue
        out.append(label + cont + '   ' + pieces[0])
        out.extend('      ' + p for p in pieces[1:])
    return '\n'.join(out) + '\n'


# F90 attribute declarations: `real*8, dimension(3,3), intent(in) :: a, b`.
# f2c only knows `real*8 a(3,3), b(3,3)`. `parameter` needs its own statement.
RE_ATTR_DECL = re.compile(
    r'^\s*((?:double\s+precision|real|integer|logical|character|complex)'
    r'(?:\s*\*\s*\d+)?(?:\s*\([^)]*\))?)\s*(?:,(.*?))?::(.*)$', re.I)
RE_DIMENSION = re.compile(r'^\s*dimension\s*\((.*)\)\s*$', re.I)


def rewrite_attr_decl(body):
    """Return replacement statements, or None to leave the declaration alone."""
    m = RE_ATTR_DECL.match(body)
    if not m:
        return None
    base, attrs, names = m.group(1).strip(), m.group(2) or '', m.group(3)
    dims, is_param = None, False
    for a in split_top(attrs):
        a = a.strip()
        if not a:
            continue
        md = RE_DIMENSION.match(a)
        if md:
            dims = md.group(1).strip()
        elif re.match(r'^parameter$', a, re.I):
            is_param = True
        elif re.match(r'^(intent\s*\(.*\)|save|target|contiguous|value|optional)$', a, re.I):
            pass                      # no f2c equivalent, and none is load-bearing here
        else:
            return None               # allocatable, pointer, ... genuinely unsupported
    decls, params = [], []
    for n in split_top(names):
        n = n.strip()
        if not n:
            continue
        if is_param and '=' in n:
            lhs, rhs = n.split('=', 1)
            decls.append(lhs.strip())
            params.append('%s=%s' % (lhs.strip(), rhs.strip()))
        elif dims and '(' not in n:
            decls.append('%s(%s)' % (n, dims))
        else:
            decls.append(n)
    if not decls:
        return None
    out = ['%s %s' % (base, ', '.join(decls))]
    if params:
        out.append('parameter (%s)' % ', '.join(params))
    return out


# --- F90 array constructors -------------------------------------------------
# ccx initialises its Gauss-point tables with
#     x = reshape(( /v1,v2,.../ ), ( /d1,d2/ ))
# and plain  x = (/v1,v2,.../).  f2c knows neither `reshape` nor `(/ /)`.
# Both are rewritten into explicit element assignments. reshape fills in
# column-major order, which is also Fortran's storage order, so the value
# sequence maps directly onto (1,1),(2,1)...(d1,1),(1,2)...
RE_RESHAPE = re.compile(
    r'^(\s*)([A-Za-z]\w*)\s*=\s*reshape\s*\(\s*\(\s*/(.*?)/\s*\)\s*,'
    r'\s*\(\s*/(.*?)/\s*\)\s*\)\s*$', re.I | re.S)
RE_VECTOR = re.compile(r'^(\s*)([A-Za-z]\w*)\s*=\s*\(\s*/(.*?)/\s*\)\s*$', re.I | re.S)


RE_NUMLIT = re.compile(r'^[-+]?(\d+\.?\d*|\.\d+)([dDeE][-+]?\d+)?$')


def _emit_assigns(name, pairs):
    """pairs = [(subscript_text, value)]. All-literal tables are emitted as DATA so
    they remain declarations; anything else has to be executable assignment."""
    if all(RE_NUMLIT.match(v) for _, v in pairs):
        return _emit(['data %s(%s) /%s/' % (name, sub, val) for sub, val in pairs])
    return _emit(['%s(%s)=%s' % (name, sub, val) for sub, val in pairs])


def _emit(stmts):
    """Emit statements as fixed-form lines, wrapping past column 72."""
    out = []
    for st in stmts:
        body = st.strip()
        line = '      ' + body
        while len(line) > 72:
            cut = line.rfind(',', 0, 72)
            if cut <= 6:
                break
            out.append(line[:cut + 1])
            line = '     &' + line[cut + 1:]
        out.append(line)
    return out


def join_continuations(lines):
    """Yield (logical_statement, [original_lines]) preserving comments as-is."""
    buf, owned = None, []
    for raw in lines:
        lab, cont, code, is_c = split_fixed(raw)
        if is_c or not raw.strip():
            if buf is not None:
                yield buf, owned
                buf, owned = None, []
            yield None, [raw]
            continue
        if cont not in (' ', '0') and buf is not None:
            buf += strip_bang(code)
            owned.append(raw)
            continue
        if buf is not None:
            yield buf, owned
        buf, owned = (lab + ' ' + strip_bang(code)), [raw]
    if buf is not None:
        yield buf, owned


def expand_array_ctors(text):
    lines = text.splitlines()
    low = text.lower()
    if 'reshape' not in low and '(/' not in text and '::' not in text:
        return text
    out = []
    for stmt, originals in join_continuations(lines):
        if stmt is None:
            out.extend(originals)
            continue
        label, body = stmt[:5], stmt[5:]
        m = RE_RESHAPE.match(body)
        if m:
            name, vals, dims = m.group(2), m.group(3), m.group(4)
            v = [x.strip() for x in vals.split(',') if x.strip()]
            d = [x.strip() for x in dims.split(',') if x.strip()]
            try:
                d = [int(x) for x in d]
            except ValueError:
                out.extend(originals)
                continue
            if len(d) == 2 and len(v) == d[0] * d[1]:
                pairs, k = [], 0
                for j in range(1, d[1] + 1):        # column-major
                    for i in range(1, d[0] + 1):
                        pairs.append(('%d,%d' % (i, j), v[k]))
                        k += 1
                out.extend(_emit_assigns(name, pairs))
                continue
            if len(d) == 1 and len(v) == d[0]:
                out.extend(_emit_assigns(name, [(str(i + 1), v[i]) for i in range(d[0])]))
                continue
            out.extend(originals)
            continue
        rep = rewrite_attr_decl(body)
        if rep is not None:
            out.extend(_emit(rep))
            continue

        m = RE_VECTOR.match(body)
        if m and 'reshape' not in body.lower():
            name, vals = m.group(2), m.group(3)
            v = [x.strip() for x in vals.split(',') if x.strip()]
            out.extend(_emit_assigns(name, [(str(i + 1), v[i]) for i in range(len(v))]))
            continue
        out.extend(originals)
    return '\n'.join(out) + '\n'


RE_OPEN_POSITION = re.compile(r"(\bopen\s*\(.*?)\bposition\s*=", re.I)


RE_FLUSH = re.compile(r'^(\s{6,})flush\s*\(\s*\d+\s*\)\s*$', re.I | re.M)


RE_INCLUDE = re.compile(r'^\s{5,}include\s', re.I)
RE_DATA_STMT = re.compile(r'^\s{5,}data\s', re.I)


def hoist_includes(text):
    """Move `include` lines above the first DATA statement.

    ccx includes gauss.f (a table of declarations + initialisers) *after* its own
    DATA statements. gfortran tolerates that; f2c enforces the F77 order and rejects
    the included declarations as "declaration after DATA".
    """
    lines = text.splitlines()
    first_data = next((i for i, l in enumerate(lines) if RE_DATA_STMT.match(l)), None)
    if first_data is None:
        return text
    incs = [i for i, l in enumerate(lines[first_data:], first_data) if RE_INCLUDE.match(l)]
    if not incs:
        return text
    moved = [lines[i] for i in incs]
    rest = [l for i, l in enumerate(lines) if i not in set(incs)]
    return '\n'.join(rest[:first_data] + moved + rest[first_data:]) + '\n'


def convert(text):
    text = hoist_includes(text)
    text = RE_FLUSH.sub(r'\1continue', text)
    text = RE_OPEN_POSITION.sub(r"\1access=", text)
    text = split_semicolons(text)
    text = expand_array_ctors(text)
    lines = text.splitlines()
    taken = used_labels(lines)
    counter = [8000]

    def new_label():
        while counter[0] in taken:
            counter[0] += 1
        lab = counter[0]
        taken.add(lab)
        counter[0] += 1
        return lab

    out = []
    stack = []          # frames: dict(kind, name, endlabel, cyc, exi)
    pending_after = []  # labels to emit after the current statement line

    for raw in lines:
        label, cont, code, is_comment = split_fixed(raw)

        if is_comment:
            # `!`-style comment line -> C so f2c accepts it
            out.append('C' + raw[1:] if raw[0] == '!' else raw)
            continue
        if not raw.strip():
            out.append(raw)
            continue

        code = strip_bang(code)
        if not code.strip():
            # line was only a trailing comment
            if label.strip() or cont not in (' ', '0'):
                out.append(label + cont + code)
            continue

        stmt = code.strip()
        is_cont = cont not in (' ', '0')

        # --- loop terminators ---------------------------------------------
        lab_txt = label.strip()
        if stack and lab_txt.isdigit() and stack[-1]['kind'] == 'labeled' \
                and int(lab_txt) == stack[-1]['endlabel']:
            fr = stack.pop()
            if fr['cyc']:
                out.append('%5d continue' % fr['cyc'])
            out.append(label + cont + code)
            if fr['exi']:
                out.append('%5d continue' % fr['exi'])
            continue

        if stack and not is_cont and RE_ENDDO.match(stmt):
            fr = stack.pop()
            if fr['cyc']:
                out.append('%5d continue' % fr['cyc'])
            if fr['kind'] == 'top':
                out.append('      goto %d' % fr['top'])
                if fr['exi']:
                    out.append('%5d continue' % fr['exi'])
                continue
            # `enddo name` is also F90-only
            out.append(label + cont + '      enddo'.strip().rjust(0)
                       if False else label + cont + re.sub(
                           r'^(\s*)end\s*do\b.*$', r'\1enddo', code, flags=re.I))
            if fr['exi']:
                out.append('%5d continue' % fr['exi'])
            continue

        # --- cycle / exit --------------------------------------------------
        if stack:
            m = RE_CYCLE.search(stmt)
            if m and not re.search(r'\bcycle\s*\(', stmt, re.I):
                target = pick_frame(stack, m.group(1))
                if target is not None:
                    if not target['cyc']:
                        target['cyc'] = new_label()
                    code = RE_CYCLE.sub('goto %d' % target['cyc'], code)
                    out.append(label + cont + code)
                    continue
            m = RE_EXIT.search(stmt)
            if m and not re.search(r'\bexit\s*\(', stmt, re.I):
                target = pick_frame(stack, m.group(1))
                if target is not None:
                    if not target['exi']:
                        target['exi'] = new_label()
                    code = RE_EXIT.sub('goto %d' % target['exi'], code)
                    out.append(label + cont + code)
                    continue

        # --- loop openers ---------------------------------------------------
        if not is_cont:
            loop_name = None
            mn = RE_NAMED_DO.match(stmt)
            if mn:
                # strip the `name:` prefix (f2c has no construct names) and then fall
                # through, because the rest may be any DO form including a bare one
                loop_name = mn.group(1).lower()
                code = re.sub(r'^(\s*)[A-Za-z]\w*\s*:\s*', r'\1', code, count=1)
                stmt = code.strip()
            ml = RE_LABELED_DO.match(stmt)
            if ml and not RE_DO_WHILE.match(stmt):
                stack.append(dict(kind='labeled', name=loop_name,
                                  endlabel=int(ml.group(1)), cyc=None, exi=None))
                out.append(label + cont + code)
                continue
            mw = RE_DO_WHILE.match(stmt)
            if mw or RE_BARE_DO.match(stmt):
                # f2c has no infinite DO or DO WHILE. Rewrite as
                #   <top> continue / [if (.not.(cond)) goto <exit>] ... goto <top>
                top = new_label()
                fr = dict(kind='top', name=loop_name, endlabel=None,
                          cyc=None, exi=None, top=top)
                if mw:
                    fr['exi'] = new_label()
                    out.append('%5d continue' % top)
                    out.append('      if (.not.(%s)) goto %d' % (mw.group(1), fr['exi']))
                else:
                    out.append('%5d continue' % top)
                stack.append(fr)
                continue

            if RE_BLOCK_DO.match(stmt) and not RE_DO_WHILE.match(stmt):
                stack.append(dict(kind='block', name=loop_name,
                                  endlabel=None, cyc=None, exi=None))
                out.append(label + cont + code)
                continue
            if loop_name is not None:
                out.append(label + cont + code)
                continue

        out.append(label + cont + code)

    return '\n'.join(out) + '\n'


def pick_frame(stack, name):
    if not name:
        return stack[-1]
    for fr in reversed(stack):
        if fr['name'] == name.lower():
            return fr
    return stack[-1]


def selftest():
    """Smallest check that fails if any transformation regresses."""
    def conv(src):
        return convert(''.join('      ' + l + '\n' for l in src))

    # reshape -> DATA, column-major
    out = conv(["g=reshape((/1.d0,2.d0,3.d0,4.d0/),(/2,2/))"])
    assert 'data g(2,1) /2.d0/' in out and 'data g(1,2) /3.d0/' in out, out
    # non-constant values stay executable
    assert 'x(1)=a' in conv(["x=(/a,b/)"])
    # `;` inside a literal continued from the previous line is not a separator
    two = ("      write(*,*) 'a" + chr(10) + "     &b; c'" + chr(10))
    assert len(convert(two).strip().splitlines()) == 2, convert(two)
    # ...but a real `;` does split
    assert len(conv(["i=1;j=2"]).strip().splitlines()) == 2
    # named infinite DO becomes a label + goto, and `exit` leaves it
    out = conv(["loop1: do", "if(i.eq.1) exit loop1", "enddo"])
    assert 'do' not in out.replace('endo', ''), out
    assert out.count('continue') == 2 and 'goto' in out, out
    # attribute declaration
    assert 'real*8 a(3,3), b(3,3)' in conv(["real*8, dimension(3,3), intent(in) :: a, b"])
    assert 'integer n' in conv(["integer, parameter :: n=3"])
    # labels stay 4-digit: f2c mis-resolves 5-digit ones
    for lab in re.findall(r'^\s*(\d+) continue', conv(["do", "cycle", "enddo"]), re.M):
        assert len(lab) <= 4, lab
    print('f77ify selftest OK')


def main():
    if len(sys.argv) == 2 and sys.argv[1] == '--selftest':
        return selftest()
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, 'r', errors='replace') as f:
        text = f.read()
    with open(dst, 'w') as f:
        f.write(convert(text))


if __name__ == '__main__':
    main()
