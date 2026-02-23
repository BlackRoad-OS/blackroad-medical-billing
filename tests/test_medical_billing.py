"""Tests for BlackRoad Medical Billing System."""
import os, tempfile, pytest
os.environ["HOME"] = tempfile.mkdtemp()

from medical_billing import (
    add_patient, get_patient, new_claim, get_claim,
    submit_claim, update_claim, generate_eob,
    denial_analysis, revenue_summary, ClaimStatus,
)

@pytest.fixture
def patient():
    return add_patient("P001", "Alice Smith", dob="1985-03-12",
                       insurance="BlueCross", member_id="BC12345")

def test_add_patient(patient):
    assert patient.patient_id == "P001"
    assert patient.name == "Alice Smith"
    assert patient.age() > 0

def test_get_patient(patient):
    p = get_patient("P001")
    assert p is not None
    assert p.insurance == "BlueCross"

def test_new_claim(patient):
    claim = new_claim("P001", ["Z00.00"], [{"code": "99213", "units": 1, "charge": 185.0}])
    assert claim.claim_id.startswith("CLM-")
    assert claim.status == ClaimStatus.DRAFT
    assert claim.total_charge == 185.0

def test_submit_claim(patient):
    claim = new_claim("P001", ["I10"], [{"code": "99214", "units": 1, "charge": 241.0}])
    submitted = submit_claim(claim.claim_id)
    assert submitted.status == ClaimStatus.SUBMITTED

def test_update_claim_approved(patient):
    claim = new_claim("P001", ["E11.9"], [{"code": "99213", "units": 1, "charge": 185.0}])
    submit_claim(claim.claim_id)
    updated = update_claim(claim.claim_id, ClaimStatus.APPROVED, paid_amt=148.0, allowed_amt=185.0, patient_resp=37.0)
    assert updated.status == ClaimStatus.APPROVED
    assert updated.paid_amt == 148.0

def test_update_claim_denied(patient):
    claim = new_claim("P001", ["Z00.00"], [{"code": "99213", "units": 1, "charge": 185.0}])
    submit_claim(claim.claim_id)
    denied = update_claim(claim.claim_id, ClaimStatus.DENIED, denial_code="CO-50")
    assert denied.denial_code == "CO-50"
    assert "Non-covered" in denied.denial_reason

def test_generate_eob(patient):
    claim = new_claim("P001", ["Z00.00"], [{"code": "99213", "units": 1, "charge": 185.0}])
    eob = generate_eob(claim.claim_id)
    assert eob["claim_id"] == claim.claim_id
    assert "totals" in eob
    assert len(eob["diagnoses"]) == 1

def test_eob_not_found():
    eob = generate_eob("NONEXISTENT")
    assert "error" in eob

def test_denial_analysis():
    r = denial_analysis(days=365)
    assert "denial_rate_pct" in r
    assert "total_claims" in r

def test_revenue_summary():
    r = revenue_summary(days=365)
    assert "total_billed" in r
    assert "collection_rate_pct" in r
    assert r["total_billed"] >= 0
