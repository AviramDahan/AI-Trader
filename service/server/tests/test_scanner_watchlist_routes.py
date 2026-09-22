import os
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

SERVER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_DIR))
import database
from routes import create_app


class ScannerWatchlistRoutesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        database.DATABASE_URL = ""
        database._SQLITE_DB_PATH = os.path.join(self.tmp.name, "watchlist.db")
        database.init_database()
        conn = database.get_db_connection()
        conn.execute("INSERT INTO agents(name,token,role,cash) VALUES('admin','admin-token','admin',100000)")
        conn.execute("INSERT INTO agents(name,token,role,cash) VALUES('regular','regular-token','agent',100000)")
        conn.commit(); conn.close()
        self.client = TestClient(create_app())

    def tearDown(self):
        self.tmp.cleanup()

    def test_admin_can_add_and_remove_without_creating_market_activity(self):
        denied = self.client.post("/api/scanner/news-watchlist", json={"ticker":"NVDA"},
                                  headers={"Authorization":"Bearer regular-token"})
        self.assertEqual(denied.status_code,403)
        added = self.client.post("/api/scanner/news-watchlist", json={"ticker":"nvda"},
                                 headers={"Authorization":"Bearer admin-token"})
        self.assertEqual(added.status_code,200,added.text)
        self.assertEqual(added.json()["item"]["ticker"],"NVDA")
        self.assertFalse(added.json()["paper_trade_created"])
        conn = database.get_db_connection()
        self.assertEqual(conn.execute("SELECT count(*) FROM scanner_signals").fetchone()[0],0)
        self.assertEqual(conn.execute("SELECT count(*) FROM scanner_trades").fetchone()[0],0)
        conn.close()
        removed = self.client.delete("/api/scanner/news-watchlist/NVDA",
                                     headers={"Authorization":"Bearer admin-token"})
        self.assertEqual(removed.status_code,200)
        self.assertEqual(removed.json()["item"]["enabled"],0)

    def test_invalid_ticker_fails_closed(self):
        response = self.client.post("/api/scanner/news-watchlist", json={"ticker":"../../bad"},
                                    headers={"Authorization":"Bearer admin-token"})
        self.assertEqual(response.status_code,400)


if __name__ == "__main__":
    unittest.main()
