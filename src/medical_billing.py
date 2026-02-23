"""
BR Medical Billing - Medical billing codes and insurance claim tracker.
SQLite persistence at ~/.blackroad/medical_billing.db
"""
import argparse
import csv
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

GREEN = "\033[0;32m"
RED = "\033[0;31m"
YELLOW = "\033[1;33m"
CYAN = "\033[0;36m"
BLUE = "\033[0;34m"
BOLD = "\033[1m"
RESET = "\033[0m"

DB_PATH = Path.home() / ".blackroad" / "medical_billing.db"
CLAIM_STATUSES = ["submitted", "pending", "approved", "denied", "appealed", "paid"]

STATUS_COLOR = {
    "submitted": CYAN, "pending": YELLOW, "approved": GREEN,
    "denied": RED, "appealed": YELLOW, "paid": BOLD + GREEN,
}


@dataclass
class BillingCode:
    id: Optional[int]
    code: str
    description: str
    amount: float


@dataclass
class Patient:
    id: Optional[int]
    name: str
    dob: str
    insurance_id: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class Claim:
    id: Optional[int]
    patient_id: int
    patient_name: str
    provider: str
    amount: float
    status: str
    billing_codes: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())


class MedicalBillingSystem:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS patients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    dob TEXT,
                    insurance_id TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS billing_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    description TEXT,
                    amount REAL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS claims (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    patient_id INTEGER REFERENCES patients(id),
                    provider TEXT,
                    amount REAL DEFAULT 0,
                    status TEXT DEFAULT 'submitted',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS claim_codes (
                    claim_id INTEGER REFERENCES claims(id) ON DELETE CASCADE,
                    code TEXT NOT NULL,
                    PRIMARY KEY (claim_id, code)
                );
            """)

    def add_patient(self, name: str, dob: str = "", insurance_id: str = "") -> Patient:
        now = datetime.now().isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO patients (name, dob, insurance_id, created_at) VALUES (?,?,?,?)",
                (name, dob, insurance_id, now),
            )
        return Patient(id=cur.lastrowid, name=name, dob=dob, insurance_id=insurance_id, created_at=now)

    def add_claim(self, patient_name: str, provider: str, amount: float,
                  codes: Optional[List[str]] = None) -> Optional[Claim]:
        now = datetime.now().isoformat()
        with self._conn() as conn:
            patient = conn.execute("SELECT id FROM patients WHERE name=?", (patient_name,)).fetchone()
            if not patient:
                cur = conn.execute(
                    "INSERT INTO patients (name, created_at) VALUES (?,?)", (patient_name, now)
                )
                patient_id = cur.lastrowid
            else:
                patient_id = patient["id"]
            cur = conn.execute(
                "INSERT INTO claims (patient_id, provider, amount, status, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?)",
                (patient_id, provider, amount, "submitted", now, now),
            )
            claim_id = cur.lastrowid
            for code in (codes or []):
                conn.execute("INSERT OR IGNORE INTO claim_codes (claim_id, code) VALUES (?,?)",
                             (claim_id, code.strip()))
        return Claim(id=claim_id, patient_id=patient_id, patient_name=patient_name,
                     provider=provider, amount=amount, status="submitted",
                     billing_codes=codes or [], created_at=now, updated_at=now)

    def update_claim_status(self, claim_id: int, new_status: str) -> bool:
        if new_status not in CLAIM_STATUSES:
            return False
        now = datetime.now().isoformat()
        with self._conn() as conn:
            result = conn.execute(
                "UPDATE claims SET status=?, updated_at=? WHERE id=?", (new_status, now, claim_id)
            )
        return result.rowcount > 0

    def list_claims(self, status: Optional[str] = None, patient: Optional[str] = None) -> List[dict]:
        with self._conn() as conn:
            query = (
                "SELECT c.*, p.name as patient_name FROM claims c "
                "JOIN patients p ON c.patient_id=p.id WHERE 1=1"
            )
            params: list = []
            if status:
                query += " AND c.status=?"
                params.append(status)
            if patient:
                query += " AND p.name LIKE ?"
                params.append(f"%{patient}%")
            query += " ORDER BY c.created_at DESC"
            rows = conn.execute(query, params).fetchall()
            result = []
            for row in rows:
                d = dict(row)
                codes = conn.execute(
                    "SELECT code FROM claim_codes WHERE claim_id=?", (row["id"],)
                ).fetchall()
                d["billing_codes"] = [c["code"] for c in codes]
                result.append(d)
            return result

    def get_status(self) -> dict:
        with self._conn() as conn:
            patients = conn.execute("SELECT COUNT(*) as c FROM patients").fetchone()["c"]
            claims = conn.execute("SELECT COUNT(*) as c FROM claims").fetchone()["c"]
            total_billed = conn.execute("SELECT SUM(amount) as s FROM claims").fetchone()["s"] or 0.0
            total_paid = conn.execute(
                "SELECT SUM(amount) as s FROM claims WHERE status='paid'"
            ).fetchone()["s"] or 0.0
            by_status = conn.execute(
                "SELECT status, COUNT(*) as c FROM claims GROUP BY status"
            ).fetchall()
        return {"total_patients": patients, "total_claims": claims,
                "total_billed": total_billed, "total_paid": total_paid,
                "by_status": {r["status"]: r["c"] for r in by_status}}

    def export(self, output_path: str, fmt: str = "json") -> None:
        claims = self.list_claims()
        if fmt == "json":
            with open(output_path, "w") as f:
                json.dump(claims, f, indent=2)
        else:
            fields = ["id", "patient_name", "provider", "amount", "status", "billing_codes",
                      "created_at", "updated_at"]
            with open(output_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                for c in claims:
                    c["billing_codes"] = "|".join(c["billing_codes"])
                    writer.writerow(c)


def main():
    parser = argparse.ArgumentParser(description="BR Medical Billing System")
    sub = parser.add_subparsers(dest="cmd")

    p_list = sub.add_parser("list", help="List claims")
    p_list.add_argument("--status", choices=CLAIM_STATUSES, help="Filter by status")
    p_list.add_argument("--patient", help="Filter by patient name")

    p_add = sub.add_parser("add", help="Add a claim")
    p_add.add_argument("patient_name")
    p_add.add_argument("provider")
    p_add.add_argument("amount", type=float)
    p_add.add_argument("--codes", nargs="+", default=[], help="Billing codes (e.g. CPT-99213)")

    sub.add_parser("status", help="Show system status")

    p_exp = sub.add_parser("export", help="Export claims")
    p_exp.add_argument("output")
    p_exp.add_argument("--format", dest="fmt", choices=["json", "csv"], default="json")

    p_upd = sub.add_parser("update", help="Update claim status")
    p_upd.add_argument("claim_id", type=int)
    p_upd.add_argument("new_status", choices=CLAIM_STATUSES)

    args = parser.parse_args()
    sys_billing = MedicalBillingSystem()

    if args.cmd == "list":
        claims = sys_billing.list_claims(status=args.status, patient=args.patient)
        if not claims:
            print(f"{YELLOW}No claims found.{RESET}")
            return
        print(f"{BOLD}{CYAN}{'ID':<5} {'Patient':<22} {'Provider':<20} {'Amount':>9} {'Status':<12} {'Codes'}{RESET}")
        print(f"{CYAN}{'-'*90}{RESET}")
        for c in claims:
            sc = STATUS_COLOR.get(c["status"], RESET)
            codes_str = ", ".join(c["billing_codes"]) or "-"
            print(f"{GREEN}{c['id']:<5}{RESET} {c['patient_name']:<22} {c['provider']:<20} "
                  f"{BLUE}${c['amount']:>8.2f}{RESET} {sc}{c['status']:<12}{RESET} {YELLOW}{codes_str}{RESET}")
    elif args.cmd == "add":
        claim = sys_billing.add_claim(args.patient_name, args.provider, args.amount, args.codes)
        if claim:
            print(f"{GREEN}✓ Claim #{claim.id} added for '{claim.patient_name}' — ${claim.amount:.2f}{RESET}")
    elif args.cmd == "status":
        s = sys_billing.get_status()
        print(f"{BOLD}{CYAN}Medical Billing System Status{RESET}")
        print(f"  {BLUE}Total Patients :{RESET} {GREEN}{s['total_patients']}{RESET}")
        print(f"  {BLUE}Total Claims   :{RESET} {GREEN}{s['total_claims']}{RESET}")
        print(f"  {BLUE}Total Billed   :{RESET} {YELLOW}${s['total_billed']:.2f}{RESET}")
        print(f"  {BLUE}Total Paid     :{RESET} {GREEN}${s['total_paid']:.2f}{RESET}")
        for st, c in s["by_status"].items():
            sc = STATUS_COLOR.get(st, RESET)
            print(f"    {sc}{st:<12}{RESET} {c}")
    elif args.cmd == "export":
        sys_billing.export(args.output, args.fmt)
        print(f"{GREEN}✓ Exported to {args.output}{RESET}")
    elif args.cmd == "update":
        ok = sys_billing.update_claim_status(args.claim_id, args.new_status)
        if ok:
            sc = STATUS_COLOR.get(args.new_status, RESET)
            print(f"{GREEN}✓ Claim #{args.claim_id} updated to {sc}{args.new_status}{RESET}")
        else:
            print(f"{RED}✗ Claim #{args.claim_id} not found or invalid status{RESET}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
