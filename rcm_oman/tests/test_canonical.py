import unittest

from rcm_oman.canonical import (
	Claim,
	Member,
	Party,
	ServiceLine,
	claim_response_from_dict,
	decision_from_dict,
	group_claim_rows,
	to_dict,
)


class TestCanonical(unittest.TestCase):
	def test_group_rows_per_patient_invoice_in_order(self):
		rows = [
			{"name": "r1", "patient": "P1", "sales_invoice": "SI-1"},
			{"name": "r2", "patient": "P1", "sales_invoice": "SI-2"},
			{"name": "r3", "patient": "P1", "sales_invoice": "SI-1"},
		]
		groups = group_claim_rows(rows)
		self.assertEqual([k for k, _ in groups], [("P1", "SI-1"), ("P1", "SI-2")])
		self.assertEqual([r["name"] for r in groups[0][1]], ["r1", "r3"])

	def test_claim_total_and_dict(self):
		c = Claim(
			claim_key="IC-1/SI-1",
			party=Party(provider_code="PRV1"),
			member=Member(patient_id="P1", id_number="12345678"),
			encounter_type="Outpatient",
			encounter_start="2026-10-01",
			encounter_end="2026-10-01",
			lines=[
				ServiceLine("l1", "2026-10-01", "Service", "99213", "Consult", 1, 20, 2, 18),
				ServiceLine("l2", "2026-10-01", "Service", "85025", "CBC", 1, 8.5, 0.85, 7.65),
			],
		)
		self.assertEqual(c.total_net, 25.65)
		d = to_dict(c)
		self.assertEqual(d["member"]["id_number"], "12345678")
		self.assertEqual(d["lines"][1]["net"], 7.65)

	def test_round_trip_decisions(self):
		d = decision_from_dict(
			{
				"status": "Partially Approved",
				"lines": [{"line_id": "x", "status": "Approved", "approved_amount": 5}],
			}
		)
		self.assertEqual(d.lines[0].approved_amount, 5)
		r = claim_response_from_dict(
			{
				"status": "Adjudicated",
				"claims": [{"claim_key": "k", "lines": [{"line_id": "x", "status": "Rejected"}]}],
			}
		)
		self.assertEqual(r.claims[0].lines[0].status, "Rejected")


if __name__ == "__main__":
	unittest.main()
