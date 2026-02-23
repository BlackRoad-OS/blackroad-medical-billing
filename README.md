# BlackRoad Medical Billing

[![CI](https://github.com/BlackRoad-OS/blackroad-medical-billing/actions/workflows/ci.yml/badge.svg)](https://github.com/BlackRoad-OS/blackroad-medical-billing/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-proprietary-red.svg)](LICENSE)
[![BlackRoad OS](https://img.shields.io/badge/BlackRoad-OS-black.svg)](https://blackroad.io)

> Medical billing: ICD-10/CPT codes, claim lifecycle, EOB generation, denial analytics

Part of the **BlackRoad OS** health & science platform — production-grade implementations with SQLite persistence, pytest coverage, and CI/CD.

## Features

- **Patient** management with insurance/member ID
- **Claim** lifecycle: draft → submitted → approved/denied/partial → paid
- `new_claim(patient_id, icd_codes, cpt_entries)` — create with ICD-10 + CPT codes
- `submit_claim(claim_id)` — advance to SUBMITTED status
- `update_claim(claim_id, status, paid, ...)` — adjudication with denial codes
- `generate_eob(claim_id)` — Explanation of Benefits document
- `denial_analysis(days=90)` — denial rate by reason code
- `revenue_summary(days=30)` — collection rate, billed vs paid

## Quick Start

```bash
python src/medical_billing.py add-patient --id P001 --name "Jane Doe" --dob 1985-03-12 --insurance "BlueCross" --member-id BC123
python src/medical_billing.py new-claim --patient P001 --icd Z00.00 --cpt 99213:1:185.00 --provider DR001
python src/medical_billing.py submit CLM-XXXX
python src/medical_billing.py update CLM-XXXX --status approved --paid 148.00 --allowed 185.00 --patient-resp 37.00
python src/medical_billing.py eob CLM-XXXX
python src/medical_billing.py denial-analysis --days 90
python src/medical_billing.py revenue --days 30
python src/medical_billing.py icd Z00.00
python src/medical_billing.py cpt 99213
```

## Supported Codes

100+ ICD-10 codes · 20+ CPT E&M/procedure codes · 12 CMS denial reason codes (CO-4, CO-50, PR-1, OA-18, ...)

## Installation

```bash
# No dependencies required — pure Python stdlib + sqlite3
python src/medical_billing.py --help
```

## Testing

```bash
pip install pytest pytest-cov
pytest tests/ -v --cov=src
```

## Data Storage

All data is stored locally in `~/.blackroad/medical-billing.db` (SQLite). Zero external dependencies.

## License

Proprietary — © BlackRoad OS, Inc. All rights reserved.
