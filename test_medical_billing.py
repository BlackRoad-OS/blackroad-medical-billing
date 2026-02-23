"""Tests for BlackRoad Medical Billing System."""
import pytest
from medical_billing import (
    init_db, register_patient, get_patient, create_claim, get_claim,
    process_era, deny_claim, appeal_claim, list_claims,
    revenue_report, days_in_ar, export_claims_csv, COMMON_CPT_CODES, PAYER_RATES,
)


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "test_medical.db")
    init_db(path)
    return path


@pytest.fixture
def patient(db):
    return register_patient(
        "John Doe", "1980-05-15", "INS123456", "BCBS",
        "POL-789", "GRP-001", copay=25.0, deductible=2000.0, path=db,
    )


def test_register_patient(db):
    p = register_patient(
        "Jane Smith", "1992-03-22", "INS654321", "Aetna",
        "POL-111", path=db,
    )
    assert p.name == "Jane Smith"
    assert p.insurance_provider == "Aetna"
    assert p.deductible == 1000.0


def test_get_patient(db, patient):
    fetched = get_patient(patient.id, db)
    assert fetched.id == patient.id
    assert fetched.name == "John Doe"


def test_get_patient_not_found(db):
    with pytest.raises(KeyError):
        get_patient("nonexistent", db)


def test_create_claim_basic(db, patient):
    claim = create_claim(
        patient.id, "1234567890", "2025-06-01",
        ["Z00.00"], ["99213"], path=db,
    )
    assert claim.patient_id == patient.id
    assert claim.status == "submitted"
    assert claim.claim_number.startswith("CLM-")
    assert len(claim.claim_lines) == 1
    assert claim.total_charges > 0


def test_create_claim_multiple_cpts(db, patient):
    claim = create_claim(
        patient.id, "1234567890", "2025-06-01",
        ["M54.5", "Z00.00"], ["99214", "93000", "85025"],
        path=db,
    )
    assert len(claim.claim_lines) == 3
    assert claim.total_charges == pytest.approx(
        180.0 + 85.0 + 35.0, rel=1e-3
    )


def test_create_claim_with_units(db, patient):
    claim = create_claim(
        patient.id, "1234567890", "2025-06-01",
        ["M54.5"], ["97110"], units=[3], path=db,
    )
    assert claim.claim_lines[0].units == 3
    assert claim.claim_lines[0].charge_amount == pytest.approx(95.0 * 3)


def test_payer_rate_applied(db, patient):
    claim = create_claim(
        patient.id, "9999999999", "2025-06-01",
        ["Z00.00"], ["99213"], payer_id="medicare", path=db,
    )
    expected_allowed = round(120.0 * PAYER_RATES["medicare"], 2)
    assert claim.total_allowed == pytest.approx(expected_allowed)


def test_claim_missing_dx_raises(db, patient):
    with pytest.raises(ValueError, match="diagnosis"):
        create_claim(patient.id, "NPI", "2025-06-01", [], ["99213"], path=db)


def test_claim_missing_cpt_raises(db, patient):
    with pytest.raises(ValueError, match="CPT"):
        create_claim(patient.id, "NPI", "2025-06-01", ["Z00.00"], [], path=db)


def test_units_mismatch_raises(db, patient):
    with pytest.raises(ValueError, match="units"):
        create_claim(patient.id, "NPI", "2025-06-01", ["Z00.00"], ["99213", "93000"], units=[1], path=db)


def test_process_era_full_payment(db, patient):
    claim = create_claim(patient.id, "NPI", "2025-06-01", ["Z00.00"], ["99213"], path=db)
    updated = process_era(claim.id, claim.total_allowed, "CHK-001", path=db)
    assert updated.status == "paid"
    assert updated.paid_at is not None


def test_process_era_partial_payment(db, patient):
    claim = create_claim(patient.id, "NPI", "2025-06-01", ["Z00.00"], ["99214"], path=db)
    partial_amount = claim.total_allowed * 0.5
    updated = process_era(claim.id, partial_amount, "CHK-002", path=db)
    assert updated.status == "partial"


def test_deny_claim(db, patient):
    claim = create_claim(patient.id, "NPI", "2025-06-01", ["Z00.00"], ["99213"], path=db)
    denied = deny_claim(claim.id, "Medical necessity not established", db)
    assert denied.status == "denied"
    assert "necessity" in denied.denial_reason


def test_appeal_claim(db, patient):
    claim = create_claim(patient.id, "NPI", "2025-06-01", ["Z00.00"], ["99213"], path=db)
    deny_claim(claim.id, "Coverage expired", db)
    appealed = appeal_claim(claim.id, "Patient had active coverage", db)
    assert appealed.status == "appealed"


def test_appeal_non_denied_fails(db, patient):
    claim = create_claim(patient.id, "NPI", "2025-06-01", ["Z00.00"], ["99213"], path=db)
    with pytest.raises(ValueError, match="denied"):
        appeal_claim(claim.id, db)


def test_list_claims_by_status(db, patient):
    c1 = create_claim(patient.id, "NPI1", "2025-06-01", ["Z00.00"], ["99213"], path=db)
    c2 = create_claim(patient.id, "NPI2", "2025-06-02", ["M54.5"], ["99214"], path=db)
    deny_claim(c2.id, "Not covered", db)
    denied = list_claims(status="denied", path=db)
    assert any(c.id == c2.id for c in denied)
    submitted = list_claims(status="submitted", path=db)
    assert any(c.id == c1.id for c in submitted)


def test_list_claims_by_patient(db, patient):
    other = register_patient("Other Person", "1990-01-01", "INS999", "Cigna", "POL-999", path=db)
    create_claim(patient.id, "NPI", "2025-06-01", ["Z00.00"], ["99213"], path=db)
    create_claim(other.id, "NPI", "2025-06-01", ["Z00.00"], ["99213"], path=db)
    results = list_claims(patient_id=patient.id, path=db)
    assert all(c.patient_id == patient.id for c in results)


def test_revenue_report(db, patient):
    c1 = create_claim(patient.id, "NPI", "2025-06-01", ["Z00.00"], ["99213"], path=db)
    c2 = create_claim(patient.id, "NPI", "2025-06-02", ["M54.5"], ["99214"], path=db)
    process_era(c1.id, c1.total_allowed, "CHK-R1", path=db)
    report = revenue_report(path=db)
    assert report["total_claims"] >= 2
    assert report["total_charges"] > 0
    assert report["total_paid"] > 0
    assert "paid" in report["by_status"]


def test_days_in_ar(db, patient):
    create_claim(patient.id, "NPI", "2025-06-01", ["Z00.00"], ["99213"], path=db)
    days = days_in_ar(db)
    assert days >= 0


def test_export_claims_csv(db, patient):
    create_claim(patient.id, "NPI", "2025-06-01", ["Z00.00"], ["99213"], path=db)
    csv_str = export_claims_csv(path=db)
    assert "claim_number" in csv_str
    assert "CLM-" in csv_str


def test_claim_number_sequential(db, patient):
    c1 = create_claim(patient.id, "NPI", "2025-06-01", ["Z00.00"], ["99213"], path=db)
    c2 = create_claim(patient.id, "NPI", "2025-06-02", ["Z00.00"], ["99214"], path=db)
    assert c1.claim_number != c2.claim_number


def test_unknown_cpt_uses_default_rate(db, patient):
    claim = create_claim(patient.id, "NPI", "2025-06-01", ["Z00.00"], ["XXXXX"], path=db)
    assert claim.claim_lines[0].charge_amount == 100.0


def test_claim_line_patient_responsibility(db, patient):
    claim = create_claim(patient.id, "NPI", "2025-06-01", ["Z00.00"], ["99213"], payer_id="bcbs", path=db)
    for line in claim.claim_lines:
        assert line.patient_responsibility >= 0


def test_cpt_code_library():
    assert "99213" in COMMON_CPT_CODES
    assert COMMON_CPT_CODES["99213"].base_rate == 120.0
    assert COMMON_CPT_CODES["85025"].category == "lab"


def test_payer_rates_defined():
    for payer in ("medicare", "medicaid", "bcbs", "aetna"):
        assert payer in PAYER_RATES
        assert 0 < PAYER_RATES[payer] <= 1
