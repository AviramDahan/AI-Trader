"""Real pg_dump -> age -> decrypt -> pg_restore on isolated PostgreSQL schemas.

No off-server account required; this validates restore content, not remote delivery.
"""
import os
import shutil
import subprocess

import pytest
import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo


def test_encrypted_dump_restore(pg,tmp_path):
    dump=os.getenv('TEST_PG_DUMP') or shutil.which('pg_dump')
    restore=os.getenv('TEST_PG_RESTORE') or shutil.which('pg_restore')
    age=os.getenv('TEST_AGE') or shutil.which('age')
    keygen=os.getenv('TEST_AGE_KEYGEN') or shutil.which('age-keygen')
    if not all([dump,restore,age,keygen]):
        pytest.skip('pg_dump/pg_restore/age binaries required; encrypted restore NOT verified')
    schema=conninfo_to_dict(pg)['options'].split('search_path=')[1]
    key=tmp_path/'restore.key'
    generated=subprocess.run([keygen,'-o',str(key)],capture_output=True,check=True)
    public=subprocess.run([keygen,'-y',str(key)],capture_output=True,check=True).stdout.decode().strip()
    cipher=tmp_path/'test.dump.age'
    with psycopg.connect(pg) as conn:
        conn.execute("INSERT INTO scanner_settings(key,value_json,updated_at) VALUES('backup-proof','{\"test\":true}','2026-01-01')")
    childenv={**os.environ,'PGDATABASE':pg}
    producer=subprocess.Popen([dump,'-d',pg,'-Fc','--no-owner','--no-acl','--schema',schema],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=childenv)
    encrypted=subprocess.run([age,'-r',public,'-o',str(cipher)],stdin=producer.stdout,capture_output=True)
    producer.stdout.close()
    producer.wait(timeout=60)
    assert producer.returncode==encrypted.returncode==0, producer.stderr.read().decode(errors='replace')
    assert b'backup-proof' not in cipher.read_bytes()
    # Only this test's UUID schema is dropped. Restore recreates it from the dump.
    from psycopg import sql
    with psycopg.connect(pg,autocommit=True) as conn:
        conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))
    decrypt=subprocess.Popen([age,'-d','-i',str(key),str(cipher)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    result=subprocess.run([restore,'--no-owner','--no-acl','--exit-on-error','--single-transaction','-d',pg],
                          stdin=decrypt.stdout,capture_output=True,env=childenv)
    decrypt.stdout.close(); decrypt.wait(timeout=60)
    assert decrypt.returncode==result.returncode==0, 'isolated restore failed'
    with psycopg.connect(pg) as conn:
        assert conn.execute("SELECT value_json FROM scanner_settings WHERE key='backup-proof'").fetchone()[0]=='{"test":true}'
        assert conn.execute('SELECT max(version) FROM schema_migrations').fetchone()[0]==2
