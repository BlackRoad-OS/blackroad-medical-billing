<!-- BlackRoad SEO Enhanced -->

# ulackroad medical uilling

> Part of **[BlackRoad OS](https://blackroad.io)** — Sovereign Computing for Everyone

[![BlackRoad OS](https://img.shields.io/badge/BlackRoad-OS-ff1d6c?style=for-the-badge)](https://blackroad.io)
[![BlackRoad OS](https://img.shields.io/badge/Org-BlackRoad-OS-2979ff?style=for-the-badge)](https://github.com/BlackRoad-OS)
[![License](https://img.shields.io/badge/License-Proprietary-f5a623?style=for-the-badge)](LICENSE)

**ulackroad medical uilling** is part of the **BlackRoad OS** ecosystem — a sovereign, distributed operating system built on edge computing, local AI, and mesh networking by **BlackRoad OS, Inc.**

## About BlackRoad OS

BlackRoad OS is a sovereign computing platform that runs AI locally on your own hardware. No cloud dependencies. No API keys. No surveillance. Built by [BlackRoad OS, Inc.](https://github.com/BlackRoad-OS-Inc), a Delaware C-Corp founded in 2025.

### Key Features
- **Local AI** — Run LLMs on Raspberry Pi, Hailo-8, and commodity hardware
- **Mesh Networking** — WireGuard VPN, NATS pub/sub, peer-to-peer communication
- **Edge Computing** — 52 TOPS of AI acceleration across a Pi fleet
- **Self-Hosted Everything** — Git, DNS, storage, CI/CD, chat — all sovereign
- **Zero Cloud Dependencies** — Your data stays on your hardware

### The BlackRoad Ecosystem
| Organization | Focus |
|---|---|
| [BlackRoad OS](https://github.com/BlackRoad-OS) | Core platform and applications |
| [BlackRoad OS, Inc.](https://github.com/BlackRoad-OS-Inc) | Corporate and enterprise |
| [BlackRoad AI](https://github.com/BlackRoad-AI) | Artificial intelligence and ML |
| [BlackRoad Hardware](https://github.com/BlackRoad-Hardware) | Edge hardware and IoT |
| [BlackRoad Security](https://github.com/BlackRoad-Security) | Cybersecurity and auditing |
| [BlackRoad Quantum](https://github.com/BlackRoad-Quantum) | Quantum computing research |
| [BlackRoad Agents](https://github.com/BlackRoad-Agents) | Autonomous AI agents |
| [BlackRoad Network](https://github.com/BlackRoad-Network) | Mesh and distributed networking |
| [BlackRoad Education](https://github.com/BlackRoad-Education) | Learning and tutoring platforms |
| [BlackRoad Labs](https://github.com/BlackRoad-Labs) | Research and experiments |
| [BlackRoad Cloud](https://github.com/BlackRoad-Cloud) | Self-hosted cloud infrastructure |
| [BlackRoad Forge](https://github.com/BlackRoad-Forge) | Developer tools and utilities |

### Links
- **Website**: [blackroad.io](https://blackroad.io)
- **Documentation**: [docs.blackroad.io](https://docs.blackroad.io)
- **Chat**: [chat.blackroad.io](https://chat.blackroad.io)
- **Search**: [search.blackroad.io](https://search.blackroad.io)

---


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
