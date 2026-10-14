"""Copay engine — pure functions, no Frappe imports, unit-tested in tests/test_copay.py.

Model
-----
Marley's Item Insurance Eligibility gives the covered percentage of a service (the rest is
non-covered and always patient's). A Copay Rule then takes a patient share *out of the covered
part*: deductible first, then a percent, a fixed amount, or a percent capped at a maximum.
An approved prior authorisation can cap the payer share further.

    amount            = price x qty - discount                (Marley)
    covered           = amount x eligibility_coverage %       (Marley)
    copay             = rule applied to `covered`             (this module)
    payer_share       = min(covered - copay, authorized_cap)
    patient_payable   = amount - payer_share
"""

from dataclasses import dataclass

OMR_PRECISION = 3  # Omani rial has 3 decimal places (baisa)

SPECIFICITY = {"Item": 3, "Template": 2, "Item Group": 1, "All Services": 0}


def money(value, precision=OMR_PRECISION):
	"""Round half up (banker's rounding would surprise cashiers)."""
	value = float(value or 0)
	factor = 10**precision
	sign = -1 if value < 0 else 1
	return sign * int(abs(value) * factor + 0.5) / factor


@dataclass
class Split:
	amount: float
	covered: float
	deductible: float
	copay: float
	payer_share: float
	patient_payable: float
	capped_by_authorization: bool = False

	@property
	def effective_coverage_percent(self):
		if not self.amount:
			return 0.0
		return round(self.payer_share / self.amount * 100, 6)


def copay_on(covered, rule):
	"""Patient share taken out of the covered amount: returns (deductible, copay)."""
	covered = max(float(covered or 0), 0.0)
	if not rule or covered == 0:
		return 0.0, 0.0

	deductible = min(float(rule.get("deductible_per_line") or 0), covered)
	remaining = covered - deductible

	copay_type = rule.get("copay_type") or "None"
	pct = float(rule.get("copay_percent") or 0)
	if copay_type == "Percent":
		copay = remaining * pct / 100
	elif copay_type == "Fixed":
		copay = min(float(rule.get("copay_fixed") or 0), remaining)
	elif copay_type == "Percent with Cap":
		copay = remaining * pct / 100
		cap = float(rule.get("max_patient_share") or 0)
		if cap > 0:
			copay = min(copay, max(cap - deductible, 0))
	else:
		copay = 0.0

	minimum = float(rule.get("min_patient_share") or 0)
	if minimum and deductible + copay < minimum:
		copay = min(minimum, covered) - deductible

	copay = min(max(copay, 0.0), remaining)
	return money(deductible), money(copay)


def compute_split(amount, coverage_percent, rule=None, authorized_cap=None):
	amount = money(amount)
	covered = money(amount * float(coverage_percent or 0) / 100)
	deductible, copay = copay_on(covered, rule)
	payer = money(covered - deductible - copay)
	capped = False
	if authorized_cap is not None and authorized_cap >= 0 and payer > authorized_cap:
		payer = money(authorized_cap)
		capped = True
	return Split(
		amount=amount,
		covered=covered,
		deductible=deductible,
		copay=copay,
		payer_share=payer,
		patient_payable=money(amount - payer),
		capped_by_authorization=capped,
	)


def _in_window(rule, on_date):
	if on_date is None:
		return True
	vf, vt = rule.get("valid_from"), rule.get("valid_till")
	if vf and str(vf) > str(on_date):
		return False
	if vt and str(vt) < str(on_date):
		return False
	return True


def rule_matches(rule, item_code=None, item_groups=(), template_dt=None, encounter_type=None, on_date=None):
	if not rule.get("is_active", 1):
		return False
	if not _in_window(rule, on_date):
		return False
	rule_et = rule.get("encounter_type") or "All"
	if rule_et != "All" and encounter_type and rule_et != encounter_type:
		return False
	applies = rule.get("applies_to") or "All Services"
	if applies == "Item":
		return bool(item_code) and rule.get("item_code") == item_code
	if applies == "Template":
		return bool(template_dt) and rule.get("template_dt") == template_dt
	if applies == "Item Group":
		return rule.get("item_group") in (item_groups or ())
	return True


def select_rule(rules, item_code=None, item_groups=(), template_dt=None, encounter_type=None, on_date=None):
	"""Most specific matching rule wins; ties go to the higher priority, then encounter-specific rules.

	`item_groups` should hold the item's group and its ancestors, nearest first; a rule on a nearer
	group beats a rule on a farther one."""
	candidates = []
	for rule in rules:
		if not rule_matches(rule, item_code, item_groups, template_dt, encounter_type, on_date):
			continue
		spec = SPECIFICITY.get(rule.get("applies_to") or "All Services", 0)
		group_rank = 0
		if rule.get("applies_to") == "Item Group" and item_groups:
			group_rank = len(item_groups) - list(item_groups).index(rule.get("item_group"))
		et_rank = 0 if (rule.get("encounter_type") or "All") == "All" else 1
		candidates.append(((spec, group_rank, int(rule.get("priority") or 0), et_rank), rule))
	if not candidates:
		return None
	candidates.sort(key=lambda c: c[0], reverse=True)
	return candidates[0][1]
