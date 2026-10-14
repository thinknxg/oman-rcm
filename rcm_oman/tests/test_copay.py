"""Pure unit tests for the copay engine (no site needed): python -m unittest rcm_oman.tests.test_copay"""

import unittest

from rcm_oman.rules.copay import compute_split, copay_on, money, select_rule


class TestMoney(unittest.TestCase):
	def test_three_decimals_half_up(self):
		self.assertEqual(money(1.2345), 1.235)
		self.assertEqual(money(1.2344), 1.234)
		self.assertEqual(money(-1.2345), -1.235)


class TestCopay(unittest.TestCase):
	def test_no_rule_payer_takes_covered(self):
		s = compute_split(100, 80)
		self.assertEqual((s.covered, s.payer_share, s.patient_payable), (80, 80, 20))
		self.assertEqual(s.effective_coverage_percent, 80)

	def test_percent_copay_on_covered_part(self):
		s = compute_split(100, 80, {"copay_type": "Percent", "copay_percent": 10})
		self.assertEqual(s.copay, 8)
		self.assertEqual(s.payer_share, 72)
		self.assertEqual(s.patient_payable, 28)

	def test_fixed_copay_capped_at_covered(self):
		self.assertEqual(copay_on(3, {"copay_type": "Fixed", "copay_fixed": 5}), (0, 3))
		s = compute_split(50, 100, {"copay_type": "Fixed", "copay_fixed": 5})
		self.assertEqual((s.payer_share, s.patient_payable), (45, 5))

	def test_percent_with_cap(self):
		rule = {"copay_type": "Percent with Cap", "copay_percent": 20, "max_patient_share": 15}
		self.assertEqual(compute_split(50, 100, rule).copay, 10)  # 20 % of 50 under cap
		self.assertEqual(compute_split(200, 100, rule).copay, 15)  # capped

	def test_deductible_then_percent(self):
		rule = {"copay_type": "Percent", "copay_percent": 10, "deductible_per_line": 20}
		s = compute_split(120, 100, rule)
		self.assertEqual((s.deductible, s.copay, s.payer_share), (20, 10, 90))

	def test_cap_includes_deductible(self):
		rule = {
			"copay_type": "Percent with Cap",
			"copay_percent": 50,
			"max_patient_share": 25,
			"deductible_per_line": 10,
		}
		s = compute_split(100, 100, rule)
		self.assertEqual(s.deductible + s.copay, 25)

	def test_minimum_patient_share(self):
		rule = {"copay_type": "Percent", "copay_percent": 1, "min_patient_share": 2}
		self.assertEqual(compute_split(100, 100, rule).copay, 2)
		self.assertEqual(compute_split(1, 100, rule).copay, 1)  # never above covered

	def test_authorization_cap(self):
		s = compute_split(1000, 100, {"copay_type": "Percent", "copay_percent": 10}, authorized_cap=700)
		self.assertTrue(s.capped_by_authorization)
		self.assertEqual((s.payer_share, s.patient_payable), (700, 300))

	def test_zero_amount(self):
		s = compute_split(0, 80, {"copay_type": "Fixed", "copay_fixed": 5})
		self.assertEqual((s.payer_share, s.patient_payable, s.effective_coverage_percent), (0, 0, 0))

	def test_omr_rounding(self):
		s = compute_split(33.333, 70, {"copay_type": "Percent", "copay_percent": 15})
		self.assertAlmostEqual(s.payer_share + s.patient_payable, 33.333, places=6)


class TestRuleSelection(unittest.TestCase):
	RULES = [
		{"name": "all", "applies_to": "All Services", "copay_type": "Percent", "copay_percent": 20},
		{
			"name": "lab",
			"applies_to": "Item Group",
			"item_group": "Laboratory",
			"copay_type": "Percent",
			"copay_percent": 10,
		},
		{
			"name": "services",
			"applies_to": "Item Group",
			"item_group": "Services",
			"copay_type": "Percent",
			"copay_percent": 15,
		},
		{
			"name": "mri",
			"applies_to": "Item",
			"item_code": "MRI-BRAIN",
			"copay_type": "Fixed",
			"copay_fixed": 25,
		},
		{"name": "ip", "applies_to": "All Services", "encounter_type": "Inpatient", "copay_type": "None"},
		{
			"name": "old",
			"applies_to": "Item",
			"item_code": "CBC",
			"valid_till": "2025-12-31",
			"copay_type": "Fixed",
			"copay_fixed": 1,
		},
	]

	def pick(self, **kw):
		r = select_rule(self.RULES, **kw)
		return r and r["name"]

	def test_item_beats_group(self):
		self.assertEqual(self.pick(item_code="MRI-BRAIN", item_groups=["Radiology", "Services"]), "mri")

	def test_nearest_group_wins(self):
		self.assertEqual(
			self.pick(item_code="CBC", item_groups=["Laboratory", "Services"], on_date="2026-10-14"), "lab"
		)

	def test_expired_rule_ignored(self):
		self.assertEqual(self.pick(item_code="CBC", item_groups=["Laboratory"], on_date="2026-10-14"), "lab")
		self.assertEqual(self.pick(item_code="CBC", item_groups=["Laboratory"], on_date="2025-06-01"), "old")

	def test_encounter_specific_beats_generic_at_same_level(self):
		self.assertEqual(self.pick(item_code="X", encounter_type="Inpatient"), "ip")
		self.assertEqual(self.pick(item_code="X", encounter_type="Outpatient"), "all")

	def test_inactive_ignored(self):
		rules = [{"name": "a", "applies_to": "All Services", "is_active": 0}]
		self.assertIsNone(select_rule(rules, item_code="X"))


if __name__ == "__main__":
	unittest.main()
