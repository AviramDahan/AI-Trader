"""Reader gates; the full Linux image proof covers real encrypted round-trip."""
import unittest
import sys
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import active_snapshot
import recovery_state
import test_sec_schema7_compat


class RecoverySchema7Tests(unittest.TestCase):
    def connection(self, restoring=False, invalid=False):
        conn = Mock()
        checks = test_sec_schema7_compat.Schema7BridgeTests.connection(
            missing=('si_filing_jobs', 'accession') if invalid else None)
        metadata = list(checks.execute.side_effect)
        conn.execute.side_effect = [
            *([Mock()] if restoring else [Mock(), Mock()]),
            Mock(fetchone=lambda: {'version': 7}),
            *metadata,
            Mock(fetchone=lambda: {'ok': False}, fetchall=lambda: []),
        ]
        conn.__enter__ = Mock(return_value=conn)
        conn.__exit__ = Mock(return_value=False)
        return conn

    def test_export_accepts_complete_seven_before_portfolio_validation(self):
        conn = self.connection()
        with patch('psycopg.connect', return_value=conn):
            with self.assertRaisesRegex(ValueError, 'stable_scanner_identity_missing'):
                recovery_state.export_postgres('isolated-fixture')
        self.assertEqual(conn.execute.call_count, 8)

    def test_restore_accepts_complete_seven_without_bypassing_worker_lock(self):
        conn = self.connection(restoring=True)
        with patch('psycopg.connect', return_value=conn), patch.object(active_snapshot, 'validate'):
            with self.assertRaisesRegex(ValueError, 'workers_must_be_stopped'):
                active_snapshot.import_data({'version': 3}, 'isolated-fixture')
        self.assertEqual(conn.execute.call_count, 7)

    def test_export_and_restore_reject_incomplete_seven_before_writes(self):
        for restoring in (False, True):
            conn = self.connection(restoring=restoring, invalid=True)
            with patch('psycopg.connect', return_value=conn), patch.object(active_snapshot, 'validate'):
                with self.assertRaisesRegex(RuntimeError, 'structure_incomplete'):
                    if restoring:
                        active_snapshot.import_data({'version': 3}, 'isolated-fixture')
                    else:
                        recovery_state.export_postgres('isolated-fixture')
            self.assertFalse(any('INSERT ' in str(call) or 'UPDATE ' in str(call)
                                 for call in conn.execute.call_args_list))


if __name__ == '__main__':
    unittest.main()
