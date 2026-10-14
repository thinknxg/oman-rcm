"""Canonical insurance message model (version 1).

These structures are the contract between rcm_oman (which builds them from Marley / ERPNext
documents) and any transport (dhamani_gateway, or a future TPA connector). Nothing here is
Dhamani-specific: the gateway's mapper translates them to and from the wire format.

Pure Python — no Frappe import — so mappers and tests can use it standalone.
"""

from dataclasses import asdict, dataclass, field

CANONICAL_VERSION = "1"


@dataclass
class Party:
	provider_code: str | None = None  # facility (Dhamani provider code)
	facility_licence: str | None = None  # MOH facility licence number
	payer_code: str | None = None  # Dhamani payer / TPA code
	payer_name: str | None = None


@dataclass
class Member:
	patient_id: str  # HIS patient (MRN)
	id_type: str | None = None
	id_number: str | None = None  # Civil ID / resident card / passport
	member_id: str | None = None  # payer member id
	policy_number: str | None = None
	name: str | None = None
	dob: str | None = None
	gender: str | None = None


@dataclass
class EligibilityRequest:
	reference: str  # Eligibility Check name
	party: Party
	member: Member
	service_date: str
	encounter_type: str = "Outpatient"
	version: str = CANONICAL_VERSION


@dataclass
class EligibilityResponse:
	eligible: bool
	member_id: str | None = None
	plan_reference: str | None = None
	payer_reference: str | None = None
	copay_percent: float | None = None
	deductible: float | None = None
	annual_limit: float | None = None
	remaining_limit: float | None = None
	message: str | None = None


@dataclass
class ServiceLine:
	line_id: str  # HIS row id; echoed back by the payer
	service_date: str
	code_type: str  # Service / Procedure / Drug
	code: str
	description: str | None
	qty: float
	gross: float
	patient_share: float
	net: float  # amount claimed from / requested of the payer
	authorization: str | None = None  # approval number
	practitioner_licence: str | None = None


@dataclass
class AuthRequest:
	reference: str  # Prior Authorization Request name
	party: Party
	member: Member
	encounter_type: str
	is_retroactive: bool
	diagnosis_codes: list = field(default_factory=list)
	clinical_notes: str | None = None
	practitioner_licence: str | None = None
	lines: list = field(default_factory=list)  # list[ServiceLine]
	version: str = CANONICAL_VERSION


@dataclass
class LineDecision:
	line_id: str
	status: str  # Approved / Partially Approved / Rejected
	approved_qty: float | None = None
	approved_amount: float | None = None
	denial_code: str | None = None
	denial_reason: str | None = None


@dataclass
class AuthDecision:
	status: str  # Approved / Partially Approved / Rejected / Information Requested / Pending
	payer_reference: str | None = None
	approval_number: str | None = None
	valid_till: str | None = None
	message: str | None = None
	lines: list = field(default_factory=list)  # list[LineDecision]


@dataclass
class Claim:
	claim_key: str  # stable HIS key: <Insurance Claim>/<sales invoice>
	party: Party
	member: Member
	encounter_type: str
	encounter_start: str
	encounter_end: str
	diagnosis_codes: list = field(default_factory=list)
	practitioner_licence: str | None = None
	resubmission_of: str | None = None  # external claim id of the original
	resubmission_type: str | None = None
	lines: list = field(default_factory=list)  # list[ServiceLine]
	attachments: list = field(default_factory=list)  # [{"name","url","mime"}]

	@property
	def total_net(self):
		return round(sum(line.net for line in self.lines), 3)


@dataclass
class ClaimSubmission:
	reference: str  # Insurance Claim name
	party: Party
	claims: list = field(default_factory=list)  # list[Claim]
	version: str = CANONICAL_VERSION


@dataclass
class ClaimResult:
	claim_key: str
	external_claim_id: str | None = None
	status: str | None = None  # Accepted / Rejected / Adjudicated / Information Requested
	message: str | None = None
	lines: list = field(default_factory=list)  # list[LineDecision]


@dataclass
class ClaimResponse:
	status: str  # Accepted / Rejected / Adjudicated / Information Requested
	batch_reference: str | None = None
	message: str | None = None
	claims: list = field(default_factory=list)  # list[ClaimResult]


@dataclass
class RemittanceLine:
	external_claim_id: str | None
	line_id: str | None
	claimed_amount: float
	paid_amount: float
	denied_amount: float
	denial_code: str | None = None
	denial_reason: str | None = None


@dataclass
class Remittance:
	payment_reference: str
	payment_date: str
	payer_code: str | None
	provider_code: str | None
	lines: list = field(default_factory=list)  # list[RemittanceLine]


def to_dict(obj):
	data = asdict(obj)
	return data


def group_claim_rows(rows):
	"""Group claim coverage rows into one payer claim per patient visit invoice.

	rows: iterable of dicts with at least `patient` and `sales_invoice`.
	Returns an ordered dict-like list of (key, rows) preserving first-seen order."""
	groups = {}
	order = []
	for row in rows:
		key = (row.get("patient"), row.get("sales_invoice") or row.get("insurance_coverage"))
		if key not in groups:
			groups[key] = []
			order.append(key)
		groups[key].append(row)
	return [(key, groups[key]) for key in order]


def decision_from_dict(data):
	lines = [LineDecision(**line) for line in data.get("lines", [])]
	return AuthDecision(**{**{k: v for k, v in data.items() if k != "lines"}, "lines": lines})


def claim_response_from_dict(data):
	claims = []
	for c in data.get("claims", []):
		lines = [LineDecision(**line) for line in c.get("lines", [])]
		claims.append(ClaimResult(**{**{k: v for k, v in c.items() if k != "lines"}, "lines": lines}))
	return ClaimResponse(**{**{k: v for k, v in data.items() if k != "claims"}, "claims": claims})


def remittance_from_dict(data):
	lines = [RemittanceLine(**line) for line in data.get("lines", [])]
	return Remittance(**{**{k: v for k, v in data.items() if k != "lines"}, "lines": lines})
