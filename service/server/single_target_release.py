"""Read-only preflight for the explicitly approved single-target transition.

No init, migrations, worker startup or state repair. Resume requires both the
complete numbered history and the concrete effects of 006 on the same snapshot.
"""
import os


def assert_transition_schema(expected):
    from database import get_db_connection
    if expected not in (5, 6):
        raise ValueError('unsupported_single_target_transition')
    with get_db_connection() as db:
        db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        rows = db.execute('SELECT version,applied_at FROM schema_migrations ORDER BY version').fetchall()
        if [r['version'] for r in rows] != list(range(1, expected + 1)) or any(r['applied_at'] is None for r in rows):
            raise RuntimeError('single_target_migration_history_incomplete')
        if expected == 5:
            return
        rows = db.execute("""SELECT table_name,column_name,is_nullable,data_type,column_default
            FROM information_schema.columns WHERE table_schema=current_schema()
            AND table_name IN ('scanner_orders','scanner_signals','scanner_trades')""").fetchall()
        columns = {(r['table_name'], r['column_name']): r for r in rows}
        for table, names in [('scanner_signals', ('tp2', 'tp3', 'rr2', 'rr3')), ('scanner_trades', ('tp2', 'tp3'))]:
            for name in names:
                if columns.get((table, name), {}).get('is_nullable') != 'YES':
                    raise RuntimeError('single_target_schema_006_incomplete')
        plan = columns.get(('scanner_orders', 'plan_json'), {})
        if (plan.get('data_type') != 'text' or plan.get('is_nullable') != 'NO'
                or plan.get('column_default') != "'{}'::text"):
            raise RuntimeError('single_target_schema_006_plan_invalid')


def assert_creation_disabled():
    import single_target_activation as activation
    # A bridge may be incapable of creation even when a stale env flag is true.
    # Reject that configuration before replacing it with a capable binary.
    if os.getenv('STOCK_SCANNER_SINGLE_TARGET_V2_ENABLED', 'false').lower() != 'false' or activation.enabled():
        raise RuntimeError('single_target_creation_must_be_disabled')


def assert_bridge(expected):
    import cloud_runtime as cloud
    import single_target_activation as activation
    if (cloud.SCHEMA_VERSION != 5 or cloud.SUPPORTED_SCHEMAS != (5, 6)
            or cloud.SINGLE_TARGET_ROLLBACK_CAPABILITY != 'v2-format3-holds-legacy-v1'
            or activation.CREATION_CAPABLE):
        raise RuntimeError('single_target_rollback_bridge_required')
    assert_creation_disabled()
    assert_transition_schema(expected)
