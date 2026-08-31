import unittest

import tax


class MarginalRateTest(unittest.TestCase):
    def test_brackets_2026(self):
        self.assertEqual(tax.marginal_rate(1e8), (0.110, "2억 이하"))
        self.assertEqual(tax.marginal_rate(2e8), (0.110, "2억 이하"))
        self.assertEqual(tax.marginal_rate(2e8 + 1), (0.220, "2억~200억"))
        self.assertEqual(tax.marginal_rate(150e8), (0.220, "2억~200억"))
        self.assertEqual(tax.marginal_rate(2500e8), (0.242, "200억~3,000억"))
        self.assertEqual(tax.marginal_rate(5e12), (0.275, "3,000억 초과"))

    def test_old_brackets_before_2026(self):
        self.assertEqual(tax.marginal_rate(5e12, year=2025), (0.264, "3,000억 초과"))

    def test_loss_or_none(self):
        self.assertEqual(tax.marginal_rate(-5), (None, "결손/미확인"))
        self.assertEqual(tax.marginal_rate(None), (None, "결손/미확인"))
