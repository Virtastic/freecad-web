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
import glob
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

bad = 0
for path in sorted(glob.glob('.github/workflows/*.yml')):
    try:
        yaml.load(io.open(path, encoding='utf-8'), NoDuplicates)
        print('  ok    %s' % path)
    except Exception as exc:
        print('  FAIL  %s: %s' % (path, str(exc).replace('\n', ' ')))
        bad += 1
sys.exit(1 if bad else 0)
