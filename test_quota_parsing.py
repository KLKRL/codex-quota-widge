import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("codex_quota_widget.py")
SPEC = importlib.util.spec_from_file_location("codex_quota_widget", MODULE_PATH)
quota = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(quota)


class QuotaParsingTests(unittest.TestCase):
    def test_parse_remaining_and_used_shapes(self) -> None:
        short = quota.parse_usage_window({"remainingPercent": 73.4, "windowSeconds": 18000})
        weekly = quota.parse_usage_window({"utilization": 0.4, "windowSeconds": 604800})

        self.assertEqual(short.remaining, 73.4)
        self.assertEqual(weekly.remaining, 60.0)

    def test_find_windows_by_duration(self) -> None:
        value = {
            "windows": [
                {"name": "weekly", "remaining": 88, "windowSeconds": 604800},
                {"name": "primary", "remaining": 51, "windowSeconds": 18000},
            ]
        }

        short = quota.parse_usage_window(quota.find_window(value, ["primary"], 18000))
        weekly = quota.parse_usage_window(quota.find_window(value, ["weekly"], 604800))

        self.assertEqual(short.remaining, 51.0)
        self.assertEqual(weekly.remaining, 88.0)

    def test_collect_reset_credit_expirations(self) -> None:
        value = {
            "available_count": 2,
            "credits": [
                {"expires_at": "2026-07-18T00:21:54Z"},
                {"expiresAt": 1780000000},
            ],
        }

        expirations = quota.collect_reset_credit_expirations(value)

        self.assertEqual(len(expirations), 2)
        self.assertIn(1780000000, expirations)


if __name__ == "__main__":
    unittest.main()
