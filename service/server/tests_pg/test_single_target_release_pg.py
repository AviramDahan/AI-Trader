"""Real catalog and read-only snapshot verification; destructive test_* schema only."""
import pytest
import database
from single_target_release import assert_transition_schema


def test_complete_006_readonly_does_not_rewrite_history(pg):
    with database.get_db_connection() as db:
        before = [dict(r) for r in db.execute('SELECT * FROM schema_migrations ORDER BY version')]
    assert_transition_schema(6)
    assert_transition_schema(6)
    with database.get_db_connection() as db:
        assert [dict(r) for r in db.execute('SELECT * FROM schema_migrations ORDER BY version')] == before
    with pytest.raises(RuntimeError, match='history_incomplete'):
        assert_transition_schema(5)


@pytest.mark.parametrize('damage', [
    'DELETE FROM schema_migrations WHERE version=6',
    'DELETE FROM schema_migrations WHERE version=4',
    'INSERT INTO schema_migrations(version) VALUES(7)',
    'ALTER TABLE scanner_orders DROP COLUMN plan_json',
    'ALTER TABLE scanner_orders ALTER COLUMN plan_json DROP NOT NULL',
    'ALTER TABLE scanner_orders ALTER COLUMN plan_json DROP DEFAULT',
    "ALTER TABLE scanner_orders ALTER COLUMN plan_json SET DEFAULT '[]'",
    'ALTER TABLE scanner_orders ALTER COLUMN plan_json TYPE varchar(200)',
    'ALTER TABLE scanner_signals ALTER COLUMN tp2 SET NOT NULL',
    'ALTER TABLE scanner_signals ALTER COLUMN tp3 SET NOT NULL',
    'ALTER TABLE scanner_signals ALTER COLUMN rr2 SET NOT NULL',
    'ALTER TABLE scanner_signals ALTER COLUMN rr3 SET NOT NULL',
    'ALTER TABLE scanner_trades ALTER COLUMN tp2 SET NOT NULL',
    'ALTER TABLE scanner_trades ALTER COLUMN tp3 SET NOT NULL',
])
def test_resume_rejects_incomplete_history_or_006_effects(pg, damage):
    with database.get_db_connection() as db:
        db.execute(damage)
    with pytest.raises(RuntimeError, match='single_target_'):
        assert_transition_schema(6)


def test_preflight_connection_is_enforced_readonly(pg, monkeypatch):
    import contextlib
    original = database.get_db_connection
    @contextlib.contextmanager
    def checked_connection():
        with original() as db:
            yield db
            assert db.execute('SHOW transaction_read_only').fetchone()['transaction_read_only'] == 'on'
            assert db.execute('SHOW transaction_isolation').fetchone()['transaction_isolation'] == 'repeatable read'
    monkeypatch.setattr(database, 'get_db_connection', checked_connection)
    assert_transition_schema(6)
