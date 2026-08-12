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


def declare_generated(lines):
    """Declare the loop variables the section rules invent.

    ccx compiles with `implicit none`, so an undeclared i_fcwN is a hard error. They
    are inserted just before the first executable statement, which is the last point
    a declaration is still legal.
    """
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


def convert(text):
    text = truncate_sequence_field(text)
    text = strip_inline_comments(text)
    text = RE_OMP_LINE.sub('C     omp removed', text)
    text = RE_INTENT_STMT.sub('C     intent removed', text)
    text = split_decl_initialisers(text)
    text = expand_reductions(text, declared_dims(text.splitlines()))
    text = expand_allocatables(text)
    text = sink_data_statements(text)
    text = hoist_includes(text)
    text = RE_FLUSH.sub(r'\1continue', text)
    text = RE_OPEN_POSITION.sub(r"\1access=", text)
    text = split_semicolons(text)
    text = expand_array_ctors(text)
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
    assert 'voldl(0:mi(2),8)' in dec, dec
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
    with open(src, 'r', errors='replace') as f:
        text = f.read()
    with open(dst, 'w') as f:
        f.write(convert(text))


if __name__ == '__main__':
    main()
