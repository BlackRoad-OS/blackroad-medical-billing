#!/usr/bin/env python3
"""
BlackRoad Medical Billing System
Production medical billing with ICD-10/CPT codes, claim lifecycle management,
EOB generation, denial tracking, and revenue analytics.

Usage:
    python medical_billing.py add-patient --id P001 --name "Jane Doe" --dob 1985-03-12 --insurance "BlueCross" --member-id BC123
    python medical_billing.py new-claim --patient P001 --provider DR001 --icd Z00.00 --cpt 99213 --amount 250.00
    python medical_billing.py submit --claim C001
    python medical_billing.py update --claim C001 --status approved --paid 185.00
    python medical_billing.py eob --claim C001
    python medical_billing.py denial-analysis
    python medical_billing.py revenue --days 30
"""

from __future__ import annotations

import argparse
import csv
import uuid
import json
import sqlite3
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta, date
from enum import Enum
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional

DB_PATH = Path.home() / ".blackroad" / "medical_billing.db"

# ── Reference data ─────────────────────────────────────────────────────────────

ICD10_COMMON: Dict[str, str] = {
    "Z00.00": "Encounter for general adult medical examination",
    "Z00.01": "Encounter for general adult medical examination with normal findings",
    "J06.9":  "Acute upper respiratory infection, unspecified",
    "J18.9":  "Pneumonia, unspecified organism",
    "E11.9":  "Type 2 diabetes mellitus without complications",
    "I10":    "Essential (primary) hypertension",
    "M54.5":  "Low back pain",
    "R05":    "Cough",
    "R51":    "Headache",
    "K21.0":  "GERD with esophagitis",
    "F32.9":  "Major depressive disorder, single episode, unspecified",
    "F41.1":  "Generalized anxiety disorder",
    "Z23":    "Immunization encounter",
    "S52.501A": "Unspecified fracture of the lower end of right radius, initial",
    "C34.10": "Malignant neoplasm of upper lobe, bronchus or lung, unspecified",
}

CPT_CODES: Dict[str, Dict] = {
    "99201": {"desc": "Office visit, new patient, minimal",       "rvu": 0.97,  "base": 68},
    "99202": {"desc": "Office visit, new patient, straightforward","rvu": 1.60,  "base": 109},
    "99203": {"desc": "Office visit, new patient, low complexity", "rvu": 2.33,  "base": 158},
    "99204": {"desc": "Office visit, new patient, moderate",       "rvu": 3.55,  "base": 241},
    "99205": {"desc": "Office visit, new patient, high complexity","rvu": 4.50,  "base": 305},
    "99211": {"desc": "Office visit, established, minimal",        "rvu": 0.48,  "base": 33},
    "99212": {"desc": "Office visit, established, straightforward","rvu": 1.10,  "base": 75},
    "99213": {"desc": "Office visit, established, low complexity", "rvu": 1.82,  "base": 124},
    "99214": {"desc": "Office visit, established, moderate",       "rvu": 2.73,  "base": 185},
    "99215": {"desc": "Office visit, established, high complexity","rvu": 3.73,  "base": 253},
    "93000": {"desc": "Electrocardiogram, routine ECG",            "rvu": 0.61,  "base": 41},
    "36415": {"desc": "Collection of venous blood by venipuncture","rvu": 0.18,  "base": 12},
    "85025": {"desc": "Complete blood count (CBC)",                "rvu": 0.34,  "base": 23},
    "80053": {"desc": "Comprehensive metabolic panel",             "rvu": 0.47,  "base": 32},
    "71046": {"desc": "Radiologic exam, chest; 2 views",           "rvu": 0.56,  "base": 38},
    "90471": {"desc": "Immunization administration, first injection","rvu": 0.69, "base": 47},
    "90714": {"desc": "Tetanus and diphtheria toxoids injection",  "rvu": 0.18,  "base": 12},
    "20610": {"desc": "Arthrocentesis, major joint injection",     "rvu": 1.09,  "base": 74},
    "45378": {"desc": "Colonoscopy, diagnostic",                   "rvu": 5.91,  "base": 401},
    "70553": {"desc": "MRI brain without and with contrast",       "rvu": 6.95,  "base": 471},
}

DENIAL_CODES: Dict[str, str] = {
    "CO-4":  "Service inconsistent with procedure / modifier",
    "CO-11": "Diagnosis inconsistent with procedure",
    "CO-16": "Claim lacks info needed to adjudicate",
    "CO-22": "Coordination of benefits",
    "CO-27": "Expenses incurred after policy terminated",
    "CO-50": "Non-covered service",
    "CO-97": "Benefit not part of plan",
    "PR-1":  "Deductible amount",
    "PR-2":  "Coinsurance amount",
    "PR-3":  "Co-payment amount",
    "OA-18": "Duplicate claim",
    "PI-6":  "Authorization required",
}


class ClaimStatus(str, Enum):
    DRAFT     = "draft"
    SUBMITTED = "submitted"
    PENDING   = "pending"
    APPROVED  = "approved"
    DENIED    = "denied"
    PARTIAL   = "partial"
    APPEALING = "appealing"
    PAID      = "paid"
    CLOSED    = "closed"


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class Patient:
    id:           int
    patient_id:   str
    name:         str
    dob:          str
    insurance:    str
    member_id:    str
    group_id:     str
    phone:        str
    email:        str
    address:      str
    created_at:   str = field(default_factory=lambda: datetime.now().isoformat())

    def age(self) -> int:
        try:
            bd = date.fromisoformat(self.dob)
            return (date.today() - bd).days // 365
        except Exception:
            return 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["age"] = self.age()
        return d


@dataclass
class Claim:
    id:            int
    claim_id:      str
    patient_id:    str
    provider_id:   str
    icd_codes:     str     # JSON list
    cpt_codes:     str     # JSON list of {code, units, charge}
    total_charge:  float
    allowed_amt:   float
    paid_amt:      float
    patient_resp:  float
    status:        str
    denial_code:   str
    denial_reason: str
    submitted_at:  str
    adjudicated_at: str
    notes:         str
    created_at:    str

    def to_dict(self) -> dict:
        d = asdict(self)
        try:
            d["icd_list"] = json.loads(self.icd_codes)
        except Exception:
            d["icd_list"] = []
        try:
            d["cpt_list"] = json.loads(self.cpt_codes)
        except Exception:
            d["cpt_list"] = []
        return d


# ── Database ───────────────────────────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS patients (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id  TEXT NOT NULL UNIQUE,
            name        TEXT NOT NULL DEFAULT '',
            dob         TEXT NOT NULL DEFAULT '',
            insurance   TEXT NOT NULL DEFAULT '',
            member_id   TEXT NOT NULL DEFAULT '',
            group_id    TEXT NOT NULL DEFAULT '',
            phone       TEXT NOT NULL DEFAULT '',
            email       TEXT NOT NULL DEFAULT '',
            address     TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS claims (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id       TEXT NOT NULL UNIQUE,
            patient_id     TEXT NOT NULL,
            provider_id    TEXT NOT NULL DEFAULT '',
            icd_codes      TEXT NOT NULL DEFAULT '[]',
            cpt_codes      TEXT NOT NULL DEFAULT '[]',
            total_charge   REAL NOT NULL DEFAULT 0,
            allowed_amt    REAL NOT NULL DEFAULT 0,
            paid_amt       REAL NOT NULL DEFAULT 0,
            patient_resp   REAL NOT NULL DEFAULT 0,
            status         TEXT NOT NULL DEFAULT 'draft',
            denial_code    TEXT NOT NULL DEFAULT '',
            denial_reason  TEXT NOT NULL DEFAULT '',
            submitted_at   TEXT NOT NULL DEFAULT '',
            adjudicated_at TEXT NOT NULL DEFAULT '',
            notes          TEXT NOT NULL DEFAULT '',
            created_at     TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_claims_patient ON claims(patient_id);
        CREATE INDEX IF NOT EXISTS idx_claims_status  ON claims(status);

        CREATE TABLE IF NOT EXISTS claim_events (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id   TEXT NOT NULL,
            event_type TEXT NOT NULL,
            old_status TEXT NOT NULL DEFAULT '',
            new_status TEXT NOT NULL DEFAULT '',
            amount     REAL NOT NULL DEFAULT 0,
            notes      TEXT NOT NULL DEFAULT '',
            occurred_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    conn.commit()


def _log_event(conn, claim_id: str, event_type: str, old: str = "",
               new: str = "", amount: float = 0, notes: str = "") -> None:
    conn.execute(
        "INSERT INTO claim_events(claim_id,event_type,old_status,new_status,amount,notes)"
        " VALUES(?,?,?,?,?,?)",
        (claim_id, event_type, old, new, amount, notes),
    )


# ── Patient API ────────────────────────────────────────────────────────────────

def add_patient(
    patient_id: str, name: str, dob: str = "",
    insurance: str = "", member_id: str = "", group_id: str = "",
    phone: str = "", email: str = "", address: str = "",
) -> Patient:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO patients"
            "(patient_id,name,dob,insurance,member_id,group_id,phone,email,address)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (patient_id, name, dob, insurance, member_id, group_id, phone, email, address),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM patients WHERE patient_id=?", (patient_id,)).fetchone()
    return Patient(**dict(row))


def get_patient(patient_id: str) -> Optional[Patient]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM patients WHERE patient_id=?", (patient_id,)
        ).fetchone()
    return Patient(**dict(row)) if row else None


# ── Claim API ──────────────────────────────────────────────────────────────────

def _next_claim_id() -> str:
    return f"CLM-{uuid.uuid4().hex[:12].upper()}"


def new_claim(
    patient_id: str,
    icd_codes: List[str],
    cpt_entries: List[Dict],    # [{"code":"99213","units":1,"charge":185.0}, ...]
    provider_id: str = "",
    notes: str = "",
) -> Claim:
    """Create a new claim in DRAFT status."""
    claim_id = _next_claim_id()
    total    = sum(e.get("charge", CPT_CODES.get(e["code"], {}).get("base", 0))
                   for e in cpt_entries)
    now      = datetime.now().isoformat()
    icd_json = json.dumps(icd_codes)
    cpt_json = json.dumps(cpt_entries)

    with get_conn() as conn:
        conn.execute(
            "INSERT INTO claims(claim_id,patient_id,provider_id,icd_codes,cpt_codes,"
            "total_charge,status,notes,created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (claim_id, patient_id, provider_id, icd_json, cpt_json,
             round(total, 2), ClaimStatus.DRAFT, notes, now),
        )
        _log_event(conn, claim_id, "created", "", ClaimStatus.DRAFT, total)
        conn.commit()
    return get_claim(claim_id)


def get_claim(claim_id: str) -> Optional[Claim]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM claims WHERE claim_id=?", (claim_id,)
        ).fetchone()
    return Claim(**dict(row)) if row else None


def submit_claim(claim_id: str) -> Claim:
    """Advance claim from DRAFT → SUBMITTED."""
    claim = get_claim(claim_id)
    if not claim:
        raise ValueError(f"Claim {claim_id} not found")
    ts = datetime.now().isoformat()
    with get_conn() as conn:
        conn.execute(
            "UPDATE claims SET status=?,submitted_at=? WHERE claim_id=?",
            (ClaimStatus.SUBMITTED, ts, claim_id),
        )
        _log_event(conn, claim_id, "submitted", claim.status, ClaimStatus.SUBMITTED)
        conn.commit()
    return get_claim(claim_id)


def update_claim(
    claim_id: str,
    status: str,
    paid_amt: float = 0.0,
    allowed_amt: float = 0.0,
    patient_resp: float = 0.0,
    denial_code: str = "",
    notes: str = "",
) -> Claim:
    claim = get_claim(claim_id)
    if not claim:
        raise ValueError(f"Claim {claim_id} not found")
    ts = datetime.now().isoformat()
    denial_reason = DENIAL_CODES.get(denial_code, "")
    with get_conn() as conn:
        conn.execute(
            "UPDATE claims SET status=?,paid_amt=?,allowed_amt=?,patient_resp=?,"
            "denial_code=?,denial_reason=?,adjudicated_at=?,notes=? WHERE claim_id=?",
            (status, paid_amt, allowed_amt, patient_resp,
             denial_code, denial_reason, ts, notes or claim.notes, claim_id),
        )
        _log_event(conn, claim_id, "updated", claim.status, status, paid_amt, denial_code)
        conn.commit()
    return get_claim(claim_id)


def generate_eob(claim_id: str) -> dict:
    """Explanation of Benefits document for a claim."""
    claim = get_claim(claim_id)
    if not claim:
        return {"error": f"Claim {claim_id} not found"}
    patient = get_patient(claim.patient_id)

    try:
        cpt_list = json.loads(claim.cpt_codes)
        icd_list = json.loads(claim.icd_codes)
    except Exception:
        cpt_list, icd_list = [], []

    line_items = []
    for entry in cpt_list:
        code = entry.get("code", "")
        info = CPT_CODES.get(code, {})
        line_items.append({
            "cpt_code":    code,
            "description": info.get("desc", "Unknown"),
            "units":       entry.get("units", 1),
            "billed":      entry.get("charge", info.get("base", 0)),
            "allowed":     round(entry.get("charge", info.get("base", 0)) * 0.75, 2),
        })

    return {
        "eob_date":      date.today().isoformat(),
        "claim_id":      claim_id,
        "patient": {
            "id":        claim.patient_id,
            "name":      patient.name if patient else "Unknown",
            "insurance": patient.insurance if patient else "",
            "member_id": patient.member_id if patient else "",
        },
        "provider_id":   claim.provider_id,
        "diagnoses":     [{"code": c, "desc": ICD10_COMMON.get(c, "See codebook")} for c in icd_list],
        "services":      line_items,
        "totals": {
            "total_charge": claim.total_charge,
            "allowed_amt":  claim.allowed_amt or round(claim.total_charge * 0.75, 2),
            "paid_by_ins":  claim.paid_amt,
            "patient_resp": claim.patient_resp,
            "balance":      round(claim.total_charge - claim.paid_amt - claim.patient_resp, 2),
        },
        "status":        claim.status,
        "denial_code":   claim.denial_code or None,
        "denial_reason": claim.denial_reason or None,
        "submitted_at":  claim.submitted_at,
        "adjudicated_at":claim.adjudicated_at,
    }


def denial_analysis(days: int = 90) -> dict:
    """Aggregate denial statistics for the past N days."""
    since = (datetime.now() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT denial_code, denial_reason, COUNT(*) as n, SUM(total_charge) as total"
            " FROM claims WHERE status='denied' AND created_at>=?"
            " GROUP BY denial_code ORDER BY n DESC",
            (since,),
        ).fetchall()
        total_claims = conn.execute(
            "SELECT COUNT(*) FROM claims WHERE created_at>=?", (since,)
        ).fetchone()[0]
        denied_count = conn.execute(
            "SELECT COUNT(*) FROM claims WHERE status='denied' AND created_at>=?", (since,)
        ).fetchone()[0]

    top_denials = [
        {"code": r["denial_code"], "reason": r["denial_reason"],
         "count": r["n"], "total_charge": round(r["total"] or 0, 2)}
        for r in rows
    ]
    return {
        "period_days":    days,
        "total_claims":   total_claims,
        "denied_count":   denied_count,
        "denial_rate_pct": round(denied_count / total_claims * 100, 1) if total_claims else 0,
        "top_denials":    top_denials,
    }


def revenue_summary(days: int = 30) -> dict:
    """Revenue analytics for the past N days."""
    since = (datetime.now() - timedelta(days=days)).isoformat()
    with get_conn() as conn:
        row = conn.execute("""
            SELECT
              COUNT(*) AS n_claims,
              SUM(total_charge)  AS billed,
              SUM(allowed_amt)   AS allowed,
              SUM(paid_amt)      AS collected,
              SUM(patient_resp)  AS patient_due,
              SUM(CASE WHEN status='denied' THEN total_charge ELSE 0 END) AS denied_charges,
              SUM(CASE WHEN status='paid'   THEN 1 ELSE 0 END)            AS paid_count,
              SUM(CASE WHEN status='denied' THEN 1 ELSE 0 END)            AS denied_count
            FROM claims WHERE created_at >= ?
        """, (since,)).fetchone()

    billed    = row["billed"]    or 0
    collected = row["collected"] or 0
    return {
        "period_days":         days,
        "n_claims":            row["n_claims"],
        "total_billed":        round(billed, 2),
        "total_allowed":       round(row["allowed"] or 0, 2),
        "total_collected":     round(collected, 2),
        "patient_due":         round(row["patient_due"] or 0, 2),
        "denied_charges":      round(row["denied_charges"] or 0, 2),
        "paid_count":          row["paid_count"],
        "denied_count":        row["denied_count"],
        "collection_rate_pct": round(collected / billed * 100, 1) if billed else 0,
    }


# ── CLI ────────────────────────────────────────────────────────────────────────

def _print(obj):
    print(json.dumps(obj, indent=2, default=str))


def main():
    parser = argparse.ArgumentParser(description="BlackRoad Medical Billing System")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add-patient")
    p.add_argument("--id",        required=True, dest="patient_id")
    p.add_argument("--name",      required=True)
    p.add_argument("--dob",       default="")
    p.add_argument("--insurance", default="")
    p.add_argument("--member-id", default="", dest="member_id")
    p.add_argument("--group-id",  default="", dest="group_id")
    p.add_argument("--phone",     default="")
    p.add_argument("--email",     default="")
    p.add_argument("--address",   default="")

    p = sub.add_parser("new-claim")
    p.add_argument("--patient",  required=True, dest="patient_id")
    p.add_argument("--provider", default="", dest="provider_id")
    p.add_argument("--icd",      nargs="+", required=True, dest="icd_codes")
    p.add_argument("--cpt",      nargs="+", required=True, dest="cpt_codes",
                   help="code[:units[:charge]], e.g. 99213 or 99213:1:185.00")
    p.add_argument("--notes",    default="")

    p = sub.add_parser("submit")
    p.add_argument("claim_id")

    p = sub.add_parser("update")
    p.add_argument("claim_id")
    p.add_argument("--status",   required=True)
    p.add_argument("--paid",     type=float, default=0, dest="paid_amt")
    p.add_argument("--allowed",  type=float, default=0, dest="allowed_amt")
    p.add_argument("--patient-resp", type=float, default=0, dest="patient_resp")
    p.add_argument("--denial",   default="", dest="denial_code")
    p.add_argument("--notes",    default="")

    p = sub.add_parser("eob",    help="Generate Explanation of Benefits")
    p.add_argument("claim_id")

    p = sub.add_parser("get",    help="Get claim details")
    p.add_argument("claim_id")

    p = sub.add_parser("icd",    help="Look up ICD-10 code")
    p.add_argument("code")

    p = sub.add_parser("cpt",    help="Look up CPT code")
    p.add_argument("code")

    p = sub.add_parser("denial-analysis")
    p.add_argument("--days", type=int, default=90)

    p = sub.add_parser("revenue")
    p.add_argument("--days", type=int, default=30)

    args = parser.parse_args()

    if args.cmd == "add-patient":
        pt = add_patient(args.patient_id, args.name, args.dob, args.insurance,
                         args.member_id, args.group_id, args.phone, args.email, args.address)
        _print({"status": "added", "patient": pt.to_dict()})

    elif args.cmd == "new-claim":
        cpt_entries = []
        for token in args.cpt_codes:
            parts = token.split(":")
            code  = parts[0]
            units = int(parts[1])   if len(parts) > 1 else 1
            base  = CPT_CODES.get(code, {}).get("base", 0)
            charge= float(parts[2]) if len(parts) > 2 else base * units
            cpt_entries.append({"code": code, "units": units, "charge": charge})
        claim = new_claim(args.patient_id, args.icd_codes, cpt_entries,
                          args.provider_id, args.notes)
        _print({"status": "created", "claim": claim.to_dict()})

    elif args.cmd == "submit":
        claim = submit_claim(args.claim_id)
        _print({"status": "submitted", "claim": claim.to_dict()})

    elif args.cmd == "update":
        claim = update_claim(args.claim_id, args.status, args.paid_amt,
                             args.allowed_amt, args.patient_resp,
                             args.denial_code, args.notes)
        _print({"status": "updated", "claim": claim.to_dict()})

    elif args.cmd == "eob":
        _print(generate_eob(args.claim_id))

    elif args.cmd == "get":
        c = get_claim(args.claim_id)
        _print(c.to_dict() if c else {"error": "not found"})

    elif args.cmd == "icd":
        _print({"code": args.code, "description": ICD10_COMMON.get(args.code, "Not in local codebook")})

    elif args.cmd == "cpt":
        _print({"code": args.code, **CPT_CODES.get(args.code, {"error": "not found"})})

    elif args.cmd == "denial-analysis":
        _print(denial_analysis(args.days))

    elif args.cmd == "revenue":
        _print(revenue_summary(args.days))


if __name__ == "__main__":
    main()
