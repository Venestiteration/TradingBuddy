import unittest

from app.routers.importance import assemble_daily_rows


class ImportanceTimelineTest(unittest.TestCase):
    def test_non_market_signals_decay_and_baseline_keeps_line_complete(self):
        trading_dates = ["2026-09-10", "2026-09-11", "2026-09-12"]
        signals = [{
            "signal_date": "2026-09-10", "category": "public", "raw_score": 80.0,
            "score": 80.0, "summary": "公告", "title": "公告", "source_status": "fresh",
        }]
        signals.extend({
            "signal_date": date, "category": "market", "raw_score": 20.0,
            "score": 20.0, "summary": "行情", "title": "行情", "source_status": "fresh",
        } for date in trading_dates)
        rows = assemble_daily_rows(trading_dates, signals)
        self.assertEqual([row["status"] for row in rows], ["complete", "complete", "complete"])
        self.assertEqual(rows[0]["category_scores"]["upstream"], 5.0)
        self.assertLess(rows[2]["raw_category_scores"]["public"], 80.0)
        self.assertEqual(rows[2]["category_status"]["cross_asset"], "baseline")


if __name__ == "__main__":
    unittest.main()
