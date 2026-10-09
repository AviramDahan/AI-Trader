import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cloud_runtime
from sec_schema7_compat import REQUIRED_COLUMNS, REQUIRED_INDEXES, assert_sec_schema7


class Schema7BridgeTests(unittest.TestCase):
    @staticmethod
    def connection(version=7, missing=None):
        names = [(table, column) for table, cols in REQUIRED_COLUMNS.items() for column in cols]
        if missing:
            names.remove(missing)
        conn = Mock()
        conn.execute.side_effect = [
            Mock(fetchall=lambda: [{'version': 1}, {'version': 6}, {'version': version}]),
            Mock(fetchall=lambda: [{'table_name': t, 'column_name': c} for t, c in names]),
            Mock(fetchall=lambda: [{'indexname': i} for i in REQUIRED_INDEXES]),
        ]
        return conn

    def test_complete_schema7_and_no_schema_creation(self):
        conn = self.connection()
        assert_sec_schema7(conn)
        self.assertEqual(conn.execute.call_count, 3)

    def test_missing_column_and_history_fail_closed(self):
        with self.assertRaisesRegex(RuntimeError, 'structure_incomplete'):
            assert_sec_schema7(self.connection(missing=('si_filing_jobs', 'accession')))
        with self.assertRaisesRegex(RuntimeError, 'history_incomplete'):
            assert_sec_schema7(self.connection(version=8))

    def test_activation_requires_complete_seven(self):
        self.assertEqual(cloud_runtime.SCHEMA_VERSION, 7)
        self.assertEqual(cloud_runtime.SUPPORTED_SCHEMAS, (7,))
