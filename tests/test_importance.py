import unittest

from app.services.importance import daily_scores, decay_score, freshness_score, score_signal


class ImportanceScoreTest(unittest.TestCase):
    def test_public_formula_and_contributions(self):
        result = score_signal("public", {"R": 80, "M": 70, "C": 90, "L": 60})
        self.assertEqual(result["score"], 75.5)
        self.assertEqual(result["contributions"], {"R": 20.0, "M": 21.0, "C": 22.5, "L": 12.0})

    def test_missing_factors_require_sixty_percent_weight(self):
        result = score_signal("public", {"R": 80, "M": 70, "C": None, "L": 60})
        self.assertEqual(result["score"], 70.7)
        with self.assertRaisesRegex(ValueError, "有效因子权重不足"):
            score_signal("upstream", {"R": None, "M": 70, "C": None, "T": 80})

    def test_freshness_decay_and_daily_baseline(self):
        self.assertEqual(freshness_score(48, 48), 50.0)
        self.assertEqual(decay_score(80, 3, "public"), 40.0)
        summary = daily_scores({"public": 80, "upstream": None, "market": 20, "cross_asset": None})
        self.assertEqual(summary["category_scores"], {
            "public": 80.0, "upstream": 5.0, "market": 20.0, "cross_asset": 5.0,
        })
        self.assertEqual(summary["composite_score"], 27.5)
        self.assertEqual(summary["dominant_category"], "public")
        self.assertEqual(summary["status"], "complete")

    def test_missing_market_creates_incomplete_preview(self):
        summary = daily_scores({"public": 40, "upstream": None, "market": None, "cross_asset": None})
        self.assertIsNone(summary["composite_score"])
        self.assertEqual(summary["preview_score"], 16.7)
        self.assertEqual(summary["status"], "incomplete")

if __name__ == "__main__":
    unittest.main()
