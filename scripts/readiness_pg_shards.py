"""Run all PG test files across isolated CI runners, never concurrent shared DBs."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]


def partition(root, count):
    suite = root / 'service/server/tests_pg'
    # Both pytest default filename patterns; no hand-maintained test allowlist.
    files = sorted({*suite.rglob('test_*.py'), *suite.rglob('*_test.py')})
    if type(count) is not int or not 1 <= count <= len(files):
        raise ValueError('invalid_pg_shard_count_or_empty_suite')
    return [[p.relative_to(root).as_posix() for p in files[index::count]]
            for index in range(count)]


class ShardCollection:
    def __init__(self, parts, index):
        self.parts, self.index = parts, index

    @pytest.hookimpl(trylast=True)
    def pytest_collection_modifyitems(self, config, items):
        # Collect the UNCHANGED full suite once (including all import/hooks and
        # parametrization), then partition the actual collected node IDs.
        owners = {file: index for index, part in enumerate(self.parts) for file in part}
        if len(owners) != sum(map(len, self.parts)):
            raise pytest.UsageError('overlapping_pg_file_partitions')
        groups = [[] for _ in self.parts]
        ids = [item.nodeid for item in items]
        if len(set(ids)) != len(ids):
            raise pytest.UsageError('duplicate_pg_collected_node_ids')
        for item in items:
            file = item.nodeid.split('::', 1)[0]
            if file not in owners:
                raise pytest.UsageError('unassigned_pg_collected_node')
            groups[owners[file]].append(item)
        if any(not group for group in groups):
            raise pytest.UsageError('empty_pg_collected_shard')
        # Every original item has exactly one owner; no per-test allowlist or
        # skip. Both isolated jobs must pass the whole-workflow release gate.
        selected = groups[self.index]
        excluded = [item for index, group in enumerate(groups) if index != self.index for item in group]
        manifest = dict(index=self.index, count=len(groups), full_count=len(ids),
                        shard_counts=list(map(len, groups)),
                        full_node_ids_sha256=hashlib.sha256('\n'.join(sorted(ids)).encode()).hexdigest())
        print('PG_SHARD_COLLECTION ' + json.dumps(manifest, sort_keys=True), flush=True)
        config.hook.pytest_deselected(items=excluded)
        items[:] = selected


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--index', required=True, type=int)
    parser.add_argument('--count', required=True, type=int)
    args = parser.parse_args(argv)
    shards = partition(ROOT, args.count)
    if not 0 <= args.index < args.count:
        parser.error('shard index outside partition')
    # Same directory/flags as the original gate; the plugin sees full collected
    # node IDs rather than trusting an independently collected filename count.
    return pytest.main([str(ROOT / 'service/server/tests_pg'), '-q', '--durations=15'],
                       plugins=[ShardCollection(shards, args.index)])


if __name__ == '__main__':
    raise SystemExit(main())
