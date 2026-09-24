import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import Mock, patch
import pandas as pd
import telegram_charts


class ChartTests(unittest.TestCase):
    def trade(self):
        return dict(id=1,ticker="TEST",entry_price=100,original_stop=97,tp1=103,tp2=106,tp3=109,
                    opened_at="2026-09-22T17:00:00Z",strategy="single")

    def frame(self):
        return pd.DataFrame({"Open":[99.]*20,"High":[101.]*20,"Low":[98.]*20,"Close":[100.]*20},
                            index=pd.date_range("2026-09-22T12:00:00Z",periods=20,freq="15min"))

    def test_renders_png_from_real_supplied_ohlc_not_model(self):
        png = telegram_charts.render_entry_chart(self.trade(),self.frame())
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertGreater(len(png),10000)

    def test_insufficient_or_future_data_fails_closed(self):
        with self.assertRaises(ValueError):
            telegram_charts.render_entry_chart(self.trade(),self.frame().tail(3))
        frame = self.frame(); frame.index += pd.Timedelta(days=1)
        with self.assertRaises(ValueError):
            telegram_charts.render_entry_chart(self.trade(),frame)

    def test_invalid_ohlc_is_not_plotted(self):
        frame = self.frame(); frame.iloc[0,frame.columns.get_loc("High")] = 90
        with self.assertRaises(ValueError):
            telegram_charts.render_entry_chart(self.trade(),frame)

    def test_photo_delivery_verifies_configured_destination(self):
        row = self.trade() | {"is_shadow":0,"legacy_position_id":None}
        connection = Mock()
        connection.execute.return_value.fetchone.return_value = row
        response = Mock(ok=True)
        response.json.return_value = {"ok":True,"result":{"chat":{"id":-5435768720}}}
        session = Mock(); session.post.return_value = response
        with patch("database.get_db_connection",return_value=connection), \
             patch.object(telegram_charts,"entry_chart_bytes",return_value=b"\x89PNGfixture"), \
             patch.dict("os.environ",{"TELEGRAM_BOT_TOKEN":"test-token","TELEGRAM_CHAT_ID":"-5435768720",
                                       "TELEGRAM_TRADING_THREAD_ID":"202","TELEGRAM_TRADES_THREAD_ID":""}), \
             patch.object(telegram_charts.requests,"Session",return_value=session):
            self.assertEqual(telegram_charts.send_entry_chart(1),"sent")
        call = session.post.call_args
        self.assertEqual(call.kwargs["data"]["chat_id"],"-5435768720")
        self.assertEqual(call.kwargs["data"]["message_thread_id"],202)
        self.assertIn("TP1",call.kwargs["data"]["caption"])
        self.assertIn("כניסה בפועל",call.kwargs["data"]["caption"])
