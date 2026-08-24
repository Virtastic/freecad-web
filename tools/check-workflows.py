# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Reject duplicate mapping keys in the workflow files, which PyYAML will not.

    python tools/check-workflows.py

yaml.safe_load keeps the LAST of a duplicated key and says nothing. GitHub refuses the
workflow outright: the run appears, fails in under a second, and has no log and no jobs to
look at -- `gh run view --log` answers "log not found", which reads like an API problem
rather than a syntax error.

That happened here: an edit inserted `id:` into a step that already had one, and the only
symptom was a run with a zero-second duration.
"""
import io
import sys
import fnmatch
import glob
import re
import yaml


class NoDuplicates(yaml.SafeLoader):
    pass


def _mapping(loader, node, deep=False):
    seen = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, 'duplicate key %r' % (key,), key_node.start_mark)
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


NoDuplicates.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)

def scripts_vs_paths(path, doc, text):
    """A workflow that runs a script but does not watch it will not rerun when it changes.

    This has cost two silent no-op iterations: a fix was committed and pushed, no run was
    triggered, and the last result shown was the failure the fix addressed -- which reads
    exactly like the fix not working. Cheap to check, so check it.
    """
    on = doc.get('on') or doc.get(True) or {}
    watched = set()
    for evt in ('push', 'pull_request'):
        spec = on.get(evt) if isinstance(on, dict) else None
        if isinstance(spec, dict):
            watched.update(spec.get('paths') or [])
    if not watched:
        return []          # watches everything, or is dispatch-only

    invoked = set(re.findall(r'(?:^|\s)(?:bash|sh)\s+([A-Za-z0-9_./-]+\.sh)', text))
    missing = []
    for s in sorted(invoked):
        # Steps often run from a build directory, so a script is invoked as
        # ../scratchpad/x.sh while on.push.paths names it scratchpad/x.sh. Compare the
        # repo-relative form too, or the check reports a file that IS watched.
        forms = {s, s.lstrip('./')}
        t = s
        while t.startswith('../'):
            t = t[3:]
            forms.add(t)
        if any(fnmatch.fnmatch(f, pat.strip("'\"")) for f in forms for pat in watched):
            continue
        missing.append(s)
    return missing


bad = 0
for path in sorted(glob.glob('.github/workflows/*.yml')):
    text = io.open(path, encoding='utf-8').read()
    try:
        doc = yaml.load(io.StringIO(text), NoDuplicates)
    except Exception as exc:
        print('  FAIL  %s: %s' % (path, str(exc).replace('\n', ' ')))
        bad += 1
        continue
    missing = scripts_vs_paths(path, doc, text) if isinstance(doc, dict) else []
    if missing:
        print('  FAIL  %s runs these but does not watch them:' % path)
        for m in missing:
            print('          %s' % m)
        print('        Add them to on.push.paths, or the workflow will not rerun when '
              'they change.')
        bad += 1
    else:
        print('  ok    %s' % path)
sys.exit(1 if bad else 0)
