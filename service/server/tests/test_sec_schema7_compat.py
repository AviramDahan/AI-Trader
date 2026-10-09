import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cloud_runtime
from sec_schema7_compat import REQUIRED_COLUMNS, REQUIRED_INDEXES, REQUIRED_CONSTRAINTS, assert_sec_schema7


class Schema7BridgeTests(unittest.TestCase):
    @staticmethod
    def connection(version=7, missing=None, missing_constraint=None):
        names = [(table, column) for table, cols in REQUIRED_COLUMNS.items() for column in cols]
        if missing:
            names.remove(missing)
        conn = Mock()
        conn.execute.side_effect = [
            Mock(fetchall=lambda: [{'version': v} for v in [*range(1, 7), version]]),
            Mock(fetchall=lambda: [{'table_name': t, 'column_name': c} for t, c in names]),
            Mock(fetchall=lambda: [{'indexname': i} for i in REQUIRED_INDEXES]),
            Mock(fetchall=lambda: [dict(table_name=t, constraint_type=k, column_names=list(cols), referenced_table=ref)
                for t, k, cols, ref in REQUIRED_CONSTRAINTS if (t, k, cols, ref) != missing_constraint]),
        ]
        return conn

    def test_complete_schema7_and_no_schema_creation(self):
        conn = self.connection()
        assert_sec_schema7(conn)
        self.assertEqual(conn.execute.call_count, 4)

    def test_missing_column_and_history_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError, 'structure_incomplete'):
            assert_sec_schema7(self.connection(missing=('si_filing_jobs', 'accession')))
        with self.assertRaisesRegex(RuntimeError, 'history_incomplete'):
            assert_sec_schema7(self.connection(version=8))
        with self.assertRaisesRegex(RuntimeError, 'constraints_incomplete'):
            assert_sec_schema7(self.connection(missing_constraint=('si_filing_jobs','f',
                ('universe_snapshot_id',),'si_universe_snapshots')))

    def test_bridge_keeps_normal_migration_target_at_six(self):
        self.assertEqual(cloud_runtime.SCHEMA_VERSION, 6)
        self.assertEqual(cloud_runtime.SUPPORTED_SCHEMAS, (6, 7))
