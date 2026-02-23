# blackroad-medical-billing

Production-grade medical billing system with claims management, insurance processing, CPT code library, ERA handling, and revenue analytics.

## Features
- Patient registration with insurance and deductible tracking
- CMS-1500 style claim creation with CPT codes and diagnosis codes
- Built-in CPT code library (15 common codes with base rates)
- Payer-specific reimbursement rates (Medicare, Medicaid, BCBS, Aetna, United, Cigna, etc.)
- ERA (Electronic Remittance Advice) processing for full/partial payments
- Claim denial and appeal workflow
- Revenue reports with collection rate analysis
- Days in Accounts Receivable calculation
- CSV export of all claims

## Usage
```bash
python medical_billing.py init
python medical_billing.py register-patient "John Doe" 1980-05-15 INS123 BCBS POL789 --copay 25
python medical_billing.py create-claim <patient_id> 1234567890 2025-06-01 \
  --dx Z00.00,M54.5 --cpt 99214,93000 --payer bcbs
python medical_billing.py process-era <claim_id> 234.00 CHK-2025-001
python medical_billing.py deny-claim <claim_id> "Medical necessity not established"
python medical_billing.py appeal-claim <claim_id> --notes "Submitting additional documentation"
python medical_billing.py revenue-report --start 2025-01-01 --end 2025-12-31
python medical_billing.py days-in-ar
python medical_billing.py cpt-codes
```

## Testing
```bash
pip install pytest
pytest test_medical_billing.py -v
```
