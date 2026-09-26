"""Real PostgreSQL tests are opt-in and destructive ONLY inside test_* schemas."""
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def no_external_requests(monkeypatch):
    monkeypatch.delenv('TELEGRAM_BOT_TOKEN',raising=False)
    monkeypatch.delenv('TELEGRAM_CHAT_ID',raising=False)
    monkeypatch.setenv('STOCK_SCANNER_TELEGRAM_PORTFOLIO_STATUS_ENABLED','false')
    monkeypatch.setenv('STOCK_SCANNER_NEWS_FAST_MARKET','false')
    monkeypatch.setenv('TELEGRAM_NEWS_STREAM_ENABLED','false')
    def blocked(*args,**kwargs):
        raise AssertionError('External HTTP forbidden in PostgreSQL tests')
    monkeypatch.setattr(requests.sessions.Session,'request',blocked)


@pytest.fixture
def pg(monkeypatch):
    url=os.getenv('TEST_POSTGRES_URL')
    if not url:
        pytest.skip('TEST_POSTGRES_URL not set; PostgreSQL NOT verified')
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo
    import database
    import config
    import migrations
    name='test_'+uuid.uuid4().hex
    with psycopg.connect(url,autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(name)))
    scoped=make_conninfo(url,options='-c search_path='+name)
    monkeypatch.setattr(config,'DATABASE_URL',scoped)
    monkeypatch.setattr(database,'DATABASE_URL',scoped)
    monkeypatch.setenv('PGOPTIONS','-c search_path='+name)
    try:
        migrations.migrate()
        yield scoped
    finally:
        with psycopg.connect(url,autocommit=True) as admin:
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(name)))
