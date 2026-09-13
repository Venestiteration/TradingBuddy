import unittest
from datetime import datetime, timezone

from app.services.signals import build_evidence_signals, build_market_signals


class SignalBuilderTest(unittest.TestCase):
    def test_market_builder_emits_one_signal_per_row_after_warmup(self):
        rows = []
        for day in range(1, 23):
            rows.append({
                "date": f"2026-08-{day:02d}",
                "close": 100 + day * 0.2,
                "volume": 1_000_000 + day * 10_000,
                "MA5": 100 + day * 0.15,
                "MA20": 100 + day * 0.08,
            })
        signals = build_market_signals(rows)
        self.assertEqual(signals[-1]["signal_date"], "2026-08-22")
        self.assertEqual(signals[-1]["category"], "market")
        self.assertEqual(signals[-1]["factor_scores"]["factors"]["R"], 100.0)
        self.assertTrue(0 <= signals[-1]["score"] <= 100)

    def test_evidence_can_create_public_and_upstream_signals(self):
        evidence = [{
            "evidence_id": "ev-1",
            "stock_code": "600000",
            "source_type": "announcement",
            "source_level": "primary",
            "title": "公司与核心供应商签订原材料长期采购合同",
            "excerpt": "合同将影响未来两个季度的原材料成本。",
            "published_at": "2026-09-13 08:00:00",
            "fetched_at": "2026-09-13T09:00:00+08:00",
            "content_status": "full",
            "raw": {},
        }]
        signals = build_evidence_signals(
            evidence, "600000", "浦发银行",
            now=datetime(2026, 9, 13, 10, 0, tzinfo=timezone.utc),
        )
        self.assertEqual({item["category"] for item in signals}, {"public", "upstream"})
        self.assertEqual(signals[0]["evidence_ids"], ["ev-1"])


if __name__ == "__main__":
    unittest.main()
