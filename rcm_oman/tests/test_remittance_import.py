import unittest
import sys, types

# remittance_import imports frappe at module level; stub the bits used by rows_from_table
if "frappe" not in sys.modules:
	frappe = types.ModuleType("frappe")
	frappe._ = lambda s: s
	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda v, p=None: float(v or 0)
	frappe.utils = utils
	sys.modules["frappe"] = frappe
	sys.modules["frappe.utils"] = utils

from rcm_oman.claims.remittance_import import rows_from_table


class TestRemittanceImport(unittest.TestCase):
	def test_aliases_and_blank_rows(self):
		table = [
			["Claim ID", "Line ID", "Paid", "Denied", "Reason Code", "Remarks"],
			["CLM-1", "row1", "90", "10", "PRICE-01", "Tariff"],
			["", "", "", "", "", ""],
			["CLM-2", "row2", "0", "50", "CODE-02", ""],
		]
		rows = rows_from_table(table)
		self.assertEqual(len(rows), 2)
		self.assertEqual(rows[0]["external_claim_id"], "CLM-1")
		self.assertEqual(rows[0]["paid_amount"], 90.0)
		self.assertEqual(rows[1]["denial_code"], "CODE-02")
		self.assertIsNone(rows[1]["denial_reason"])

	def test_requires_columns(self):
		with self.assertRaises(ValueError):
			rows_from_table([["foo", "bar"], ["1", "2"]])


if __name__ == "__main__":
	unittest.main()
