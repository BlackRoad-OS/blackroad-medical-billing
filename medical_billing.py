#!/usr/bin/env python3
"""
BlackRoad Medical Billing System
Production-grade medical billing with claims, insurance, CPT codes, ERA processing, and revenue analytics.
"""
from __future__ import annotations
import argparse
import csv
import io
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import List, Optional, Dict

DB_PATH = os.path.expanduser("~/.blackroad/medical_billing.db")


@dataclass
class Patient:
    id: str
    name: str
    dob: str
    insurance_id: str
    insurance_provider: str
    policy_number: str
    group_number: str
    copay: float
    deductible: float
    deductible_met: float
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CptCode:
    code: str
    description: str
    base_rate: float
    category: str   # E&M | procedure | lab | radiology | therapy

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ClaimLine:
    cpt_code: str
    description: str
    units: int
    charge_amount: float
    allowed_amount: float
    paid_amount: float
    adjustment: float
    denial_reason: str = ""

    @property
    def patient_responsibility(self) -> float:
        return round(max(0, self.allowed_amount - self.paid_amount), 2)

    def to_dict(self) -> dict:
        return {**asdict(self), "patient_responsibility": self.patient_responsibility}


@dataclass
class Claim:
    id: str
    claim_number: str
    patient_id: str
    provider_npi: str
    facility: str
    date_of_service: str
    date_submitted: str
    diagnosis_codes: List[str]
    claim_lines: List[ClaimLine]
    status: str       # draft | submitted | processing | paid | denied | partial | appealed
    total_charges: float
    total_allowed: float
    total_paid: float
    total_patient_responsibility: float
    payer_id: str
    payer_name: str
    created_at: str
    paid_at: Optional[str] = None
    denial_reason: Optional[str] = None
    notes: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["claim_lines"] = [cl.to_dict() for cl in self.claim_lines]
        return d


# Common CPT codes library
COMMON_CPT_CODES: Dict[str, CptCode] = {
    "99213": CptCode("99213", "Office Visit - Established Patient (Level 3)", 120.0, "E&M"),
    "99214": CptCode("99214", "Office Visit - Established Patient (Level 4)", 180.0, "E&M"),
    "99215": CptCode("99215", "Office Visit - Established Patient (Level 5)", 250.0, "E&M"),
    "99203": CptCode("99203", "Office Visit - New Patient (Level 3)", 175.0, "E&M"),
    "99204": CptCode("99204", "Office Visit - New Patient (Level 4)", 250.0, "E&M"),
    "93000": CptCode("93000", "Electrocardiogram (ECG)", 85.0, "procedure"),
    "85025": CptCode("85025", "Complete Blood Count (CBC)", 35.0, "lab"),
    "80053": CptCode("80053", "Comprehensive Metabolic Panel", 55.0, "lab"),
    "71046": CptCode("71046", "Chest X-Ray (2 views)", 145.0, "radiology"),
    "97110": CptCode("97110", "Therapeutic Exercise", 95.0, "therapy"),
    "97530": CptCode("97530", "Therapeutic Activities", 95.0, "therapy"),
    "11100": CptCode("11100", "Skin Biopsy", 200.0, "procedure"),
    "36415": CptCode("36415", "Routine Venipuncture", 25.0, "lab"),
    "90837": CptCode("90837", "Psychotherapy, 60 min", 190.0, "therapy"),
    "99232": CptCode("99232", "Subsequent Hospital Care", 145.0, "E&M"),
}

# Payer-specific reimbursement rates (as fraction of charge)
PAYER_RATES: Dict[str, float] = {
    "medicare": 0.72,
    "medicaid": 0.58,
    "bcbs": 0.85,
    "aetna": 0.82,
    "united": 0.80,
    "cigna": 0.81,
    "humana": 0.79,
    "self_pay": 0.40,
}


def _now() -> str:
    return datetime.utcnow().isoformat()


def _claim_number(conn: sqlite3.Connection) -> str:
    year = datetime.utcnow().year
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM claims WHERE claim_number LIKE ?",
        (f"CLM-{year}-%",),
    ).fetchone()
    seq = (row["cnt"] if row else 0) + 1
    return f"CLM-{year}-{seq:06d}"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def get_db(path: str = DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(path: str = DB_PATH) -> None:
    with get_db(path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS patients (
                id                 TEXT PRIMARY KEY,
                name               TEXT NOT NULL,
                dob                TEXT NOT NULL,
                insurance_id       TEXT NOT NULL,
                insurance_provider TEXT NOT NULL,
                policy_number      TEXT NOT NULL,
                group_number       TEXT NOT NULL DEFAULT '',
                copay              REAL NOT NULL DEFAULT 0,
                deductible         REAL NOT NULL DEFAULT 0,
                deductible_met     REAL NOT NULL DEFAULT 0,
                created_at         TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS claims (
                id                        TEXT PRIMARY KEY,
                claim_number              TEXT UNIQUE NOT NULL,
                patient_id                TEXT NOT NULL REFERENCES patients(id),
                provider_npi              TEXT NOT NULL,
                facility                  TEXT NOT NULL DEFAULT '',
                date_of_service           TEXT NOT NULL,
                date_submitted            TEXT NOT NULL,
                diagnosis_codes           TEXT NOT NULL DEFAULT '[]',
                status                    TEXT NOT NULL DEFAULT 'draft',
                total_charges             REAL NOT NULL DEFAULT 0,
                total_allowed             REAL NOT NULL DEFAULT 0,
                total_paid                REAL NOT NULL DEFAULT 0,
                total_patient_responsibility REAL NOT NULL DEFAULT 0,
                payer_id                  TEXT NOT NULL,
                payer_name                TEXT NOT NULL,
                created_at                TEXT NOT NULL,
                paid_at                   TEXT,
                denial_reason             TEXT,
                notes                     TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS claim_lines (
                id               TEXT PRIMARY KEY,
                claim_id         TEXT NOT NULL REFERENCES claims(id),
                cpt_code         TEXT NOT NULL,
                description      TEXT NOT NULL,
                units            INTEGER NOT NULL DEFAULT 1,
                charge_amount    REAL NOT NULL,
                allowed_amount   REAL NOT NULL DEFAULT 0,
                paid_amount      REAL NOT NULL DEFAULT 0,
                adjustment       REAL NOT NULL DEFAULT 0,
                denial_reason    TEXT NOT NULL DEFAULT '',
                position         INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS era_payments (
                id              TEXT PRIMARY KEY,
                claim_id        TEXT NOT NULL,
                payer_id        TEXT NOT NULL,
                check_number    TEXT NOT NULL,
                paid_amount     REAL NOT NULL,
                payment_date    TEXT NOT NULL,
                created_at      TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_claims_patient ON claims(patient_id);
            CREATE INDEX IF NOT EXISTS idx_claims_status  ON claims(status);
            CREATE INDEX IF NOT EXISTS idx_cl_claim       ON claim_lines(claim_id);
        """)


# ---------------------------------------------------------------------------
# Patient management
# ---------------------------------------------------------------------------

def register_patient(
    name: str,
    dob: str,
    insurance_id: str,
    insurance_provider: str,
    policy_number: str,
    group_number: str = "",
    copay: float = 20.0,
    deductible: float = 1000.0,
    path: str = DB_PATH,
) -> Patient:
    patient = Patient(
        id=str(uuid.uuid4()),
        name=name,
        dob=dob,
        insurance_id=insurance_id,
        insurance_provider=insurance_provider,
        policy_number=policy_number,
        group_number=group_number,
        copay=copay,
        deductible=deductible,
        deductible_met=0.0,
        created_at=_now(),
    )
    with get_db(path) as conn:
        conn.execute(
            """INSERT INTO patients
               (id, name, dob, insurance_id, insurance_provider, policy_number,
                group_number, copay, deductible, deductible_met, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (patient.id, patient.name, patient.dob, patient.insurance_id,
             patient.insurance_provider, patient.policy_number, patient.group_number,
             patient.copay, patient.deductible, patient.deductible_met, patient.created_at),
        )
    return patient


def get_patient(patient_id: str, path: str = DB_PATH) -> Patient:
    with get_db(path) as conn:
        row = conn.execute("SELECT * FROM patients WHERE id=?", (patient_id,)).fetchone()
    if not row:
        raise KeyError(f"Patient {patient_id} not found")
    return _row_to_patient(row)


# ---------------------------------------------------------------------------
# Claim operations
# ---------------------------------------------------------------------------

def create_claim(
    patient_id: str,
    provider_npi: str,
    date_of_service: str,
    diagnosis_codes: List[str],
    cpt_codes: List[str],
    units: Optional[List[int]] = None,
    payer_id: str = "bcbs",
    facility: str = "",
    notes: str = "",
    path: str = DB_PATH,
) -> Claim:
    """Create a new claim with CPT code line items."""
    get_patient(patient_id, path)  # validate patient
    if not diagnosis_codes:
        raise ValueError("At least one diagnosis code required")
    if not cpt_codes:
        raise ValueError("At least one CPT code required")

    payer_rate = PAYER_RATES.get(payer_id.lower(), 0.75)
    payer_name = payer_id.title().replace("_", " ")
    if units is None:
        units = [1] * len(cpt_codes)
    if len(units) != len(cpt_codes):
        raise ValueError("units list must match cpt_codes length")

    claim_lines_data = []
    for i, (cpt, unit) in enumerate(zip(cpt_codes, units)):
        cpt_info = COMMON_CPT_CODES.get(cpt, CptCode(cpt, f"Service {cpt}", 100.0, "procedure"))
        charge = round(cpt_info.base_rate * unit, 2)
        allowed = round(charge * payer_rate, 2)
        paid = allowed  # simple model
        adj = round(charge - allowed, 2)
        claim_lines_data.append(ClaimLine(
            cpt_code=cpt,
            description=cpt_info.description,
            units=unit,
            charge_amount=charge,
            allowed_amount=allowed,
            paid_amount=paid,
            adjustment=adj,
        ))

    total_charges = round(sum(cl.charge_amount for cl in claim_lines_data), 2)
    total_allowed = round(sum(cl.allowed_amount for cl in claim_lines_data), 2)
    total_paid = round(sum(cl.paid_amount for cl in claim_lines_data), 2)
    total_pr = round(sum(cl.patient_responsibility for cl in claim_lines_data), 2)

    with get_db(path) as conn:
        claim_num = _claim_number(conn)
        now = _now()
        claim = Claim(
            id=str(uuid.uuid4()),
            claim_number=claim_num,
            patient_id=patient_id,
            provider_npi=provider_npi,
            facility=facility,
            date_of_service=date_of_service,
            date_submitted=now,
            diagnosis_codes=diagnosis_codes,
            claim_lines=claim_lines_data,
            status="submitted",
            total_charges=total_charges,
            total_allowed=total_allowed,
            total_paid=total_paid,
            total_patient_responsibility=total_pr,
            payer_id=payer_id,
            payer_name=payer_name,
            created_at=now,
            notes=notes,
        )
        conn.execute(
            """INSERT INTO claims
               (id, claim_number, patient_id, provider_npi, facility, date_of_service,
                date_submitted, diagnosis_codes, status, total_charges, total_allowed,
                total_paid, total_patient_responsibility, payer_id, payer_name, created_at, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (claim.id, claim.claim_number, claim.patient_id, claim.provider_npi, claim.facility,
             claim.date_of_service, claim.date_submitted, json.dumps(claim.diagnosis_codes),
             claim.status, claim.total_charges, claim.total_allowed, claim.total_paid,
             claim.total_patient_responsibility, claim.payer_id, claim.payer_name,
             claim.created_at, claim.notes),
        )
        for i, cl in enumerate(claim_lines_data):
            conn.execute(
                """INSERT INTO claim_lines
                   (id, claim_id, cpt_code, description, units, charge_amount, allowed_amount,
                    paid_amount, adjustment, denial_reason, position)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()), claim.id, cl.cpt_code, cl.description, cl.units,
                 cl.charge_amount, cl.allowed_amount, cl.paid_amount, cl.adjustment,
                 cl.denial_reason, i),
            )
    return claim


def get_claim(claim_id: str, path: str = DB_PATH) -> Claim:
    with get_db(path) as conn:
        row = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
        if not row:
            raise KeyError(f"Claim {claim_id} not found")
        cl_rows = conn.execute(
            "SELECT * FROM claim_lines WHERE claim_id=? ORDER BY position", (claim_id,)
        ).fetchall()
    lines = [_row_to_claim_line(r) for r in cl_rows]
    return _row_to_claim(row, lines)


def process_era(
    claim_id: str,
    paid_amount: float,
    check_number: str,
    payment_date: Optional[str] = None,
    path: str = DB_PATH,
) -> Claim:
    """Process an Electronic Remittance Advice (ERA) payment for a claim."""
    with get_db(path) as conn:
        row = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
        if not row:
            raise KeyError(f"Claim {claim_id} not found")
        status = "paid" if paid_amount >= row["total_allowed"] else "partial"
        paid_at = payment_date or _now()
        conn.execute(
            "UPDATE claims SET status=?, total_paid=?, paid_at=? WHERE id=?",
            (status, paid_amount, paid_at, claim_id),
        )
        era_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO era_payments (id, claim_id, payer_id, check_number, paid_amount, payment_date, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (era_id, claim_id, row["payer_id"], check_number, paid_amount, paid_at, _now()),
        )
    return get_claim(claim_id, path)


def deny_claim(claim_id: str, reason: str, path: str = DB_PATH) -> Claim:
    with get_db(path) as conn:
        conn.execute(
            "UPDATE claims SET status='denied', denial_reason=? WHERE id=?",
            (reason, claim_id),
        )
    return get_claim(claim_id, path)


def appeal_claim(claim_id: str, notes: str = "", path: str = DB_PATH) -> Claim:
    with get_db(path) as conn:
        row = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
        if not row:
            raise KeyError(f"Claim {claim_id} not found")
        if row["status"] != "denied":
            raise ValueError("Only denied claims can be appealed")
        conn.execute(
            "UPDATE claims SET status='appealed', notes=? WHERE id=?",
            (notes, claim_id),
        )
    return get_claim(claim_id, path)


def list_claims(
    patient_id: Optional[str] = None,
    status: Optional[str] = None,
    payer_id: Optional[str] = None,
    path: str = DB_PATH,
) -> List[Claim]:
    with get_db(path) as conn:
        query = "SELECT id FROM claims WHERE 1=1"
        params = []
        if patient_id:
            query += " AND patient_id=?"
            params.append(patient_id)
        if status:
            query += " AND status=?"
            params.append(status)
        if payer_id:
            query += " AND payer_id=?"
            params.append(payer_id)
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
    return [get_claim(r["id"], path) for r in rows]


# ---------------------------------------------------------------------------
# Revenue analytics
# ---------------------------------------------------------------------------

def revenue_report(
    start: Optional[str] = None,
    end: Optional[str] = None,
    path: str = DB_PATH,
) -> Dict:
    """Generate a revenue report for a date range."""
    with get_db(path) as conn:
        query = "SELECT * FROM claims WHERE 1=1"
        params = []
        if start:
            query += " AND date_of_service >= ?"
            params.append(start)
        if end:
            query += " AND date_of_service <= ?"
            params.append(end)
        rows = conn.execute(query, params).fetchall()

    total_charges = sum(r["total_charges"] for r in rows)
    total_paid = sum(r["total_paid"] for r in rows)
    total_pr = sum(r["total_patient_responsibility"] for r in rows)

    by_status: Dict[str, int] = {}
    by_payer: Dict[str, float] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        by_payer[r["payer_id"]] = round(by_payer.get(r["payer_id"], 0) + r["total_paid"], 2)

    collection_rate = round(total_paid / total_charges * 100, 1) if total_charges else 0.0

    return {
        "period_start": start,
        "period_end": end,
        "total_claims": len(rows),
        "total_charges": round(total_charges, 2),
        "total_paid": round(total_paid, 2),
        "total_patient_responsibility": round(total_pr, 2),
        "collection_rate_pct": collection_rate,
        "by_status": by_status,
        "by_payer": by_payer,
    }


def days_in_ar(path: str = DB_PATH) -> float:
    """Calculate average days in Accounts Receivable for unpaid claims."""
    with get_db(path) as conn:
        rows = conn.execute(
            "SELECT date_submitted FROM claims WHERE status IN ('submitted','processing','partial')"
        ).fetchall()
    if not rows:
        return 0.0
    today = datetime.utcnow()
    days = []
    for r in rows:
        try:
            submitted = datetime.fromisoformat(r["date_submitted"])
            days.append((today - submitted).days)
        except Exception:
            pass
    return round(sum(days) / len(days), 1) if days else 0.0


def export_claims_csv(path: str = DB_PATH, output: Optional[str] = None) -> str:
    with get_db(path) as conn:
        rows = conn.execute("SELECT * FROM claims ORDER BY created_at DESC").fetchall()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "claim_number", "patient_id", "date_of_service", "status", "payer_id",
        "total_charges", "total_allowed", "total_paid", "total_patient_responsibility",
        "created_at", "paid_at", "denial_reason",
    ])
    for r in rows:
        writer.writerow([
            r["claim_number"], r["patient_id"], r["date_of_service"], r["status"],
            r["payer_id"], r["total_charges"], r["total_allowed"], r["total_paid"],
            r["total_patient_responsibility"], r["created_at"], r["paid_at"], r["denial_reason"],
        ])
    result = buf.getvalue()
    if output:
        with open(output, "w") as f:
            f.write(result)
    return result


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _row_to_patient(row: sqlite3.Row) -> Patient:
    return Patient(
        id=row["id"], name=row["name"], dob=row["dob"],
        insurance_id=row["insurance_id"], insurance_provider=row["insurance_provider"],
        policy_number=row["policy_number"], group_number=row["group_number"],
        copay=row["copay"], deductible=row["deductible"],
        deductible_met=row["deductible_met"], created_at=row["created_at"],
    )


def _row_to_claim_line(row: sqlite3.Row) -> ClaimLine:
    return ClaimLine(
        cpt_code=row["cpt_code"], description=row["description"],
        units=row["units"], charge_amount=row["charge_amount"],
        allowed_amount=row["allowed_amount"], paid_amount=row["paid_amount"],
        adjustment=row["adjustment"], denial_reason=row["denial_reason"],
    )


def _row_to_claim(row: sqlite3.Row, lines: List[ClaimLine]) -> Claim:
    return Claim(
        id=row["id"], claim_number=row["claim_number"],
        patient_id=row["patient_id"], provider_npi=row["provider_npi"],
        facility=row["facility"], date_of_service=row["date_of_service"],
        date_submitted=row["date_submitted"],
        diagnosis_codes=json.loads(row["diagnosis_codes"]),
        claim_lines=lines, status=row["status"],
        total_charges=row["total_charges"], total_allowed=row["total_allowed"],
        total_paid=row["total_paid"],
        total_patient_responsibility=row["total_patient_responsibility"],
        payer_id=row["payer_id"], payer_name=row["payer_name"],
        created_at=row["created_at"], paid_at=row["paid_at"],
        denial_reason=row["denial_reason"], notes=row["notes"],
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_json(obj) -> None:
    if hasattr(obj, "to_dict"):
        print(json.dumps(obj.to_dict(), indent=2))
    elif isinstance(obj, list):
        print(json.dumps([o.to_dict() if hasattr(o, "to_dict") else o for o in obj], indent=2))
    else:
        print(json.dumps(obj, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="medical_billing", description="BlackRoad Medical Billing System")
    parser.add_argument("--db", default=DB_PATH)
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("init")

    p = sub.add_parser("register-patient")
    p.add_argument("name")
    p.add_argument("dob")
    p.add_argument("insurance_id")
    p.add_argument("provider")
    p.add_argument("policy")
    p.add_argument("--group", default="")
    p.add_argument("--copay", type=float, default=20.0)
    p.add_argument("--deductible", type=float, default=1000.0)

    p = sub.add_parser("get-patient")
    p.add_argument("patient_id")

    p = sub.add_parser("create-claim")
    p.add_argument("patient_id")
    p.add_argument("npi")
    p.add_argument("dos")   # date of service
    p.add_argument("--dx", required=True, help="Diagnosis codes (comma-separated)")
    p.add_argument("--cpt", required=True, help="CPT codes (comma-separated)")
    p.add_argument("--units", default=None, help="Units (comma-separated, defaults to 1 each)")
    p.add_argument("--payer", default="bcbs")
    p.add_argument("--facility", default="")
    p.add_argument("--notes", default="")

    p = sub.add_parser("get-claim")
    p.add_argument("claim_id")

    p = sub.add_parser("process-era")
    p.add_argument("claim_id")
    p.add_argument("paid_amount", type=float)
    p.add_argument("check_number")

    p = sub.add_parser("deny-claim")
    p.add_argument("claim_id")
    p.add_argument("reason")

    p = sub.add_parser("appeal-claim")
    p.add_argument("claim_id")
    p.add_argument("--notes", default="")

    p = sub.add_parser("list-claims")
    p.add_argument("--patient", default=None)
    p.add_argument("--status", default=None)
    p.add_argument("--payer", default=None)

    p = sub.add_parser("revenue-report")
    p.add_argument("--start", default=None)
    p.add_argument("--end", default=None)

    sub.add_parser("days-in-ar")

    p = sub.add_parser("export-csv")
    p.add_argument("--output", default=None)

    sub.add_parser("cpt-codes")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    db = args.db
    init_db(db)

    if args.command == "init":
        print("Database initialized.")
    elif args.command == "register-patient":
        p = register_patient(args.name, args.dob, args.insurance_id, args.provider,
                              args.policy, args.group, args.copay, args.deductible, db)
        _print_json(p)
    elif args.command == "get-patient":
        _print_json(get_patient(args.patient_id, db))
    elif args.command == "create-claim":
        dx = [c.strip() for c in args.dx.split(",")]
        cpt = [c.strip() for c in args.cpt.split(",")]
        units = [int(u.strip()) for u in args.units.split(",")] if args.units else None
        claim = create_claim(args.patient_id, args.npi, args.dos, dx, cpt, units,
                             args.payer, args.facility, args.notes, db)
        _print_json(claim)
    elif args.command == "get-claim":
        _print_json(get_claim(args.claim_id, db))
    elif args.command == "process-era":
        _print_json(process_era(args.claim_id, args.paid_amount, args.check_number, path=db))
    elif args.command == "deny-claim":
        _print_json(deny_claim(args.claim_id, args.reason, db))
    elif args.command == "appeal-claim":
        _print_json(appeal_claim(args.claim_id, args.notes, db))
    elif args.command == "list-claims":
        _print_json(list_claims(args.patient, args.status, args.payer, db))
    elif args.command == "revenue-report":
        print(json.dumps(revenue_report(args.start, args.end, db), indent=2))
    elif args.command == "days-in-ar":
        print(json.dumps({"days_in_ar": days_in_ar(db)}))
    elif args.command == "export-csv":
        csv_str = export_claims_csv(db, args.output)
        if not args.output:
            print(csv_str)
    elif args.command == "cpt-codes":
        print(json.dumps({k: v.to_dict() for k, v in COMMON_CPT_CODES.items()}, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
