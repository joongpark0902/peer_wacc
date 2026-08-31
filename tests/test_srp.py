"""한공회 기업규모위험 프리미엄(SRP) 분위 자동 판정 — 연구결과(2026-06-05) 5분위표 기준.

상장 대상은 시가총액 구간(분위별 Min을 경계로), 비상장 대상은 순자산 장부금액을
분위별 중위값에 최근접(기하평균 경계, 참고목적 — 한공회 주2) 판정한다. 단위 백만원.
"""
import unittest

import srp


class SrpCapTest(unittest.TestCase):
    def test_cap_quintile_boundaries(self):
        self.assertEqual(srp.judge(cap_million=2_000_000)["quintile"], 1)
        self.assertEqual(srp.judge(cap_million=700_000)["quintile"], 2)
        self.assertEqual(srp.judge(cap_million=400_000)["quintile"], 3)
        self.assertEqual(srp.judge(cap_million=200_000)["quintile"], 4)
        self.assertEqual(srp.judge(cap_million=100_000)["quintile"], 5)
        self.assertEqual(srp.judge(cap_million=1_883_659)["quintile"], 1)   # 1분위 Min 딱 걸침
        self.assertEqual(srp.judge(cap_million=176_000)["quintile"], 5)     # 4분위 Min 바로 아래

    def test_premiums(self):
        self.assertAlmostEqual(srp.judge(cap_million=2_000_000)["premium"], -0.0051)
        self.assertAlmostEqual(srp.judge(cap_million=700_000)["premium"], -0.0006)
        self.assertAlmostEqual(srp.judge(cap_million=400_000)["premium"], 0.0097)
        self.assertAlmostEqual(srp.judge(cap_million=200_000)["premium"], 0.0267)
        self.assertAlmostEqual(srp.judge(cap_million=100_000)["premium"], 0.0486)

    def test_note_mentions_basis(self):
        j = srp.judge(cap_million=100_000)
        self.assertIn("5분위", j["note"])
        self.assertIn("시가총액", j["note"])
        self.assertIn("한공회", j["note"])


class SrpNetAssetsTest(unittest.TestCase):
    def test_nearest_median_quintiles(self):
        self.assertEqual(srp.judge(net_assets_million=4_000_000)["quintile"], 1)
        self.assertEqual(srp.judge(net_assets_million=900_000)["quintile"], 2)
        self.assertEqual(srp.judge(net_assets_million=380_000)["quintile"], 3)
        self.assertEqual(srp.judge(net_assets_million=230_000)["quintile"], 4)
        self.assertEqual(srp.judge(net_assets_million=100_000)["quintile"], 5)

    def test_note_mentions_net_assets_and_reference_caveat(self):
        j = srp.judge(net_assets_million=230_000)
        self.assertIn("순자산", j["note"])
        self.assertIn("4분위", j["note"])

    def test_cap_wins_over_net_assets(self):
        j = srp.judge(cap_million=2_000_000, net_assets_million=100_000)
        self.assertEqual(j["quintile"], 1)
        self.assertIn("시가총액", j["note"])


class SrpDefaultTest(unittest.TestCase):
    def test_default_is_smallest_quintile(self):
        j = srp.judge()
        self.assertEqual(j["quintile"], 5)
        self.assertAlmostEqual(j["premium"], 0.0486)
        self.assertIn("기본", j["note"])


if __name__ == "__main__":
    unittest.main()
