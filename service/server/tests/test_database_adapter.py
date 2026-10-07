import os
import sys


SERVER_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from database import _adapt_sql_for_postgres
from database import DatabaseCursor
from unittest.mock import Mock
import pytest


def test_postgres_adapter_escapes_like_percent_literals():
    query = _adapt_sql_for_postgres(
        "SELECT * FROM signals WHERE content LIKE '%@%' AND title LIKE '%source%' AND id = ?"
    )

    assert "content LIKE '%%@%%'" in query
    assert "title LIKE '%%source%%'" in query
    assert query.endswith("id = %s")


def test_postgres_adapter_preserves_existing_escaped_percent_literals():
    query = _adapt_sql_for_postgres("SELECT * FROM signals WHERE content LIKE '%%引用%%'")

    assert "LIKE '%%引用%%'" in query


@pytest.mark.parametrize('prefix',['','\n    ','\t\r\n '])
@pytest.mark.parametrize('has_id',[True,False])
def test_insert_id_detection_accepts_multiline_sql(prefix,has_id):
    driver=Mock()
    driver.fetchone.side_effect=[{'exists':1},{'id':17}] if has_id else [None]
    cursor=DatabaseCursor(driver,'postgres')
    cursor.execute(prefix+'INSERT INTO synthetic(value) VALUES(?)',('isolated',))
    assert driver.execute.call_args_list[0].args[1]==('synthetic',)
    assert driver.execute.call_args.args[1]==('isolated',)
    assert driver.execute.call_args.args[0].endswith(' RETURNING id') is has_id
    assert cursor.lastrowid==(17 if has_id else None)
