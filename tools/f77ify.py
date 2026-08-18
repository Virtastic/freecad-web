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
import os
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



def is_cont_line(cont):
    return cont not in (' ', '0')


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
            total = 1
            for x in d:
                total *= x
            if d and len(v) == total:
                # Column-major: the FIRST subscript varies fastest. Any rank -- ccx has
                # rank-3 tables (xlocal.f reshapes into (/3,1,6/)).
                subs = [[]]
                for dim in d:
                    subs = [pre + [i] for i in range(1, dim + 1) for pre in subs]
                # the comprehension above varies `pre` fastest, which is what we want
                # only once it is rebuilt in index order:
                subs = []
                idx = [1] * len(d)
                for _ in range(total):
                    subs.append(list(idx))
                    for axis in range(len(d)):
                        idx[axis] += 1
                        if idx[axis] <= d[axis]:
                            break
                        idx[axis] = 1
                out.extend(_emit_assigns(
                    name, [(','.join(str(x) for x in sub), v[k])
                           for k, sub in enumerate(subs)]))
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


# F2003 spells a one-element array constructor [x]; arpack-ng passes scalars that way
# (`call ivout(logfil, 1, [mxiter], ...)`). For a single scalar the address handed over
# is the same, so the brackets just come off. Only applied to code, never comments, and
# only to a lone identifier/number -- multi-element constructors would need a temporary.
RE_BRACKET_SCALAR = re.compile(r'\[\s*([A-Za-z_]\w*|\d+)\s*\]')

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




RE_CHAR_DECL = re.compile(
    # length may be *132, *(*), (len=..) or absent
    r'^\s{6,}character\s*(?:\*\s*\(\s*\*\s*\)|\*\s*\d+|\([^)]*\))?\s*(?:::)?\s*(.*)$',
    re.I)


def character_names(lines):
    """Names declared CHARACTER.

    `setname(1:15)='contactelements'` is a SUBSTRING assignment, not an array section --
    rewriting it as a loop over elements silently corrupts the string. The only way to
    tell the two apart is the declaration, so character names are collected up front and
    excluded from every section rule.
    """
    names = set()
    # joined statements, not raw lines: ccx wraps declarations, and a name on a
    # continuation line (multistages' `indeptiet`) would otherwise be missed
    for stmt, _owned in join_continuations(lines):
        if stmt is None:
            continue
        m = RE_CHAR_DECL.match(stmt)
        if not m:
            continue
        for part in split_top(strip_bang(m.group(1))):
            nm = re.match(r'\s*([A-Za-z]\w*)', part)
            if nm:
                names.add(nm.group(1).lower())
    return names



RE_DECL_STMT = re.compile(
    r'^(real|integer|logical|character|double\s+precision|complex|dimension|common|'
    r'data|implicit|parameter|external|intrinsic|save|equivalence|include)\b', re.I)


def is_declaration(code):
    """True for a declaration statement.

    `code` is the text from column 7 onward, so it has no leading fixed-form padding --
    matching a column-anchored pattern against it silently never fires, which is how the
    section rules got loose inside declarations and rewrote array bounds.
    """
    return bool(RE_DECL_STMT.match(code.strip()))



# --- F90 array sections -----------------------------------------------------
# ccx passes contiguous column slices around (`call attachline(xl2s,
# pvertex(1:3,k), ...)`), writes them (`write(20,*) nodef(1:nopes)`), and zeroes
# them (`field(1:nfield,1:20)=0.d0`). f2c knows none of it. Each has an exact F77
# equivalent, and the three contexts need different ones -- which is why this is
# done per context rather than with one blanket substitution.
RE_SECTION = re.compile(
    # subscripts may contain a call, e.g. xl2mp(1:3,modf(n,i))
    r'\b([a-z]\w*)\(((?:[^()]|\([^()]*\))*:(?:[^()]|\([^()]*\))*)\)', re.I)


def _has_range(subs):
    """True if a subscript list contains a lo:hi range at depth 0."""
    depth = 0
    for ch in subs:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        elif ch == ':' and depth == 0:
            return True
    return False


def _first_of_range(subs):
    """`1:3,k` -> `1,k`. The section starts at element (lo, ...), and Fortran
    passes by reference, so handing over that address is exactly the slice."""
    out = []
    for part in split_top(subs):
        if ':' in part:
            lo = part.split(':', 1)[0].strip()
            out.append(lo if lo else '1')
        else:
            out.append(part.strip())
    return ','.join(out)


def sections_as_arguments(code, skip=()):
    """A section in an ARGUMENT position becomes the address of its first element."""
    out, i = [], 0
    for m in RE_SECTION.finditer(code):
        if m.start() < i:
            continue
        if not _has_range(m.group(2)) or m.group(1).lower() in skip:
            continue
        before = code[:m.start()].rstrip()
        # argument position: directly after '(' or ',' of an enclosing call
        if not before.endswith(('(', ',')):
            continue
        after = code[m.end():].lstrip()
        if not after.startswith((',', ')')):
            continue
        out.append(code[i:m.start()])
        out.append('%s(%s)' % (m.group(1), _first_of_range(m.group(2))))
        i = m.end()
    out.append(code[i:])
    return ''.join(out)


RE_IO_HEAD = re.compile(r'^(\s*)(write|read)\s*\(', re.I)


def _io_split(code):
    """Split `write(88,'(I12)') items` into (header, items), or None.

    The control list is matched by balancing parentheses with quote awareness -- a
    format such as '(I12)' contains a ')' that a plain regex stops at, which silently
    left those statements unconverted.
    """
    m = RE_IO_HEAD.match(code)
    if not m:
        return None
    i = code.index('(', m.end() - 1)
    depth, quote, j = 0, None, i
    while j < len(code):
        ch = code[j]
        if quote:
            if ch == quote:
                quote = None
        elif ch in '"\'':
            quote = ch
        elif ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                return code[:j + 1], code[j + 1:]
        j += 1
    return None


def sections_in_io(code, counter, skip=()):
    """`write(20,*) x(1:n,k)` -> `write(20,*) (x(i_,k),i_=1,n)` (implied DO)."""
    parts = _io_split(code)
    if not parts:
        return code
    head, items = parts
    if not RE_SECTION.search(items):
        return code
    new_items = []
    for item in split_top(items):
        sm = RE_SECTION.fullmatch(item.strip())
        if sm and _has_range(sm.group(2)) and sm.group(1).lower() not in skip:
            subs = split_top(sm.group(2))
            rng = [k for k, p in enumerate(subs) if ':' in p]
            if len(rng) == 1:
                k = rng[0]
                lo, hi = [x.strip() for x in subs[k].split(':', 1)]
                var = 'i_fcw%d' % next(counter)
                subs2 = list(subs)
                subs2[k] = var
                new_items.append('(%s(%s),%s=%s,%s)'
                                 % (sm.group(1), ','.join(x.strip() for x in subs2),
                                    var, lo or '1', hi))
                continue
        new_items.append(item.strip())
    return head + ' ' + ','.join(new_items)


RE_SECTION_ASSIGN = re.compile(
    r'^(\s*)([a-z]\w*)\(([^()]*:[^()]*)\)\s*=\s*(\S.*)$', re.I)


def section_assignments(code, counter, skip=(), dims=None):
    """`field(1:nfield,1:20)=0.d0` -> nested DO loops. Only explicit lo:hi
    bounds; a bare `:` would need the declaration, which is not available here."""
    m = RE_SECTION_ASSIGN.match(code)
    if not m or not _has_range(m.group(3)):
        return None
    if m.group(2).lower() in skip:
        return None          # CHARACTER substring assignment, not an array section
    if m.group(4).lstrip()[:1] in ("'", '"'):
        return None          # assigning a string literal: a substring, whatever the
                             # declaration scan concluded
    subs = split_top(m.group(3))
    rhs = m.group(4).strip()
    if RE_SECTION.search(rhs):
        return None                      # section on both sides: not handled
    loops, idx = [], []
    for part in subs:
        part = part.strip()
        if ':' in part:
            lo, hi = [x.strip() for x in part.split(':', 1)]
            if not lo or not hi:
                # bare ':' -- take the extent from the declaration
                decl = (dims or {}).get(m.group(2).lower())
                axis = len(idx)
                if not decl or axis >= len(decl):
                    return None
                d = decl[axis].strip()
                lo, hi = (d.split(':', 1) if ':' in d else ('1', d))
                lo, hi = lo.strip(), hi.strip()
            var = 'i_fcw%d' % next(counter)
            loops.append((var, lo, hi))
            idx.append(var)
        else:
            idx.append(part)
    body = ['      do %s=%s,%s' % (v, lo, hi) for v, lo, hi in loops]
    body.append('      %s(%s)=%s' % (m.group(2), ','.join(idx), rhs))
    body += ['      enddo' for _ in loops]
    return body



RE_DECL_KW = re.compile(
    r'^\s{6,}(real|integer|logical|character|double\s+precision|complex|dimension|'
    r'common|data|implicit|parameter|external|intrinsic|save|equivalence|include)\b', re.I)


def _declare_in_unit(lines):
    """declare_generated for ONE subprogram. See there for why the split matters."""
    used = sorted({m.group(0) for l in lines for m in re.finditer(r'\bi_fcw\d+\b', l)},
                  key=lambda x: int(x[5:]))
    if not used:
        return lines
    for i, l in enumerate(lines):
        if not l.strip() or l[:1] in 'cC*!' or (len(l) > 5 and l[5] not in ' 0'):
            continue
        head = l.strip().lower()
        if head.startswith(('data ', 'include ')):
            # F77 requires declarations before DATA -- and an include may pull DATA in
            # (ccx's gauss.f does), so stop at whichever comes first rather than at the
            # first executable statement
            return lines[:i] + ['      integer ' + ','.join(used)] + lines[i:]
        if head.startswith(('subroutine', 'function', 'end', 'entry')) or RE_DECL_KW.match(l):
            continue
        if re.match(r'^\s{6,}\S', l):
            return lines[:i] + ['      integer ' + ','.join(used)] + lines[i:]
    return lines


def declare_generated(lines):
    """Declare the loop variables the section rules invent, PER SUBPROGRAM.

    ccx compiles with `implicit none`, so an undeclared i_fcwN is a hard error.

    This used to scan the whole file and emit one declaration at the first executable
    statement it found -- which is correct only when the file holds a single subprogram.
    ccx has several that do not: us3_sub.f has 14, us4_sub.f 13, umat_ciarlet_el.f 6. Every
    i_fcwN in the file was declared in the FIRST subprogram, so f2c reported both halves of
    the same mistake at once (run 32140989422):

        109 Warning ... local variable i_fcwN never used          <- in the first subprogram
         94 Error ... Declaration error for i_fcwN: attempt to
                      use undefined variable                       <- in all the others

    and the file was stubbed. Splitting on subprogram heads and declaring only what each one
    actually uses fixes both. A file with one subprogram behaves exactly as before.
    """
    heads = [i for i, l in enumerate(lines) if RE_SUBPROG_HEAD.match(l)]
    if len(heads) <= 1:
        return _declare_in_unit(lines)
    out = lines[:heads[0]]
    for n, start in enumerate(heads):
        end = heads[n + 1] if n + 1 < len(heads) else len(lines)
        out.extend(_declare_in_unit(lines[start:end]))
    return out



def wrap_long_lines(lines):
    """Fold code lines past column 72 onto continuations.

    Every rewrite here can lengthen a line -- `exit` becoming `goto 8012` pushed one
    of rhsnodef's deeply indented statements to 77 columns, where fixed form simply
    drops the tail. Breaks are chosen outside string literals; a line with no safe
    break point is left alone rather than corrupted.
    """
    out = []
    for l in lines:
        if l[:1] in 'cC*!' or not l.strip():
            out.append(l)
            continue
        if len(l) <= 72:
            out.append(l)
            continue
        cur = l
        while len(cur) > 72:
            cut, quote = -1, None
            for i, ch in enumerate(cur[:72]):
                if quote:
                    if ch == quote:
                        quote = None
                    continue
                if ch in '"\'':
                    quote = ch
                elif i > 6 and ch in ' ,+-*/=()':
                    cut = i + 1 if ch == ',' else i
            if cut <= 6:
                break                      # nothing safe to break on
            out.append(cur[:cut])
            cur = '     &' + cur[cut:].lstrip()
        out.append(cur)
    return out



RE_ARRAY_DECL = re.compile(
    r'^\s*(?:real|integer|logical|complex|double\s+precision)\s*(?:\*\s*\d+)?\s*(?:::)?\s*(.*)$',
    re.I)


def declared_dims(lines):
    """name -> list of dimension strings, from the file's own declarations.

    Needed for `x(:,:)=0.d0`: a bare ':' carries no bounds, so the only place to learn
    the extent is the declaration.
    """
    dims = {}
    for stmt, _ in join_continuations(lines):
        if stmt is None or not is_declaration(stmt[5:]):
            continue
        m = RE_ARRAY_DECL.match(stmt[5:])
        if not m:
            continue
        for part in split_top(m.group(1)):
            dm = re.match(r'\s*([A-Za-z]\w*)\s*\((.*)\)\s*$', part.strip(), re.S)
            if dm and ':' not in dm.group(2):
                dims.setdefault(dm.group(1).lower(), split_top(dm.group(2)))
    return dims



# --- F90 ALLOCATABLE --------------------------------------------------------
# f2c has no dynamic memory. Each allocatable becomes a fixed-size array in STATIC
# storage (they are mesh-sized, so the stack is not an option), and the ALLOCATE
# statement becomes the bounds check -- that is the point where the real extent is
# finally known, so exceeding it stops the run instead of overrunning the array.
ALLOC_BOUND = 200000
# Only the LAST dimension gets the mesh-sized bound. `allocate(thickecp(mi(3),nkon))`
# with ALLOC_BOUND on both is 4e10 elements, which clang rejects outright; the leading
# dimensions of ccx's allocatables are always small per-element counts (layers, DOF).
# Both still get a guard, so an underestimate stops the run.
ALLOC_MINOR_BOUND = 20

RE_ALLOCATABLE_DECL = re.compile(
    r'^\s*((?:real|integer|logical|complex|double\s+precision)\s*(?:\*\s*\d+)?)\s*,\s*'
    r'dimension\s*\(\s*(:(?:\s*,\s*:)*)\s*\)\s*,\s*allocatable\s*::\s*(.+)$', re.I)
RE_ALLOCATE = re.compile(r'^\s*(de)?allocate\s*\((.*)\)\s*$', re.I)


def _alloc_dims(text, name):
    """Dimensions from the first `allocate(name(...))` for this array."""
    for m in re.finditer(r'\ballocate\s*\(', text, re.I):
        inner = text[m.end():]
        depth, j = 1, 0
        while j < len(inner) and depth:
            if inner[j] == '(':
                depth += 1
            elif inner[j] == ')':
                depth -= 1
            j += 1
        for item in split_top(inner[:j - 1]):
            im = re.match(r'\s*([A-Za-z]\w*)\s*\((.*)\)\s*$', item.strip(), re.S)
            if im and im.group(1).lower() == name:
                return split_top(im.group(2))
    return None


def expand_allocatables(text):
    """Turn F90 allocatables into bounded static arrays plus a guard."""
    if 'allocatable' not in text.lower():
        return text
    lines = text.splitlines()
    info = {}
    for stmt, _ in join_continuations(lines):
        if stmt is None:
            continue
        m = RE_ALLOCATABLE_DECL.match(stmt[5:])
        if not m:
            continue
        for nm in split_top(m.group(3)):
            nm = nm.strip().lower()
            dims = _alloc_dims(text, nm)
            if not dims or len(dims) != m.group(2).count(':'):
                return text          # cannot see the extent: leave it to the stub
            fixed, guards = [], []
            for k, d in enumerate(dims):
                d = d.strip()
                if re.fullmatch(r'\d+', d):
                    fixed.append(d)          # already a literal
                    continue
                last = k == len(dims) - 1
                fixed.append(str(ALLOC_BOUND if last else ALLOC_MINOR_BOUND))
                guards.append((d, ALLOC_BOUND if last else ALLOC_MINOR_BOUND))
            info[nm] = (m.group(1).strip(), fixed, guards)
    if not info:
        return text

    out = []
    for raw in lines:
        lab, cont, code, is_c = split_fixed(raw)
        if is_c or not raw.strip():
            out.append(raw)
            continue
        stripped = code.strip()
        m = RE_ALLOCATABLE_DECL.match(stripped)
        if m:
            for nm in split_top(m.group(3)):
                nm = nm.strip().lower()
                typ, fixed, _ = info[nm]
                out.append('      %s %s(%s)' % (typ, nm, ','.join(fixed)))
                out.append('      save %s' % nm)
            continue
        a = RE_ALLOCATE.match(stripped)
        if a:
            if a.group(1):                    # deallocate: nothing to release
                out.append('      continue')
                continue
            emitted = False
            for item in split_top(a.group(2)):
                im = re.match(r'\s*([A-Za-z]\w*)\s*\(', item.strip())
                if not im or im.group(1).lower() not in info:
                    continue
                for g, bound in info[im.group(1).lower()][2]:
                    out.extend(wrap_long_lines(
                        ['      if((%s).gt.%d) then' % (g, bound)]))
                    out.append("         write(*,*) '*ERROR: array too large for the'")
                    out.append("         write(*,*) '        WebAssembly build'")
                    out.append('         call exit(201)')
                    out.append('      endif')
                emitted = True
            out.append('      continue' if not emitted else '      continue')
            continue
        out.append(raw)
    return '\n'.join(out) + '\n'




# --- F90 MATMUL / TRANSPOSE -------------------------------------------------
# FORTRAN 77 has no array-valued intrinsics, so `Kshell=matmul(matmul(transpose(tmg),
# Kshell),tmg)` has no F77 spelling at all and f2c rejects the whole file.
#
# The rewrite mirrors expand_reductions: every intermediate result becomes a temporary
# sized from the DECLARATIONS, and the loops live in bridge/ccx_matmul.f rather than being
# generated inline. What has to be generated is the element-wise assignment, because the
# statements this appears in are array arithmetic -- `Kp = (matmul(..) + matmul(..))*Ae`.
#
# Anything whose shape cannot be read off a declaration is LEFT ALONE, so f2c fails loudly
# on it rather than this guessing an extent. That is the same rule expand_reductions uses
# and the reason it has never produced a wrong number.
RE_MM_CALL = re.compile(r'\b(matmul|transpose)\s*\(', re.I)


def _strip_parens(operand):
    """`(tmg)` is the same operand as `tmg`. CalculiX writes both."""
    operand = operand.strip()
    while operand.startswith('(') and operand.endswith(')'):
        depth = 0
        for i, ch in enumerate(operand):
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0 and i != len(operand) - 1:
                    return operand          # the parens are not the outermost pair
        operand = operand[1:-1].strip()
    return operand


def _shape_of(operand, dims):
    """('m', rows, cols) or ('v', n) or None -- for a name, or a section of one."""
    operand = _strip_parens(operand)
    m = re.match(r'^([A-Za-z]\w*)\s*\((.*)\)$', operand, re.S)
    if m:
        name, subs = m.group(1).lower(), split_top(m.group(2))
        d = dims.get(name)
        if not d or len(d) != len(subs):
            return None
        free = []
        for sub, extent in zip(subs, d):
            sub = sub.strip()
            if sub == ':':
                free.append(extent)
            elif ':' in sub:
                lo, hi = sub.split(':', 1)
                free.append('((%s)-(%s)+1)' % (hi.strip(), lo.strip()))
        if not free:
            return None                      # a scalar element, not an array value
        if len(free) == 1:
            return ('v', free[0])
        if len(free) == 2:
            return ('m', free[0], free[1])
        return None
    d = dims.get(operand.lower())
    if not d:
        return None
    if len(d) == 1:
        return ('v', d[0])
    if len(d) == 2:
        return ('m', d[0], d[1])
    return None


def _leading(operand, dims):
    """The DECLARED leading dimension, which is what the helpers must be given."""
    name = re.match(r'^([A-Za-z]\w*)', _strip_parens(operand))
    if not name:
        return None
    d = dims.get(name.group(1).lower())
    if not d:
        return None
    return d[0] if len(d) >= 2 else '1'


def _base(operand):
    """First element of a section, so the callee sees the right start address."""
    operand = _strip_parens(operand)
    m = re.match(r'^([A-Za-z]\w*)\s*\((.*)\)$', operand, re.S)
    if not m:
        return operand
    subs = []
    for sub in split_top(m.group(2)):
        sub = sub.strip()
        if sub == ':':
            subs.append('1')
        elif ':' in sub:
            subs.append(sub.split(':', 1)[0].strip())
        else:
            subs.append(sub)
    return '%s(%s)' % (m.group(1), ','.join(subs))


def _split_call(code, pos):
    """Return (name, arg-strings, end-index) for the intrinsic call starting at pos."""
    m = RE_MM_CALL.match(code, pos)
    open_at = code.index('(', pos)
    depth, i = 0, open_at
    while i < len(code):
        if code[i] == '(':
            depth += 1
        elif code[i] == ')':
            depth -= 1
            if depth == 0:
                break
        i += 1
    return m.group(1).lower(), split_top(code[open_at + 1:i]), i + 1


def expand_matmul(text, dims):
    # A LOCAL copy, because every temporary has to become visible to the next lookup: the
    # second level of `matmul(matmul(transpose(tmg),Kshell),tmg)` asks for the shape of the
    # temporary the first level just produced. Without this the nested forms -- which are
    # most of them -- silently fell back to leaving the statement alone.
    dims = dict(dims)
    out, temps, counter = [], {}, [0]

    def newtemp(shape):
        counter[0] += 1
        name = 'fcwmt%d' % counter[0]
        temps[name] = shape
        dims[name] = [shape[1]] if shape[0] == 'v' else [shape[1], shape[2]]
        return name

    def _sub_section(name, subs, idx):
        """`bs1(:,:)` -> `bs1(i,j)`, `B1(:,1:6)` -> `B1(i,(1)+j-1)`.

        A section operand is NOT already-indexed just because it has parentheses: the colons
        have to become the loop's indices, or they survive into f2c as a syntax error. That
        is what `B1(:,1:6)=a3*bs1(:,:)` did -- loops emitted around untouched sections.
        """
        out, free = [], 0
        for sub in subs:
            sub = sub.strip()
            if sub == ':':
                out.append(idx[free] if free < len(idx) else idx[-1])
                free += 1
            elif ':' in sub:
                lo = sub.split(':', 1)[0].strip()
                i = idx[free] if free < len(idx) else idx[-1]
                out.append('(%s)+%s-1' % (lo, i))
                free += 1
            else:
                out.append(sub)                   # a fixed subscript stays put
        return '%s(%s)' % (name, ','.join(out))

    def index_refs(expr, idx, shape):
        """Turn whole-array and sectioned operands into element references."""
        out, i = [], 0
        while i < len(expr):
            m = re.compile(r'\b([A-Za-z]\w*)\b').match(expr, i)
            if not m:
                out.append(expr[i])
                i += 1
                continue
            name = m.group(1)
            key = name.lower()
            sh = temps.get(name) or (('m',) + tuple(dims[key]) if key in dims and len(dims[key]) == 2
                                     else (('v', dims[key][0]) if key in dims and len(dims[key]) == 1
                                           else None))
            j = m.end()
            if sh is None:
                out.append(name)
                i = j
                continue
            if j < len(expr) and expr[j] == '(':
                depth, k = 0, j
                while k < len(expr):
                    if expr[k] == '(':
                        depth += 1
                    elif expr[k] == ')':
                        depth -= 1
                        if depth == 0:
                            break
                    k += 1
                inner = expr[j + 1:k]
                if ':' in inner:
                    out.append(_sub_section(name, split_top(inner), idx))
                else:
                    out.append(expr[m.start():k + 1])   # a real element reference; leave it
                i = k + 1
                continue
            if sh[0] == 'v':
                out.append('%s(%s)' % (name, idx[0]))
            else:
                out.append('%s(%s,%s)' % (name, idx[0], idx[1] if len(idx) > 1 else idx[0]))
            i = j
        return ''.join(out)

    def reduce_calls(code, pre):
        """Replace innermost matmul/transpose with temporaries, emitting calls into `pre`."""
        while True:
            hits = [m.start() for m in RE_MM_CALL.finditer(code)]
            if not hits:
                return code
            # innermost first: the last hit that contains no other hit inside it
            target = None
            for pos in reversed(hits):
                name, args, end = _split_call(code, pos)
                if not RE_MM_CALL.search(code[code.index('(', pos) + 1:end - 1]):
                    target = (pos, name, args, end)
                    break
            if target is None:
                return code
            pos, name, args, end = target
            # An operand can be an array-valued EXPRESSION rather than a name --
            # resultsmech_us3.f writes matmul(transpose(Bm),(Km+Kp)). Materialise it into a
            # temporary first, taking the shape from the arrays inside it, so the helper
            # still receives a plain contiguous array.
            for ai, arg in enumerate(args):
                if _shape_of(arg, dims) is not None:
                    continue
                inner = [nm.lower() for nm in re.findall(r'[A-Za-z]\w*', arg)
                         if nm.lower() in dims]
                if not inner:
                    continue
                sh = _shape_of(inner[0], dims)
                if sh is None:
                    continue
                t = newtemp(sh)
                if sh[0] == 'v':
                    iv = 'i_fcwm%d' % (counter[0] * 10 + 1)
                    pre.append('do %s=1,%s' % (iv, sh[1]))
                    pre.append('  %s(%s)=%s' % (t, iv, index_refs(arg, [iv], sh)))
                    pre.append('enddo')
                else:
                    iv = 'i_fcwm%d' % (counter[0] * 10 + 1)
                    jv = 'i_fcwm%d' % (counter[0] * 10 + 2)
                    pre.append('do %s=1,%s' % (jv, sh[2]))
                    pre.append('  do %s=1,%s' % (iv, sh[1]))
                    pre.append('    %s(%s,%s)=%s' % (t, iv, jv, index_refs(arg, [iv, jv], sh)))
                    pre.append('  enddo')
                    pre.append('enddo')
                args[ai] = t

            if name == 'transpose':
                if len(args) != 1:
                    return code
                sh = _shape_of(args[0], dims)
                ld = _leading(args[0], dims)
                if not sh or sh[0] != 'm' or not ld:
                    return code
                t = newtemp(('m', sh[2], sh[1]))
                pre.append('call fcwtr(%s,%s,%s,%s,%s,%s)'
                           % (_base(args[0]), ld, t, sh[2], sh[1], sh[2]))
            else:
                if len(args) != 2:
                    return code
                a, b = _shape_of(args[0], dims), _shape_of(args[1], dims)
                la, lb = _leading(args[0], dims), _leading(args[1], dims)
                if not a or not b:
                    return code
                if a[0] == 'm' and b[0] == 'm':
                    t = newtemp(('m', a[1], b[2]))
                    pre.append('call fcwmm(%s,%s,%s,%s,%s,%s,%s,%s,%s)'
                               % (_base(args[0]), la, _base(args[1]), lb, t, a[1],
                                  a[1], a[2], b[2]))
                elif a[0] == 'm' and b[0] == 'v':
                    t = newtemp(('v', a[1]))
                    pre.append('call fcwmv(%s,%s,%s,%s,%s,%s)'
                               % (_base(args[0]), la, _base(args[1]), t, a[1], a[2]))
                elif a[0] == 'v' and b[0] == 'm':
                    t = newtemp(('v', b[2]))
                    pre.append('call fcwvm(%s,%s,%s,%s,%s,%s)'
                               % (_base(args[0]), _base(args[1]), lb, t, b[1], b[2]))
                else:
                    return code
            code = code[:pos] + t + code[end:]

    for stmt, raw in join_continuations(text.split('\n')):
        if stmt is None:
            out.extend(raw)
            continue
        label, cont, code, is_comment = split_fixed(stmt)
        if is_comment or not code:
            out.extend(raw)
            continue
        if '=' not in code or code.strip().lower().startswith(('if', 'call', 'do ')):
            out.extend(raw)
            continue
        lhs, rhs = code.split('=', 1)
        lhs, rhs = lhs.strip(), rhs.strip()
        lsh = _shape_of(lhs, dims)
        if lsh is None:
            out.extend(raw)
            continue
        # Whole-array assignment is F90 too, with or without an intrinsic in it:
        # `Q4 = (Q1 + Q2)*0.5d0` is exactly as untranslatable as the matmul forms, and it is
        # what these files fell to next once matmul was handled ("wrong number of subscripts
        # on Q4"). Anything whose LHS resolves to an array shape gets the element loop; a
        # fully-subscripted LHS resolves to None above and is left alone.
        if not RE_MM_CALL.search(code):
            if '=' in code and re.match(r'^[A-Za-z]\w*$', lhs):
                pass                      # bare array name: expand below
            elif RE_SECTION.search(lhs) if 'RE_SECTION' in globals() else (':' in lhs):
                pass                      # a section: the existing machinery may also see it
            else:
                out.extend(raw)
                continue

        pre = []
        new_rhs = reduce_calls(rhs, pre)
        if RE_MM_CALL.search(new_rhs):
            out.extend(raw)                        # something unhandled; leave for f2c to reject
            continue

        body = []
        for c in pre:
            body.append('      ' + c)
        if lsh[0] == 'v':
            i = 'i_fcwm%d' % (counter[0] + 1)
            body.append('      do %s=1,%s' % (i, lsh[1]))
            body.append('        %s=%s' % (index_refs(lhs, [i], lsh) if ':' in lhs else
                                           '%s(%s)' % (lhs, i) if '(' not in lhs else
                                           index_refs(lhs, [i], lsh),
                                           index_refs(new_rhs, [i], lsh)))
            body.append('      enddo')
        else:
            i = 'i_fcwm%d' % (counter[0] + 1)
            j = 'i_fcwm%d' % (counter[0] + 2)
            body.append('      do %s=1,%s' % (j, lsh[2]))
            body.append('        do %s=1,%s' % (i, lsh[1]))
            body.append('          %s=%s' % (index_refs(lhs, [i, j], lsh),
                                             index_refs(new_rhs, [i, j], lsh)))
            body.append('        enddo')
            body.append('      enddo')
        out.extend(body)

    return '\n'.join(out), temps


def expand_matmul_units(text):
    """Run expand_matmul per subprogram and declare its temporaries there.

    Two things force the split. declared_dims must be computed per unit, because these files
    reuse names -- us3_sub.f declares tm(3,3) in a dozen different subprograms. And a
    temporary used in the fourth subprogram must be DECLARED in the fourth: declaring them
    all in the first is the exact defect that made 94 i_fcwN references undefined.
    """
    lines = text.split('\n')
    heads = [i for i, l in enumerate(lines) if RE_SUBPROG_HEAD.match(l)]
    if not heads:
        return text
    out = lines[:heads[0]]
    for n, start in enumerate(heads):
        end = heads[n + 1] if n + 1 < len(heads) else len(lines)
        unit = lines[start:end]
        dims = declared_dims(unit)
        body, temps = expand_matmul('\n'.join(unit), dims)
        ul = body.split('\n')
        # Declare the loop variables whenever they are USED, not only when a matmul
        # temporary happens to exist. extrapolatecontact.f has no matmul at all but does get
        # whole-array element loops, so gating this on `temps` left i_fcwmN undeclared there
        # and stubbed a routine that had been translating fine. Run 32160639115 caught it by
        # listing extrapolatecontact.f as newly stubbed -- a regression, not progress.
        decls = []
        for name, sh in sorted(temps.items()):
            decls.append('      real*8 %s(%s)' % (name, sh[1] if sh[0] == 'v'
                                                  else '%s,%s' % (sh[1], sh[2])))
        idx = sorted({int(m.group(1)) for l in ul
                      for m in re.finditer(r'\bi_fcwm(\d+)\b', l)})
        if idx:
            decls.append('      integer ' + ','.join('i_fcwm%d' % i for i in idx))
        if decls:
            ul = _declare_arrays_in_unit(ul, decls)
        out.extend(ul)
    return '\n'.join(out)


def _declare_arrays_in_unit(lines, decls):
    """Insert declaration lines at the last point a declaration is still legal."""
    for i, l in enumerate(lines):
        if not l.strip() or l[:1] in 'cC*!' or (len(l) > 5 and l[5] not in ' 0'):
            continue
        head = l.strip().lower()
        if head.startswith(('data ', 'include ')):
            return lines[:i] + decls + lines[i:]
        if head.startswith(('subroutine', 'function', 'end', 'entry')) or RE_DECL_KW.match(l):
            continue
        if re.match(r'^\s{6,}\S', l):
            return lines[:i] + decls + lines[i:]
    return lines


def sink_data_statements(text):
    """Move DATA below the declarations it follows.

    ccx interleaves them -- `real*8 cd_tab(12)` / `data cd_tab /.../` / `real*8
    p2p1_tab(19)` / `data ...`. F90 permits that; FORTRAN 77 wants every declaration
    before any DATA. Moving DATA later is always safe (it may not precede the
    declaration of what it initialises), so the whole prologue's DATA is emitted at
    the end of the prologue, in order.
    """
    lines = text.splitlines()
    head, data, tail = [], [], []
    in_prologue = True
    for stmt, owned in join_continuations(lines):
        if not in_prologue:
            tail.extend(owned)
            continue
        if stmt is None:
            (head if not data else data).extend(owned)
            continue
        body = stmt[5:].strip().lower()
        if re.match(r'data\s*[(\w]', body):
            data.extend(owned)
            continue
        if (is_declaration(stmt[5:]) or not body
                or body.startswith(('subroutine', 'function', 'entry'))
                or re.match(r'^[a-z]+\s+function\b', body)):
            head.extend(owned)
            continue
        in_prologue = False
        tail.extend(owned)
    if not data:
        return text
    return '\n'.join(head + data + tail) + '\n'



# OpenMP: the wasm build is single-threaded and `c$omp` directives are already comments,
# so the module use and its header are dead weight that f2c cannot parse.
RE_OMP_LINE = re.compile(
    r'^\s{5,}(use\s+omp_lib\b.*|include\s*[\'"]omp_lib\.h[\'"].*)$', re.I | re.M)
# INTENT as a free-standing statement (ccx writes `intent(in) a,b`) carries no meaning
# for f2c's output; the argument is passed by reference either way.
RE_INTENT_STMT = re.compile(r'^\s{5,}intent\s*\((in|out|inout)\)\s.*$', re.I | re.M)

# `integer iexpbr1(2) /11,11/` -- an F90 initialiser inside a type declaration.
RE_DECL_INIT = re.compile(r'(\b[a-z]\w*(?:\([^()]*\))?)\s*(/[^/]*/)')


def split_decl_initialisers(text):
    """`integer n(2) /11,11/` -> the declaration plus a separate DATA statement.

    Runs before sink_data_statements, which then puts the DATA where F77 wants it.
    """
    out = []
    for stmt, owned in join_continuations(text.splitlines()):
        if (stmt is None or not is_declaration(stmt[5:]) or '/' not in stmt
                or stmt[5:].strip().lower().startswith(('data ', 'common'))):
            out.extend(owned)
            continue
        inits = RE_DECL_INIT.findall(stmt[5:])
        if not inits:
            out.extend(owned)
            continue
        stripped = RE_DECL_INIT.sub(r'\1', stmt)
        out.extend(wrap_long_lines([stripped]))
        for name, values in inits:
            out.extend(wrap_long_lines(
                ['      data %s %s' % (name.split('(')[0], values)]))
    return '\n'.join(out) + '\n'


RE_MAXVAL = re.compile(r'\bmaxval\s*\(\s*([a-z]\w*)\s*\)', re.I)
RE_SUMABS = re.compile(
    r'\bsum\s*\(\s*abs\s*\(\s*([a-z]\w*)\s*\(\s*:\s*,((?:[^()]|\([^()]*\))*)\)\s*\)\s*\)',
    re.I)


def expand_reductions(text, dims):
    """F90 whole-array reductions -> calls into the Fortran runtime.

    `maxval(edgelength)` and `sum(abs(g(:,j)))` are the only two shapes ccx uses. Both
    become a length plus a first element, which is exact for `(:,j)` because Fortran is
    column-major, so a column IS contiguous. Anything whose length cannot be read off the
    declaration is left alone -- f2c then fails loudly rather than guessing a size.
    """
    used = set()

    def sizeof(name):
        d = dims.get(name.lower())
        return '*'.join(d) if d else None

    def rows(name):
        d = dims.get(name.lower())
        return d[0] if d and len(d) == 2 else None

    out = []
    for line in text.splitlines():
        label, cont, code, is_comment = split_fixed(line)
        if is_comment or not code:
            out.append(line)
            continue

        def mx(m):
            n = sizeof(m.group(1))
            if not n:
                return m.group(0)
            used.add('fcwmxv')
            return 'fcwmxv(%s,%s)' % (m.group(1), n)

        def sm(m):
            n = rows(m.group(1))
            if not n:
                return m.group(0)
            used.add('fcwsab')
            return 'fcwsab(%s(1,%s),%s)' % (m.group(1), m.group(2).strip(), n)

        new = RE_SUMABS.sub(sm, RE_MAXVAL.sub(mx, code))
        if new == code:
            out.append(line)
        else:
            out.extend(wrap_long_lines([line[:6] + new]))
    if not used:
        return text
    return _insert_decls('\n'.join(out) + '\n', sorted(used))


def _insert_decls(text, names):
    """Declare the reduction helpers just after the last existing declaration."""
    out, done, buf = [], False, ['      real*8 ' + n for n in names]
    stmts = list(join_continuations(text.splitlines()))
    for i, (stmt, owned) in enumerate(stmts):
        out.extend(owned)
        if done or stmt is None:
            continue
        # after the FIRST declaration, not the last: ccx's `include "gauss.f"` brings
        # DATA with it, and anything after that include is "declaration after DATA".
        if is_declaration(stmt[5:]):
            out.extend(buf)
            done = True
    return '\n'.join(out if done else buf + out) + '\n'



RE_TRAILING_SEMI = re.compile(r';\s*$')


def strip_inline_comments(text):
    """Drop `! ...` tails and trailing `;` from code lines.

    Both are F90. The comment matters beyond tidiness: a rewrite that lengthens the
    statement pushes the comment past column 72, and folding it produces a continuation
    line made of prose (relaxval_al). Quotes are tracked so a `!` inside a string stays.
    """
    out = []
    quote = None            # carries across continuations: ccx has a string that opens
    for line in text.splitlines():   # on one line and holds a `!` on the next
        label, cont, code, is_comment = split_fixed(line)
        if is_comment or not code:
            out.append(line)
            continue
        if not is_cont_line(cont):
            quote = None
        cut = -1
        for i, ch in enumerate(code):
            if quote:
                if ch == quote:
                    quote = None
            elif ch in '"\'':
                quote = ch
            elif ch == '!':
                cut = i
                break
        new = code[:cut] if cut >= 0 else code
        new = RE_TRAILING_SEMI.sub('', new)
        if new.strip() == '' and cut >= 0:
            out.append('C' + line[1:6] + code)
            continue
        out.append(line[:6] + new.rstrip() if new != code else line)
    return '\n'.join(out) + '\n'



# A sequence field is a bare tag: letters, digits, spaces. Requiring that (and a space
# at column 72) keeps this off code that ccx_bound_automatic's longer array bounds
# pushed past the margin -- truncating there silently renamed zienzhu's `maxcommon`.
RE_SEQ_FIELD = re.compile(r'^[A-Za-z0-9 ]*$')


def truncate_sequence_field(text):
    """Drop columns 73+ of the *input*.

    Fixed form ends code at column 72; hybsvd (netlib) keeps card sequence numbers
    past it, and folding `GRS   10` onto a continuation splices it into an argument
    list. This runs on the source only -- lines this tool generates are wrapped by
    wrap_long_lines, which must keep everything it is given.
    """
    out = []
    for l in text.splitlines():
        seq = (len(l) > 72 and l[:1] not in 'cC*!' and l[71].isspace()
               and RE_SEQ_FIELD.match(l[72:]))
        out.append(l[:72].rstrip() if seq else l)
    return '\n'.join(out) + '\n'



# --- F90 automatic arrays ----------------------------------------------------
# A LOCAL array sized by a variable -- `real*8 elconloc(ncmat_)` where elconloc is not a
# dummy argument. F90 allows it; FORTRAN 77, which is all f2c implements, does not, and f2c
# rejects the entire file with
#
#     Declaration error for elconloc: adjustable dimension on non-argument
#
# The routine is then STUBBED: it compiles, it links, and at run time it does nothing. 63 of
# CalculiX's 977 routines failed exactly this way -- including e_c3d.f, the 3D element
# stiffness routine, without which solid FEM does not work at all.
#
# patches/ccx-wasm-automatic-array.patch already fixes this by hand for one file. This
# generalises its shape: give the array a fixed bound, and emit a guard that STOPS the run
# if the real dimension ever exceeds it.
#
# THE GUARD IS THE POINT. A fixed bound that is too small would otherwise overrun silently
# and produce wrong stresses -- the worst failure a solver can have, because nothing looks
# broken. With the guard the only outcomes are "correct" or "stops and says so". No entry
# may be added to the table below without one.
#
# Only dimension expressions with an ESTABLISHED bound belong here. Each value below is read
# out of CalculiX's own source, not chosen:
#
#   ncmat_  1000  from patches/ccx-wasm-automatic-array.patch -- same array, same dimension.
#
#   mi(2)    255  mi(2) is the highest degree of freedom per node. ini_cal.c:217 starts it at
#                 3; every site that raises it is a small constant (allocation.f: 3, 4, 5, 6)
#                 except two, and CalculiX bounds both ITSELF:
#                   userelements.f:75    *USER ELEMENT   -> '*ERROR ... exceeds 255'
#                   matrix2userelem.f:136 *MATRIX ASSEMBLE -> rejects any ndof except 3 or 6
#                 So 255 is not a bound we picked, it is the one CalculiX enforces. No deck
#                 CalculiX accepts can exceed it, so this guard can never fire. Cost is small:
#                 the widest such array, voldl(0:mi(2),20), is 40 KB against a 16 MB stack.
#
#   mi(3)    255  max layers in a composite shell. Grown only by constant 2, except
#                 allocation.f:2092 `mi(3)=max(mi(3),nlayer)`, where nlayer is counted from
#                 the lines under *SHELL SECTION,COMPOSITE and has NO upstream limit. 255 is
#                 therefore a chosen ceiling, and the one entry below that can really fire --
#                 which is exactly why the guard is mandatory.
#
# Per-array overrides exist for one reason: the stack. `field(999,20*mi(3))` in the five
# extrapolate routines costs 160 KB per layer, so mi(3)=255 would ask for 40 MB of stack.
# 16 layers keeps it at 2.6 MB and still covers any laminate FreeCAD can produce (FreeCAD
# emits no composite sections at all, so mi(3) is 1 or 2 in practice).
#   mi(1)    255  max integration points per element. Every standard element type sets it to
#                 a small constant in allocation.f (1, 2, 4, 8, 9, 15, 27, 50 -- 50 is the
#                 largest), and the only unbounded-looking sites are the same two as mi(2):
#                   userelements.f:67  *USER ELEMENT -> '*ERROR ... exceeds 255'
#                   allocation.f:2091  mi(1)=max(mi(1),8*nlayer)  for composites
#                 So 255 again comes from CalculiX, and only a composite above 31 layers can
#                 reach past it -- which the guard stops. Found because extrapolate.f
#                 declares coords(3,mi(1)) and yiloc(6,mi(1)), and it was the single routine
#                 keeping the elastic and plastic decks from running at all.
DIM_BOUNDS = {
    'ncmat_': 1000,
    'mi(1)': 255,
    'mi(2)': 255,
    'mi(3)': 255,
}
# An entry here MUST bound an array's LAST dimension. Fortran is column-major, so bounding any
# earlier dimension changes the stride of everything after it -- and if the array is then
# handed to a routine that re-declares it with the RUNTIME dimension, the callee reads the
# wrong elements with nothing to warn you.
#
# ('field','mi(3)') satisfies that: in extrapolate.f's field(999,20*mi(3)) the bounded
# dimension IS the last one, so the layout is unchanged and 999 stays 999. It is also load
# bearing -- without it that array is 40 MB, over the stack ceiling, and extrapolate.f falls
# back to a stub, which takes the elas and plast decks with it. Measured: removing it dropped
# 959/977 to 954/977 and broke both.
#
# What was wrong was the separate GLOBAL `nfield` bound, now removed: together they turned
#   field(nfield,20*mi(3))  ->  field(20,20*16)
# in extrapolatecontact.f, bounding the FIRST dimension of an array whose stride a callee
# computes from the runtime nfield.
ARRAY_DIM_BOUNDS = {
    ('field', 'mi(3)'): 16,
}

# PROBLEM-SIZE dimensions, which are a different animal. Everything above is a per-element
# constant, so a generous bound costs a few KB. These scale with the MODEL -- neq(2) is the
# number of equations, nev the number of eigenvalues -- so they need bounds orders of
# magnitude larger, and putting those on a 16 MB stack is not an option.
#
# So they get the convention this file already uses for F90 allocatables (ALLOC_BOUND, 200000,
# with `save`): static storage rather than stack. Same guard, same fail-safe, no stack cost.
# `save` is only sound because these routines are not recursive, which is asserted below.
#
# Reached for only when a routine is otherwise unfixable. A bound here CAN be hit by a real
# model -- 200000 equations is roughly a 66,000-node mesh -- and when it is, the run stops
# with a message instead of quietly reading past the end of the array.
#
# The mesh-size entries below target the routines FreeCAD actually reaches: contact analysis
# (slavintmortar, slavintpoints, extrapolatecontact) and the Zienkiewicz-Zhu error estimator
# (zienzhu). Converting them cannot break anything that works today -- they are STUBBED right
# now, so they already abort unconditionally. Bounding turns "always aborts" into "works, or
# aborts when the bound is hit", which is strictly better and has the same failure mode.
#
# Deliberately NOT in this table, and each for a specific reason:
#   k        near2d/near3d declare ir(k+4). One-letter, and far too common to token-match.
#   x, y     calcview's `fform(x,y,idata,rdata)` is a FUNCTION declaration, not an array.
#   ipoints  patch.f declares z(ipoints,ipoints) -- SQUARE, so any generous bound explodes.
#            The per-array budget below refuses it anyway, but it should never be attempted.
STATIC_DIM_BOUNDS = {
    'neq(2)': 200000,
    'nev': 10000,
    # 80000, and the number is chosen by a semantic constraint rather than a memory one.
    # The widest arrays on this dimension are 6 columns of real*8 -- zienzhu's scpav(6,nk) and
    # extrapolatecontact's stn(6,nk). At 150000 those are 7.2 MB, over the 4 MB stack ceiling,
    # so they were made STATIC via `save` -- and `save` makes a local persist between calls.
    # extrapolatecontact runs every increment and stn holds contact stresses, so saving it
    # carries the previous increment's stresses into the next one. 80000 puts those arrays at
    # 3.84 MB, under the stack ceiling, so they stay automatic and fresh per call.
    #
    # In other words the bound is set by "which storage class does this get", not by how many
    # nodes seem generous. A larger bound here silently changes the semantics of the routine.
    'nk': 80000,           # nodes
    'ne': 200000,          # elements
    'nktet': 200000,       # nodes in the tet mesh
    'ncont': 100000,       # contact elements; declared as 3*ncont
    'ntie': 10000,         # tie/contact pairs
    'nselect': 10000,
    # Safe despite bounding a FIRST dimension (extrapolatecontact's field(nfield,20*mi(3))):
    # `field` is never passed to another routine -- verified, 0 call sites -- so every access
    # goes through the same declaration and the stride is self-consistent. I removed this
    # entry once believing it was the contact defect; it was not, and removing it only stubbed
    # extrapolatecontact. The stride hazard is real but needs the array to ESCAPE the routine.
    'nfield': 20,
    'nobject': 1000,

    # --- added 2026-08-18, working through the remaining stub list -------------------
    # Orientations. gen3dfrom2d.f declares neworien(0:norien); norien is a dummy scalar, so
    # the array is automatic. CalculiX bounds it itself one line later --
    # `if(norien.gt.norien_) *ERROR ... increase norien_` -- and neworien never leaves the
    # routine (0 call sites), so the single dimension bounded here is also the last one and
    # no callee can disagree about the stride. 10000 orientations is 40 KB.
    'norien': 10000,

    # Tets in the master mesh. basis.f declares node(netet), idummy1(netet), idummy2(netet)
    # and iparentel(netet) -- and its own comment two lines above says what they really hold:
    #
    #     !     100 nearest nodes: node(100),idummy1(100),idummy2(100),iparentel(100)
    #
    # so the declared extent is an upper bound the routine never approaches. All four are
    # single-dimension scratch, so bounding is the last dimension in each case.
    'netet': 200000,

    # Crack-front nodes. extendmesh.f declares x0/y0/z0/x/y/z(nfront), nx/ny/nz(nfront),
    # ifronteq/neighbor(nfronteq). Every one is SINGLE-dimension, so the bounded dimension is
    # necessarily the last and no stride can change -- which is what makes it safe that these
    # DO escape, to dsort() and near3d(). Both callees take the runtime count k and index
    # against that, not against the declared extent.
    #
    # 50000 keeps the widest array at 400 KB (50000 real*8) and the whole set near 3 MB, under
    # the per-array stack ceiling, so they stay automatic rather than needing `save`. A front is
    # a 1-D curve through a 3-D mesh; 50000 nodes on one is already implausible.
    'nfront': 50000,
    'nfronteq': 50000,

    # Points on a contact face. interpolateinface.f declares list/ip/ibin(numpts) and, more
    # importantly, koncont(3,2*numpts+1), imastop(3,2*numpts+1), cg(2,2*numpts+1),
    # straight(9,2*numpts+1), coi(2,numpts+3) -- numpts is the LAST dimension in every
    # multi-dimensional case, which is the rule this table exists to respect.
    # 10000 puts the widest (straight) at 1.4 MB, inside the per-array stack ceiling.
    'numpts': 10000,

    # Allocated tet capacity for the cavity remesher. cavity_refine.f and
    # cavityext_refine.f declare ig(4*netet_), ifcav(4*netet_), ige/iecav/inewel(netet_) --
    # all 1-D -- plus incav(4,netet_), where netet_ is again the LAST dimension.
    #
    # 50000 rather than netet's 200000, and the reason is the budget: ig and ifcav are
    # 4*netet_ each, so 200000 would put a single array at 3.2 MB and the file's set at
    # ~13 MB of stack against a 16 MB limit. At 50000 the widest is 800 KB and the set is
    # ~3.4 MB. If a remesh ever needs more the guard stops the run and says so.
    'netet_': 50000,

    # Radiation view-factor integration grid. calcview.f declares xy(ng) with ng a dummy
    # scalar. Its own commented-out default two lines below says what the value is:
    #
    #     c      ng=160
    #
    # so 10000 is ~60x the real grid and costs 80 KB. covered(ng,ng) is SQUARE but is a dummy
    # ARGUMENT, so it keeps its adjustable dimensions and needs nothing from this table.
    'ng': 10000,
}

# Files we deliberately leave STUBBED, even though the bounds machinery could convert them.
#
# A stub aborts with a message naming the routine. A bounded routine whose numerics are wrong
# returns an answer. For a solver the second is far worse, and mortar contact is currently the
# second: with slavintmortar and slavintpoints bounded, scratchpad/ccxval/contact.inp
# CONVERGES and produces
#
#     contact pressure  -93.2      (negative: contact cannot pull, only push)
#     z displacement    +4.07e-3   (production: exactly 0, nothing moves up)
#     x/y               asymmetric on a perfectly symmetric model
#     error estimate    68.5       (production: 11.2)
#
# against production's physically sound result. So the bounds are not merely unvalidated here,
# they are demonstrably wrong, and the honest state is the loud one. This was only visible
# after softening the deck -- at full stiffness it failed to converge instead, which hid a
# lying solver behind what looked like a tolerance problem.
#
# Remove an entry once contact.inp matches production. Do not remove one to make CI green.
#
# A SECOND hypothesis, also tested, also not the answer -- but it leaves a real caveat behind.
# Fortran is column-major, so bounding a NON-LAST dimension changes the stride of everything
# after it, and 66 declarations here do exactly that (vl(0:mi(2),20), field(nfield,...), ...).
# Handing such an array to a routine that re-declares it with the RUNTIME dimension would make
# the callee read the wrong elements, silently.
#
# It is nevertheless safe for the global table, and the reason is worth stating: mi(1..3),
# ncmat_ and the rest are applied UNIFORMLY to every declaration in the tree, so caller and
# callee agree on 255. That is not a theory -- elas, plast, freq and therm all bound mi(2) on
# a first dimension and are byte-identical to production. A static "refuse non-last dims"
# check was written, refused 12 files including e_c3d.f and resultsmech.f, and was reverted:
# a rule that contradicts a measured byte-identical result is the wrong rule.
#
# CONCLUDED. Halving every bound on the contact path (ncont and near2d/near3d's k, both
# 100000 -> 50000) produced BYTE-IDENTICAL wrong numbers: the same -9.3215e+1 contact
# pressure, the same 68.475 error estimate, the same displacements to every digit. The bound
# VALUE therefore does not reach the results at all, which means these arrays are only ever
# accessed within their true runtime extent -- nothing reads uninitialised tail memory, and a
# fixed bound corrupts nothing.
#
# Combined with the line-by-line verification below, that exonerates the transformation
# entirely. The contact difference is inherent to upstream-vs-production SOURCE: production's
# CalculiX was built from the build machine's uncaptured f2c edits, which are not in this
# repository (checked: ccx-wasm-automatic-array.patch is the only CalculiX patch here, and
# freecad.patch touches zero .f files). No bound tuning will ever close it.
#
# EVERY TRANSFORMATION ON THE CONTACT PATH HAS NOW BEEN VERIFIED FAITHFUL, and none of them
# explains the defect:
#   - slavintmortar / slavintpoints: bounds touch only LAST dimensions, so the memory layout
#     is unchanged; cycle/exit -> goto labels are all correctly placed (the cycle target sits
#     immediately before its enddo, the exit target after it).
#   - near2d / near3d: the named-loop conversion is correct too -- `cycle loop` becomes a jump
#     to a label INSIDE the loop before its enddo, `exit` to one after it.
#   - extrapolatecontact: `field` never leaves the routine, so its bound is self-consistent.
# So the cause is NOT a mis-transformation of these four files. That is a real narrowing, and
# it points at something outside them -- production carries ~90 KB more code than this build
# and its stub list has never been enumerated.
#
# LOCALISED, 2026-08-17. Diffing raw solver stdout against production puts the divergence at
# ITERATION 1 OF INCREMENT 1 -- the first force evaluation there is:
#
#     live   average force= 10.714286   largest residual force=   0.000000  (node 6, dof 3)
#     built  average force=  8.060516   largest residual force= 319.444444  (node 5, dof 3)
#     both   largest increment of disp= 1.535714e-03      <-- IDENTICAL
#
# The displacement solve agrees exactly; the RESIDUAL FORCE does not. Production reaches exact
# equilibrium on the first evaluation and this build is out by 319. Since no iteration history
# exists yet, nothing stateful can explain it -- which independently confirms the `save`
# hypothesis was wrong, and rules out convergence tuning, line search and increment size too.
#
# The defect is therefore in the CONTACT FORCE ASSEMBLY itself: the contact elements this
# build generates carry different forces from the first moment they exist. That is where to
# look next -- the slave integration point generation, not the solver loop around it.
#
# STILL OUTSTANDING, flagged rather than changed: effectivemodalmass.f gets part(nev,6) and
# effmodmass(nev,6) -- `nev` is a problem-size bound on a FIRST dimension, the same shape as
# the field/nfield defect removed above. It is left alone because the freq deck exercises that
# routine and is BYTE-IDENTICAL to production, and the lesson from the reverted stride check is
# that measurement outranks the rule. Revisit if freq ever diverges; do not "fix" it blind.
#
# The caveat that DOES stand: a non-uniform bound -- ARRAY_DIM_BOUNDS or FILE_DIM_BOUNDS -- on
# a non-last dimension of an array that gets passed onward is genuinely unsafe, because
# nothing makes the callee agree. Today that is only field/mi(3), inside a routine already
# excluded. Check it before adding another.
#
# One hypothesis has been tested and DISPROVEN, recorded so nobody repeats it: `save`. Both
# routines' arrays were made automatic (nk 150000 -> 80000 drops them under the stack ceiling,
# and `save` is now absent from the entire tree) and the deck produced numbers BYTE-IDENTICAL
# to the static build -- same -9.3215e+1 contact pressure, same 68.475 error estimate. So the
# defect is deterministic and has nothing to do with storage class. Look elsewhere.
SKIP_FILES = frozenset((
    'slavintmortar.f',
    'slavintpoints.f',
))

# FILE-SCOPED bounds. Some dimension names are far too common to put in a global table but
# are perfectly safe inside one known file. `k` is the case that forced this: near2d.f and
# near3d.f declare ir(k+4) / r(k+6) where k is "the number of closest nodes to find" -- a
# dummy argument, so those locals are automatic arrays. A global `k` entry would match
# thousands of unrelated declarations; scoped to two files it matches four.
#
# This is not optional polish. near3d is on the CONTACT path: with it stubbed, production
# runs a contact analysis and a clean build aborts. The contact.inp deck caught exactly that.
#
# 100000 is generous -- CalculiX clamps k to n (near3d.f:36 `if(k.gt.n) k=n`) and callers ask
# for a handful of neighbours -- and costs 1.2 MB of stack against a 16 MB limit.
FILE_DIM_BOUNDS = {
    ('near2d.f', 'k'): 100000,
    ('near3d.f', 'k'): 100000,
}

# Basename of the file being converted, for FILE_DIM_BOUNDS. Set by main().
CURRENT_FILE = ''

# A static array does not touch the stack, but it does consume linear memory for every user
# of the module, forever. So static mode gets its own ceiling, well above the stack one and
# still far below anything that would bloat the download. This is what stops
# patch.f's z(ipoints,ipoints) -- square in a problem-size dimension -- from being emitted as
# a multi-gigabyte declaration. Over the ceiling, the routine stays stubbed and says so.
STATIC_ARRAY_MAX_BYTES = 8 << 20

# f2c runs with -a, so these locals land on the STACK, and the link sets -sSTACK_SIZE=16MB.
# A bound that is generous on paper can therefore overflow the stack at run time -- a failure
# that looks like memory corruption, not like a bound being wrong. So the rewrite is refused
# above this size and the routine stays stubbed, which is loud and recoverable, rather than
# emitted and unsound. Raise a bound OR raise STACK_SIZE deliberately; never by accident.
AUTO_ARRAY_MAX_BYTES = 4 << 20
ELEM_BYTES = {'real*8': 8, 'doubleprecision': 8, 'complex*16': 16,
              'real': 4, 'integer': 4, 'logical': 4}

RE_SUBPROG_HEAD = re.compile(
    r'^\s{6,}(?:recursive\s+)?(?:subroutine|(?:real\*8|real|integer|logical|'
    r'double\s+precision)?\s*function)\s+([a-z0-9_]+)\s*\(', re.I)

# Anything that is still part of the declaration section; the guard goes after the last one.
RE_DECL_LINE = re.compile(
    r'^\s{6,}(implicit|integer|real|double|logical|character|dimension|common|parameter|'
    r'data|save|external|intrinsic|include|equivalence)\b', re.I)


def _dummy_args(lines):
    """Names in the SUBROUTINE/FUNCTION argument list (they may keep adjustable dims).

    Returns None if no subprogram header was found at all -- which is NOT the same as "no
    arguments", and the caller must refuse to rewrite anything in that case. This scans the
    whole file rather than a fixed prefix: ARPACK's dseupd.f carries ~200 lines of header
    comment before its SUBROUTINE line, so an 80-line window found nothing, concluded the
    routine had no arguments, and rewrote d(nev) and z(ldz,nev) -- which are arguments. That
    silently changed a caller-supplied shape into a fixed one and broke every frequency
    analysis. Caught by the deck gate; it is invisible to compilation.
    """
    for i, ln in enumerate(lines):
        if not RE_SUBPROG_HEAD.match(ln):
            continue
        decl = ''
        for k in range(i, min(i + 60, len(lines))):
            code = lines[k][:72]
            decl += code[6:] if len(code) > 6 else ''
            if decl.count('(') and decl.count('(') == decl.count(')'):
                break
        if '(' in decl and ')' in decl:
            inner = decl[decl.find('(') + 1:decl.rfind(')')]
            return {a.strip().lower() for a in inner.split(',') if a.strip()}
        return set()
    return None                                        # no header: caller must not rewrite


def _split_dims(dims):
    """Split an array's dimension list on top-level commas: 'a,mi(2),max(b,c)' -> 3 parts."""
    parts, depth, cur = [], 0, ''
    for ch in dims:
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
        if ch == ',' and depth == 0:
            parts.append(cur); cur = ''
        else:
            cur += ch
    parts.append(cur)
    return parts


def _extent(dim):
    """Elements spanned by one bounded dimension, or None if it is not fully numeric."""
    dim = dim.strip()
    lo = 1
    if ':' in dim:
        a, _, b = dim.partition(':')
        try:
            lo = int(a)
        except ValueError:
            return None
        dim = b
    dim = dim.strip()
    if not dim or not re.fullmatch(r'[0-9*+\- ]+', dim):
        return None                                    # still symbolic, or not arithmetic
    try:
        return int(eval(dim, {'__builtins__': {}}, {})) - lo + 1
    except Exception:
        return None


def _decl_elem_bytes(ln):
    head = re.match(r'\s{6,}([a-z*0-9 ]+?)\s+[a-z_]', ln, re.I)
    if not head:
        return 8
    return ELEM_BYTES.get(head.group(1).lower().replace(' ', ''), 8)


# Statement keywords that are followed by a parenthesis and would otherwise read as an array
# name. `parameter(maxmid=400)` scanned as an array called `parameter` whose dimension
# contains letters, which reverted zienzhu.f -- a routine that was translating fine.
_DECL_KEYWORDS = frozenset((
    'parameter', 'dimension', 'common', 'data', 'save', 'equivalence', 'implicit',
    'external', 'intrinsic', 'precision', 'character', 'integer', 'real', 'logical'))


def _parameter_names(text):
    """Names given a value by PARAMETER: compile-time constants, legal as F77 dimensions."""
    names = set()
    for m in re.finditer(r'^\s{6,}parameter\s*\((.*)\)\s*$', text, re.I | re.M):
        for part in _split_dims(m.group(1)):
            if '=' in part:
                names.add(part.split('=')[0].strip().lower())
    return names


def _automatic_arrays(text, args):
    """Local arrays still carrying a symbolic dimension -- i.e. what f2c will reject."""
    found, in_decl = set(), False
    # TWO sets, and conflating them is a real bug. A dummy ARRAY may keep an adjustable
    # dimension, so `args` excuses an array NAME. But a dummy SCALAR used as a dimension is
    # exactly what makes an array automatic -- `incav(4,netet_)` with netet_ an argument is
    # the whole construct this file exists to fix. Only PARAMETERs are constant dimensions.
    const_names = args | _parameter_names(text) | _DECL_KEYWORDS
    const_dims = _parameter_names(text) | _DECL_KEYWORDS
    for ln in text.split('\n'):
        if len(ln) < 7 or (ln and ln[0] in 'CcDd*!'):
            continue
        if ln[5] in ' 0':
            # A FUNCTION head is not a declaration, even though it starts with a type.
            # calcview.f contains `real*8 function fform(x,y,idata,rdata)`, which matches
            # RE_DECL_LINE and made this loop record `fform` as an automatic array with four
            # symbolic dimensions -- none of which exist. The file was then unfixable by
            # construction: no bound can satisfy a function's argument list. Check this BEFORE
            # RE_DECL_LINE, because the head also ends the previous declaration section.
            if RE_SUBPROG_HEAD.match(ln):
                in_decl = False
                continue
            in_decl = bool(RE_DECL_LINE.match(ln))
        if not in_decl:
            continue
        for m in re.finditer(r'\b([a-z_][a-z0-9_]*)\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)',
                             ln, re.I):
            arr, dims = m.group(1), m.group(2)
            if arr.lower() in const_names:
                continue                # dummy arg, PARAMETER, or a statement keyword
            for part in _split_dims(dims):
                part = part.strip()
                # `*` is assumed-size, legal only on a dummy -- but a local declared with it
                # is not something this rule created, so leave that judgement to f2c.
                if part == '*' or not re.search(r'[a-z_]', part, re.I):
                    continue
                # A dimension built only from PARAMETERs is a compile-time constant and
                # perfectly legal F77. nmids(maxmid) with parameter(maxmid=400) is not an
                # automatic array, and treating it as one costs a working routine.
                if all(t.lower() in const_dims
                       for t in re.findall(r'[a-z_][a-z0-9_]*', part, re.I)):
                    continue
                found.add(arr.lower())
    return found


def fix_automatic_arrays(text):
    """Give local automatic arrays a fixed bound plus a stop-the-run guard.

    Rewrites ONE dimension of several -- `vl(0:mi(2),20)` becomes `vl(0:255,20)` -- which is
    the shape almost every CalculiX automatic array actually has. Only declaration statements
    are touched (tracked across continuation lines), so an executable subscript that happens
    to mention mi(2) is never rewritten.
    """
    if CURRENT_FILE in SKIP_FILES:
        sys.stderr.write('f77ify: %s left stubbed on purpose -- its bounded numerics are '
                         'wrong, and an abort beats a wrong answer\n' % CURRENT_FILE)
        return text

    lines = text.split('\n')
    args = _dummy_args(lines)
    if args is None:
        # Without the argument list there is no way to tell a local from a dummy argument,
        # and guessing wrong on a dummy argument corrupts the caller's array shape without
        # any compile-time signal. Refuse.
        return text

    # `save` would make a recursive routine share one array across activations. None of the
    # affected routines are recursive, but assert it rather than assume it.
    recursive = any(re.match(r'\s{6,}recursive\s', l, re.I) for l in lines[:80])

    guards, refused, statics, in_decl = [], [], [], False
    for i, ln in enumerate(lines):
        if len(ln) < 7 or (ln and ln[0] in 'CcDd*!'):
            continue                                   # comment line
        is_cont = ln[5] not in ' 0'
        if not is_cont:
            in_decl = bool(RE_DECL_LINE.match(ln))
            # The type keyword is on the statement's FIRST line only. Reading it per-line
            # made every array declared on a continuation default to real*8 -- which sized
            # `integer iactiveline(3,3*ncont)` at 7.2 MB instead of 3.6 MB and pushed it into
            # static storage it did not need.
            elem_bytes = _decl_elem_bytes(ln) if in_decl else 8
        if not in_decl:
            continue

        def rewrite(m):
            arr, dims = m.group(1), m.group(2)
            if arr.lower() in args:
                return m.group(0)                      # a dummy argument is legal F77
            parts, hit, static = _split_dims(dims), [], False
            scoped = {d: b for (f, d), b in FILE_DIM_BOUNDS.items() if f == CURRENT_FILE}
            for k, part in enumerate(parts):
                squashed = part.lower().replace(' ', '')
                for dim, bound in scoped.items():
                    if not re.search(r'(?<![a-z0-9_])%s(?![a-z0-9_])' % re.escape(dim),
                                     squashed, re.I):
                        continue
                    parts[k] = re.sub(r'(?<![a-z0-9_])%s(?![a-z0-9_])' % re.escape(dim),
                                      str(bound), parts[k], flags=re.I)
                    hit.append((dim, bound))
                for dim, bound in DIM_BOUNDS.items():
                    if dim not in squashed:
                        continue
                    bound = ARRAY_DIM_BOUNDS.get((arr.lower(), dim), bound)
                    parts[k] = re.sub(re.escape(dim), str(bound), parts[k], flags=re.I)
                    hit.append((dim, bound))
                if recursive:
                    continue                           # `save` would be wrong; see above
                for dim, bound in STATIC_DIM_BOUNDS.items():
                    # A whole-token match only: `nev` must not fire inside `nevtot`.
                    if not re.search(r'(?<![a-z0-9_])%s(?![a-z0-9_])' % re.escape(dim),
                                     squashed, re.I):
                        continue
                    parts[k] = re.sub(r'(?<![a-z0-9_])%s(?![a-z0-9_])' % re.escape(dim),
                                      str(bound), parts[k], flags=re.I)
                    hit.append((dim, bound))
                    static = True
            if not hit:
                return m.group(0)
            # Stack budget. An unknown extent (an assumed-size `*`, or a bound still
            # symbolic) means this is not a plain local array; leave it alone.
            total = elem_bytes
            for part in parts:
                ext = _extent(part)
                if ext is None or ext <= 0:
                    return m.group(0)
                total *= ext
            # PREFER THE STACK. `save` is not a free substitute for automatic storage: it
            # makes the array persist between calls instead of being fresh each time, and a
            # routine called repeatedly inside an iteration can depend on that. Suspected
            # cause of the contact deck failing to converge ("too many cutbacks") where
            # production solves it, so a problem-size array that FITS on the stack keeps the
            # original semantics and only an oversized one is made static.
            if static and total <= AUTO_ARRAY_MAX_BYTES:
                static = False
            # Two ceilings, because the two storage classes cost different things: the stack
            # one protects a 16 MB stack, the static one protects every user's linear memory.
            cap = STATIC_ARRAY_MAX_BYTES if static else AUTO_ARRAY_MAX_BYTES
            if total > cap:
                refused.append('%s(%s) -> %d bytes of %s' % (
                    arr, dims, total, 'static' if static else 'stack'))
                return m.group(0)
            guards.extend(hit)
            if static:
                statics.append(arr)
            return '%s(%s)' % (arr, ','.join(parts))

        new = re.sub(r'\b([a-z_][a-z0-9_]*)\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)',
                     rewrite, ln, flags=re.I)
        # No column-72 check here: convert() ends with wrap_long_lines() over the whole file,
        # which splits an over-long line onto a continuation. Refusing here instead cost
        # zienzhu.f its whole rewrite over four characters. Verified afterwards -- the sweep
        # asserts every emitted line is within column 72.
        if new != ln:
            lines[i] = new

    for r in refused:
        sys.stderr.write('f77ify: left automatic array unbounded -- %s\n' % r)
    if not guards:
        return text

    # ALL OR NOTHING per file. f2c rejects a file if ANY automatic array survives, so a
    # partial rewrite leaves the routine stubbed exactly as before -- while still paying for
    # every array that did get bounded. Measured: 6 MB of static arrays emitted into two
    # routines that stayed stubbed anyway because one array each was over the ceiling. Give
    # the whole file back instead.
    if refused:
        sys.stderr.write('f77ify: %d array(s) refused, reverting the whole file '
                         '(a partial rewrite is stubbed anyway)\n' % len(refused))
        return text

    # ...and the same applies to arrays that were never MATCHED, not just ones refused. A
    # dimension absent from the tables produces no refusal, so the file could still sail
    # through with some arrays bounded and others left adjustable -- which f2c rejects just
    # the same. Measured: cavity_refine.f and cavityext_refine.f each emitted 1.5 MB of
    # static arrays and stayed stubbed on a dimension not in the table. Re-scan and revert.
    leftover = _automatic_arrays('\n'.join(lines), args)
    if leftover:
        sys.stderr.write('f77ify: %s still adjustable, reverting (file would be stubbed '
                         'regardless)\n' % ', '.join(sorted(leftover)[:4]))
        return text

    out, placed = [], False
    for ln in lines:
        stripped = ln.strip()
        is_comment = bool(ln) and ln[0] in 'CcDd*!'
        # Fixed form: column 6 non-blank/non-zero is a CONTINUATION of the previous
        # statement. Without this the first continuation of the SUBROUTINE argument list
        # looks like an executable line, and the guard gets emitted before the
        # declarations -- which is not valid Fortran. Measured on e_c3d.f.
        is_cont = len(ln) > 5 and ln[5] not in ' 0'
        if (not placed and out and stripped and not is_comment and not is_cont
                and not RE_DECL_LINE.match(ln) and not RE_SUBPROG_HEAD.match(ln)):
            # SAVE first: it is a declaration statement, so it must precede the guard's
            # executable IF. Without it a 1.6 MB array would land on the stack anyway.
            for nm in dict.fromkeys(statics):
                out.append('C     fcweb: static so the bound costs no stack')
                out.append('      save %s' % nm)
            seen = set()
            for dim, bound in guards:
                if dim in seen:
                    continue
                seen.add(dim)
                out.append('C     fcweb: %s bounded a local automatic array' % dim)
                out.append('      if(%s.gt.%d) then' % (dim, bound))
                out.append("         write(*,*) '*ERROR: %s above the wasm build bound'" % dim)
                out.append('         call exit(201)')
                out.append('      endif')
            placed = True
        out.append(ln)

    # Fail CLOSED. If there was nowhere to put the guard -- a subprogram with no executable
    # statement after its declarations -- then the bound would ship without its check, which
    # is the one combination this whole rule exists to prevent. Give the array back its
    # adjustable dimension and let f2c stub the routine: loud and recoverable beats a silent
    # fixed bound. Found by the selftest, not in the wild.
    if not placed:
        sys.stderr.write('f77ify: no place for the guard, bounds reverted\n')
        return text
    return '\n'.join(out)

def convert(text):
    text = truncate_sequence_field(text)
    text = strip_inline_comments(text)
    text = RE_OMP_LINE.sub('C     omp removed', text)
    text = RE_INTENT_STMT.sub('C     intent removed', text)
    text = split_decl_initialisers(text)
    text = expand_reductions(text, declared_dims(text.splitlines()))
    text = expand_allocatables(text)
    text = fix_automatic_arrays(text)
    text = sink_data_statements(text)
    text = hoist_includes(text)
    text = RE_FLUSH.sub(r'\1continue', text)
    text = RE_OPEN_POSITION.sub(r"\1access=", text)
    text = split_semicolons(text)
    text = expand_array_ctors(text)
    # After expand_array_ctors, because that is where `REAL*8, INTENT(IN) :: xg(3,3)`
    # becomes a declaration declared_dims can read. Before it, us3_sub.f's shapes are
    # invisible and every matmul in the file is left for f2c to reject.
    text = expand_matmul_units(text)
    lines = text.splitlines()
    taken = used_labels(lines)
    counter = [8000]
    import itertools
    seccount = itertools.count(1)
    charnames = character_names(lines)
    arraydims = declared_dims(lines)

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

        # strip_inline_comments already did this, and it tracks quotes ACROSS
        # continuations -- doing it again per-line would eat the `!'` that closes
        # zeta_calc's warning string on the following line.
        if not code.strip():
            # line was only a trailing comment
            if label.strip() or cont not in (' ', '0'):
                out.append(label + cont + code)
            continue

        code = RE_BRACKET_SCALAR.sub(r'\1', code)

        # Declarations are off-limits: `real*8 a(3),voldl(0:mi(2),8)` puts voldl( right
        # after a comma, which looks exactly like an argument position -- rewriting it
        # would silently change the array's declared bounds.
        if (not is_cont_line(cont) and RE_SECTION.search(code)
                and not is_declaration(code)):
            expanded = section_assignments(code, seccount, charnames, arraydims)
            if expanded is not None:
                out.extend(expanded)
                continue
            code = sections_in_io(code, seccount, charnames)
            code = sections_as_arguments(code, charnames)

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

    return '\n'.join(wrap_long_lines(declare_generated(out))) + '\n'


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
    # rank 3, column-major: first subscript fastest
    r3 = conv(["h=reshape((/1.d0,2.d0,3.d0,4.d0,5.d0,6.d0/),(/3,1,2/))"])
    assert 'data h(1,1,1) /1.d0/' in r3, r3
    assert 'data h(3,1,1) /3.d0/' in r3, r3
    assert 'data h(1,1,2) /4.d0/' in r3, r3
    assert 'data h(3,1,2) /6.d0/' in r3, r3
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
    assert 'ivout(logfil, 1, mxiter, n)' in conv(["call ivout(logfil, 1, [mxiter], n)"])
    import itertools
    c = itertools.count(1)
    # argument position: the slice becomes the address of its first element
    assert sections_as_arguments('call f(xl2s,pvertex(1:3,k),n)') == 'call f(xl2s,pvertex(1,k),n)'
    # ...but an assignment target must NOT be rewritten that way
    assert sections_as_arguments('field(1:n,1:20)=0.d0') == 'field(1:n,1:20)=0.d0'
    io = sections_in_io('      write(20,*) nodef(1:nopes)', c)
    assert '(nodef(i_fcw1),i_fcw1=1,nopes)' in io, io
    # a quoted format containing ')' must not truncate the control list
    io2 = sections_in_io("      write(88,'(I12)')  nodef(1:nopes)", c)
    assert io2.startswith("      write(88,'(I12)')") and 'i_fcw' in io2, io2
    asg = section_assignments('      field(1:nfield,1:20)=0.d0', c)
    assert asg is not None and any('do i_fcw' in l for l in asg), asg
    assert any('=0.d0' in l for l in asg) and sum('enddo' in l for l in asg) == 2, asg
    # a bare ':' has no bounds here, so it must be declined rather than guessed
    assert section_assignments('      x(:,1)=0.d0', c) is None
    # a CHARACTER substring must never become a loop
    chars = character_names(['      character*81 setname,noset',
                             '      character*(*) text',
                             '      character*1 inpc(*)'])
    assert {'setname', 'noset', 'text', 'inpc'} <= chars, chars
    assert section_assignments("      setname(1:15)='contactelements'", c, chars) is None
    # a name declared on a continuation line must still be recognised
    cont_chars = character_names(['      character*81 set(*),temp,indepties,',
                                  '     &     indeptiet'])
    assert 'indeptiet' in cont_chars, cont_chars
    # and a string-literal RHS is a substring even if the declaration was missed
    assert section_assignments("      unknown(1:1)=' '", c) is None
    assert sections_as_arguments("call f(setname(1:15))", chars) == 'call f(setname(1:15))'
    decl = declare_generated(['      subroutine t(n)', '      implicit none',
                              '      integer n', '      write(6,*) (x(i_fcw1),i_fcw1=1,n)',
                              '      end'])
    assert any(l.strip() == 'integer i_fcw1' for l in decl), decl
    assert decl.index('      integer i_fcw1') == 3, decl
    # must land BEFORE a DATA statement, which may not be preceded by declarations
    d2 = declare_generated(['      subroutine t(n)', '      integer n',
                            '      data k /1/', '      write(6,*) (x(i_fcw1),i_fcw1=1,n)',
                            '      end'])
    assert d2.index('      integer i_fcw1') == 2, d2
    d3 = declare_generated(['      subroutine t(n)', '      integer n',
                            '      include "gauss.f"', '      x=(y(i_fcw1))', '      end'])
    assert d3.index('      integer i_fcw1') == 2, d3
    # a declaration must never be touched by the section rules
    assert is_declaration('real*8 a(3),voldl(0:mi(2),8)')
    assert is_declaration('  integer x(2)') and not is_declaration('call f(x(1:3,k))')
    dec = conv(["real*8 a(3),voldl(0:mi(2),8)"])
    assert 'a(3)' in dec, dec               # untouched by the section rules
    # A bare declaration with no executable statement has nowhere to put the guard, so the
    # bound must be REVERTED rather than shipped unchecked.
    assert 'voldl(0:mi(2),8)' in dec, dec
    # Given somewhere to put it, the local array is bounded AND guarded -- never one alone.
    full = conv(['      subroutine t(mi)', '      integer mi(3)',
                 '      real*8 a(3),voldl(0:mi(2),8)', '      voldl(0,1)=0.d0', '      end'])
    assert 'voldl(0:255,8)' in full, full
    assert 'if(mi(2).gt.255)' in full.replace(' ', ''), full

    # The safety-critical property: a dummy argument may keep an adjustable dimension in F77,
    # so rewriting one would change a caller-supplied shape into a wrong fixed one. Assumed
    # size (`*`) makes that catastrophic and silent, which is why it gets its own assertion.
    dummy = conv(['      subroutine t(vold,mi)', '      integer mi(3)',
                  '      real*8 vold(0:mi(2),*)', '      vold(0,1)=0.d0', '      end'])
    assert 'vold(0:mi(2),*)' in dummy, dummy
    assert '0:255' not in dummy, dummy

    # An executable subscript that merely mentions mi(2) is not a declaration.
    exe = conv(['      subroutine t(mi,v)', '      integer mi(3)', '      real*8 v(0:mi(2),*)',
                '      v(mi(2),1)=0.d0', '      end'])
    assert 'v(mi(2),1)=0.d0' in exe.replace(' ', '').replace('v(mi(2),1)=0.d0', 'v(mi(2),1)=0.d0') \
        or 'v(mi(2),1)' in exe, exe

    # The stack budget must refuse rather than emit: at mi(3)=255 this asks for 40 MB.
    big = fix_automatic_arrays('\n'.join([
        '      subroutine t(mi)', '      integer mi(3)',
        '      real*8 huge_(999,20*mi(3))', '      huge_(1,1)=0.d0', '      end']))
    assert '20*255' not in big, big          # refused, left for the stub path
    assert 'mi(3)' in big, big
    # ...while the named override brings the same shape inside the budget. Note the bounded
    # dimension is the LAST one, which is what makes the override safe -- see
    # ARRAY_DIM_BOUNDS.
    ovr = fix_automatic_arrays('\n'.join([
        '      subroutine t(mi)', '      integer mi(3)',
        '      real*8 field(999,20*mi(3))', '      field(1,1)=0.d0', '      end']))
    assert '20*16' in ovr, ovr      # LAST dimension: safe to bound, and load bearing
    # Every bound in the table must carry a guard -- the whole basis for using fixed bounds.
    for _dim in DIM_BOUNDS:
        assert _dim in ('ncmat_', 'mi(1)', 'mi(2)', 'mi(3)'), _dim

    NL = chr(10)
    # A problem-size dimension gets a large bound AND static storage, so the bound does not
    # land on the stack. SAVE must precede the guard, being a declaration statement.
    st = fix_automatic_arrays(NL.join([
        '      subroutine t(neq)', '      integer neq(2)',
        '      real*8 x(neq(2))', '      x(1)=0.d0', '      end']))
    # It fits the stack (1.6 MB), so it must NOT be made static: `save` changes semantics
    # and is only worth it when the array cannot live on the stack at all.
    assert 'x(200000)' in st, st
    assert 'save' not in st, st
    # An array too big for the stack does become static, and SAVE -- a declaration --
    # must still precede the guard's executable IF.
    # 12 columns, not 6: at nk=80000 a 6-column array is 3.84 MB and correctly stays on the
    # stack, so it no longer exercises the static path. 12 columns is 7.68 MB -- over the
    # stack ceiling, under the static one.
    big = fix_automatic_arrays(NL.join([
        '      subroutine t(nk)', '      integer nk',
        '      real*8 s(12,nk)', '      s(1,1)=0.d0', '      end']))
    assert 's(12,80000)' in big, big
    assert 'save s' in big, big
    assert big.index('save s') < big.index('if(nk.gt.'), big
    # ...and a recursive routine must NOT get save: one array shared across activations.
    rec = fix_automatic_arrays(NL.join([
        '      recursive subroutine t(neq)', '      integer neq(2)',
        '      real*8 x(neq(2))', '      x(1)=0.d0', '      end']))
    assert 'save' not in rec and 'x(neq(2))' in rec, rec
    # a whole-token match only: nev must not fire inside nevtot
    tok = fix_automatic_arrays(NL.join([
        '      subroutine t(nevtot,mi)', '      integer nevtot,mi(3)',
        '      real*8 p(nevtot,6),g(0:mi(2),8)', '      p(1,1)=0.d0', '      end']))
    assert 'p(nevtot,6)' in tok, tok

    # A PARAMETER dimension is a compile-time constant and legal F77 -- not an automatic
    # array. Getting this wrong reverted zienzhu.f, which had been translating fine: the
    # scanner read the statement `parameter(maxmid=400)` as an array named `parameter`.
    par = fix_automatic_arrays(NL.join([
        '      subroutine t(nk,co)', '      integer nk,maxmid', '      parameter(maxmid=400)',
        '      real*8 co(3,*),scpav(6,nk),nmids(maxmid)', '      scpav(1,1)=0.d0', '      end']))
    assert 'scpav(6,80000)' in par, par
    assert 'nmids(maxmid)' in par, par            # the PARAMETER one is left alone
    assert _parameter_names('      parameter(maxmid=400)') == {'maxmid'}
    # ...but a dummy SCALAR used as a dimension is NOT constant -- that is the automatic
    # array itself. Conflating the two let cavity_refine.f emit 1.5 MB and stay stubbed.
    assert _automatic_arrays(NL.join([
        '      subroutine t(netet_)', '      integer netet_',
        '      integer incav(4,netet_)']), {'netet_'}) == {'incav'}

    # File-scoped bounds: `k` is far too common for a global table, but inside near3d.f it
    # is "the number of closest nodes" and ir(k+6) is a genuine automatic array. With this
    # stubbed, production runs a contact analysis and a clean build aborts -- caught by
    # contact.inp, not by anything static.
    global CURRENT_FILE
    CURRENT_FILE = 'near3d.f'
    nr = fix_automatic_arrays(NL.join([
        '      subroutine near3d(x,n,neighbor,k)', '      integer n,k,neighbor(k),ir(k+6)',
        '      real*8 x(n),r(k+6)', '      ir(1)=0', '      end']))
    # `100000+6` rather than `100006`: a constant expression, which is valid F77 and
    # which f2c folds. Only the symbolic `k` had to go.
    assert 'ir(100000+6)' in nr and 'r(100000+6)' in nr, nr
    assert 'neighbor(k)' in nr, nr           # a dummy array keeps its adjustable dimension
    assert 'if(k.gt.100000)' in nr.replace(' ', ''), nr
    CURRENT_FILE = 'somewhere_else.f'
    other = fix_automatic_arrays(NL.join([
        '      subroutine t(n,k)', '      integer n,k,ir(k+6)', '      ir(1)=0', '      end']))
    assert 'ir(k+6)' in other, other          # the same shape elsewhere is untouched
    CURRENT_FILE = ''

    # A file on the skip list must come back untouched, however convertible it looks.
    # matmul/transpose: nested calls, a temporary per intermediate, and the temporaries
    # must be visible to the NEXT lookup or the second level silently gives up.
    _mmdims = {'kshell': ['18', '18'], 'tmg': ['18', '18']}
    _mm, _mmt = expand_matmul(NL.join([
        '      subroutine probe_mm(kshell,tmg)',
        '      real*8 kshell(18,18),tmg(18,18)',
        '      kshell=matmul(matmul(transpose(tmg),kshell),tmg)',
        '      end']), _mmdims)
    assert 'matmul' not in _mm.lower(), _mm
    assert 'call fcwtr(' in _mm and _mm.count('call fcwmm(') == 2, _mm
    assert len(_mmt) == 3, _mmt
    # a redundant paren pair around an operand is the same operand
    _mm2, _ = expand_matmul(NL.join([
        '      subroutine probe_mm2(kshell,tmg)',
        '      real*8 kshell(18,18),tmg(18,18)',
        '      kshell=matmul(matmul(transpose(tmg),kshell),(tmg))',
        '      end']), _mmdims)
    assert 'matmul' not in _mm2.lower(), _mm2
    # matrix x vector picks the vector helper, not the matrix one
    _mm3, _ = expand_matmul(NL.join([
        '      subroutine probe_mm3(bs,ushell,ys)',
        '      real*8 bs(3,18),ushell(18),ys(3)',
        '      ys=matmul(bs,ushell)',
        '      end']), {'bs': ['3', '18'], 'ushell': ['18'], 'ys': ['3']})
    assert 'call fcwmv(' in _mm3 and 'call fcwmm(' not in _mm3, _mm3

    # Generated loop variables must be declared in EVERY subprogram that uses them, not
    # only the first (us3_sub.f has 14 subprograms).
    _multi = [
        '      subroutine one(x,n)', '      real*8 x(*)', '      integer n',
        '      write(6,*) (x(i_fcw1),i_fcw1=1,n)', '      end',
        '      subroutine two(y,m)', '      real*8 y(*)', '      integer m',
        '      write(6,*) (y(i_fcw2),i_fcw2=1,m)', '      end',
    ]
    _dg = declare_generated(_multi)
    _decls = [i for i, l in enumerate(_dg) if l.strip().startswith('integer i_fcw')]
    assert len(_decls) == 2, _dg
    # each declaration must sit inside the subprogram that uses it
    _ones = _dg.index('      subroutine one(x,n)')
    _twos = _dg.index('      subroutine two(y,m)')
    assert _ones < _decls[0] < _twos < _decls[1], (_decls, _ones, _twos)
    assert _dg[_decls[0]].strip() == 'integer i_fcw1', _dg[_decls[0]]
    assert _dg[_decls[1]].strip() == 'integer i_fcw2', _dg[_decls[1]]

    # A FUNCTION head must not be read as an array declaration (calcview.f's fform).
    CURRENT_FILE = 'probe_fform.f'
    _fn = NL.join([
        '      subroutine probe_fform(n,a)',
        '      integer n',
        '      real*8 a(n)',
        '      a(1)=0.d0',
        '      end',
        '      real*8 function fform(x,y,idata,rdata)',
        '      real*8 x,y',
        '      integer idata(*)',
        '      real*8 rdata(*)',
        '      fform=0.d0',
        '      end',
    ])
    _args = _dummy_args(_fn.split(NL))
    _autos = _automatic_arrays(_fn, _args)
    assert 'fform' not in _autos, _autos
    CURRENT_FILE = ''

    global SKIP_FILES
    _saved_skip = SKIP_FILES
    SKIP_FILES = frozenset(('probe_skip.f',))
    CURRENT_FILE = 'probe_skip.f'
    skipped = fix_automatic_arrays(NL.join([
        '      subroutine probe_skip(ncont,x)', '      integer ncont,ia(3,3*ncont)',
        '      real*8 x(3)', '      ia(1,1)=0', '      end']))
    assert 'ia(3,3*ncont)' in skipped, skipped
    assert 'fcweb' not in skipped, skipped
    SKIP_FILES = _saved_skip
    CURRENT_FILE = ''

    # patch.f declares z(ipoints,ipoints) -- SQUARE in a problem-size dimension. Even a
    # modest bound is millions of elements, so the static ceiling must refuse it. This is the
    # case that makes a per-array budget mandatory rather than tidy.
    sq = fix_automatic_arrays(NL.join([
        '      subroutine t(nk)', '      integer nk',
        '      real*8 z(nk,nk)', '      z(1,1)=0.d0', '      end']))
    assert 'z(nk,nk)' in sq, sq
    assert '200000' not in sq, sq

    # REGRESSION, from ARPACK dseupd.f: a subprogram whose SUBROUTINE line sits below a long
    # header comment. The argument list must still be found, or d(nev) and z(ldz,nev) -- both
    # arguments -- get rewritten into fixed shapes and every frequency analysis breaks with
    # nothing failing to compile.
    deep = ['C' + ' comment' * 3] * 200 + [
        '      subroutine dseupd(rvec,d,z,ldz,nev,info)',
        '      integer nev,ldz,info', '      logical rvec',
        '      real*8 d(nev),z(ldz,nev)', '      d(1)=0.d0', '      end']
    got = fix_automatic_arrays(NL.join(deep))
    assert 'd(nev)' in got and 'z(ldz,nev)' in got, got[-400:]
    assert '10000' not in got, got[-400:]
    # ...and with NO header at all, nothing may be rewritten: local and dummy are
    # indistinguishable, and guessing wrong on a dummy is silent corruption.
    assert _dummy_args(['      real*8 x(nev)']) is None
    assert 'x(nev)' in fix_automatic_arrays('      real*8 x(nev)')
    long_l = ' ' * 39 + 'if(ikactmech(idm).eq.jdof-1) goto 8012'
    w = wrap_long_lines([long_l])
    assert all(len(x) <= 72 for x in w), [len(x) for x in w]
    assert w[1].startswith('     &'), w
    assert ''.join(x[6:] if x.startswith('     &') else x for x in w).replace(' ', '') \
        == long_l.replace(' ', ''), w
    # a line with no safe break point is left intact rather than mangled
    nobreak = '      ' + 'a' * 80
    assert wrap_long_lines([nobreak]) == [nobreak]
    dd = declared_dims(['      real*8 tm(4,6),other(3)'])
    assert dd['tm'] == ['4', '6'], dd
    bare = section_assignments('      tm(:,:) = 0.d0', c, (), dd)
    assert bare is not None and sum('do i_fcw' in l for l in bare) == 2, bare
    assert any('1,4' in l for l in bare) and any('1,6' in l for l in bare), bare
    # still declined when the declaration is unknown
    assert section_assignments('      zz(:,:)=0.d0', c, (), dd) is None
    al = expand_allocatables('\n'.join([
        '      integer,dimension(:),allocatable::koncp',
        '      allocate(koncp(nkon))',
        '      koncp(1)=2',
        '      deallocate(koncp)']))
    assert 'integer koncp(200000)' in al and 'save koncp' in al, al
    assert '(nkon).gt.200000' in al and 'deallocate' not in al, al
    # a literal dimension is preserved rather than blown up to the bound
    al2 = expand_allocatables('\n'.join([
        '      integer,dimension(:,:),allocatable::iponorcp',
        '      allocate(iponorcp(2,nkon))']))
    assert 'iponorcp(2,200000)' in al2, al2
    sk = sink_data_statements('\n'.join([
        '      subroutine t()',
        '      real*8 a(2)',
        '      data a /1.d0,2.d0/',
        '      real*8 b(2)',
        '      data b /3.d0,4.d0/',
        '      x=1',
        '      end']))
    sl = [l.strip() for l in sk.strip().split('\n')]
    assert sl.index('real*8 b(2)') < sl.index('data a /1.d0,2.d0/'), sl
    assert sl.index('data b /3.d0,4.d0/') < sl.index('x=1'), sl
    im = sink_data_statements('\n'.join([
        '      subroutine u()', '      DATA((z(i,j),i=1,2),j=1,2) /1,2,3,4/',
        '      real*8 z(2,2)', '      end']))
    assert im.index('real*8 z(2,2)') < im.index('DATA(('), im
    assert sl.index('data a /1.d0,2.d0/') < sl.index('data b /3.d0,4.d0/'), 'order kept'
    di = split_decl_initialisers(
        '      subroutine t()\n      integer iexpbr1(2) /11,11/\n      end\n')
    assert 'iexpbr1(2)' in di and 'data iexpbr1 /11,11/' in di, di
    assert '/11,11/' not in di.split('data')[0], di
    keep = '      subroutine t()\n      integer q(2)\n      data q /4,3/\n      end\n'
    assert split_decl_initialisers(keep).count('/4,3/') == 1, 'DATA is not a declaration'
    rd = expand_reductions('      hmax=maxval(edge)\n', {'edge': ['6']})
    assert 'fcwmxv(edge,6)' in rd, rd
    assert 'real*8 fcwmxv' in rd, rd
    rs = expand_reductions('      d=sum(abs(g(:,i)))\n', {'g': ['n', 'm']})
    assert 'fcwsab(g(1,i),n)' in rs, rs
    assert 'maxval(z)' in expand_reductions('      a=maxval(z)\n', {}), 'no dims: leave'
    seq = truncate_sequence_field('      SUBROUTINE G(A, B, C,' + ' ' * 45 + 'GRS   10')
    assert 'GRS' not in seq and 'SUBROUTINE G(A, B, C,' in seq, seq
    over = '     & jj,mi(*),ii,ncount,nope,itypflag,inum(50000),nen(3,8),maxcommon,'
    assert truncate_sequence_field(over).strip() == over.strip(), 'code is not a seq field'
    ic = strip_inline_comments('      x=1 ! note\n      call f(a);\n      y="a!b"\n')
    assert '! note' not in ic and ic.count(';') == 0 and '"a!b"' in ic, ic
    cont2 = strip_inline_comments(
        "      write(*,*) 'warning: reynolds outside\n     & valid range !'\n")
    assert cont2.count(chr(39)) == 2, cont2
    al = expand_allocatables('\n'.join([
        '      subroutine t(mi,nkon)',
        '      real*8,dimension(:,:),allocatable::thickecp',
        '      allocate(thickecp(mi(3),nkon))',
        '      deallocate(thickecp)', '      end']))
    assert 'thickecp(20,200000)' in al, al
    assert '(mi(3)).gt.20' in al and '(nkon).gt.200000' in al, al
    print('f77ify selftest OK')


def main():
    if len(sys.argv) == 2 and sys.argv[1] == '--selftest':
        return selftest()
    src, dst = sys.argv[1], sys.argv[2]
    global CURRENT_FILE
    CURRENT_FILE = os.path.basename(src)          # selects FILE_DIM_BOUNDS entries
    with open(src, 'r', errors='replace') as f:
        text = f.read()
    with open(dst, 'w') as f:
        f.write(convert(text))


if __name__ == '__main__':
    main()
