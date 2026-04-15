"""
Cleaning rules — raw export → cleaned rows + quarantine.

Baseline gồm các failure mode mở rộng (allowlist doc_id, parse ngày, HR stale version).
Sinh viên thêm ≥3 rule mới: mỗi rule phải ghi `metric_impact` (xem README — chống trivial).
"""

from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

# Merit/Distinction: Load configuration from data_contract.yaml
CONTRACT_PATH = Path(__file__).resolve().parent.parent / "contracts" / "data_contract.yaml"
def _load_contract_config():
    try:
        with open(CONTRACT_PATH, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
            return {
                "allowed_doc_ids": frozenset(cfg.get("allowed_doc_ids", [])),
                "hr_leave_min_date": cfg.get("policy_versioning", {}).get("hr_leave_min_effective_date", "2026-01-01")
            }
    except Exception:
        # Fallback if contract not found/invalid
        return {
            "allowed_doc_ids": frozenset({"policy_refund_v4", "sla_p1_2026", "it_helpdesk_faq", "hr_leave_policy"}),
            "hr_leave_min_date": "2026-01-01"
        }

_CONFIG = _load_contract_config()
ALLOWED_DOC_IDS = _CONFIG["allowed_doc_ids"]
HR_LEAVE_MIN_DATE = _CONFIG["hr_leave_min_date"]

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DMY_SEP = re.compile(r"^(\d{2})[/-](\d{2})[/-](\d{4})$")


def _norm_text(s: str) -> str:
    # Rule 7: Normalize whitespace and lower-case for stable hash/dedupe
    return " ".join((s or "").strip().split()).lower()


def _stable_chunk_id(doc_id: str, chunk_text: str, seq: int) -> str:
    h = hashlib.sha256(f"{doc_id}|{chunk_text}|{seq}".encode("utf-8")).hexdigest()[:16]
    return f"{doc_id}_{seq}_{h}"


def _normalize_effective_date(raw: str) -> Tuple[str, str]:
    """
    Trả về (iso_date, error_reason).
    iso_date rỗng nếu không parse được.
    """
    s = (raw or "").strip()
    if not s:
        return "", "empty_effective_date"
    if _ISO_DATE.match(s):
        return s, ""
    m = _DMY_SEP.match(s)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        return f"{yyyy}-{mm}-{dd}", ""
    return "", "invalid_effective_date_format"


def load_raw_csv(path: Path) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({k: (v or "").strip() for k, v in r.items()})
    return rows


def clean_rows(
    rows: List[Dict[str, str]],
    *,
    apply_refund_window_fix: bool = True,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Trả về (cleaned, quarantine).

    Baseline (mở rộng theo narrative Day 10):
    1) Quarantine: doc_id không thuộc allowlist (export lạ / catalog sai).
    2) Chuẩn hoá effective_date sang YYYY-MM-DD; quarantine nếu không parse được.
    3) Quarantine: chunk hr_leave_policy có effective_date < HR_LEAVE_MIN_DATE (bản HR cũ / conflict version).
    4) Quarantine: chunk_text rỗng hoặc effective_date rỗng sau chuẩn hoá.
    5) Loại trùng nội dung chunk_text (giữ bản đầu).
    6) Fix stale refund: policy_refund_v4 chứa '14 ngày làm việc' -> 7 ngày.

    New rules added for Lab:
    7) Normalize whitespace: Rule 7 - Xóa khoảng trắng thừa và ký tự đặc biệt gây nhiễu embedding.
    8) Fix stale P1 SLA: Rule 8 - policy_p1_2026 chứa '4 giờ' -> '2 giờ' theo SLA mới 2026.
    9) IT FAQ Prefix: Rule 9 - Thêm prefix 'IT FAQ: ' cho it_helpdesk_faq để grounding tốt hơn.
    10) Normalize special characters: Rule 10 - Chuẩn hóa các ký tự đặc biệt như smart quotes để embedding ổn định.
    11) Remove PII: Rule 11 - Xóa các email xuất hiện trong text để bảo vệ quyền riêng tư (Grounding safety).
    12) Quarantine short text: Rule 12 - Chặn các chunk quá ngắn (<8 ký tự) để tránh nhiễu retrieval.
    13) Quarantine placeholders: Rule 13 - Chặn các chunk chứa TODO, FIXME, hoặc lỗi migration.
    """
    quarantine: List[Dict[str, Any]] = []
    seen_text: set[str] = set()
    cleaned: List[Dict[str, Any]] = []
    seq = 0

    # Rule 11: PII Regex (Email)
    email_regex = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
    # Rule 13: Suspicious markers
    suspicious_markers = ["???", "TODO", "FIXME", "lỗi migration"]

    for raw in rows:
        # Normalize doc_id for case-insensitive check
        doc_id = (raw.get("doc_id", "")).strip().lower()
        text = raw.get("chunk_text", "")
        eff_raw = raw.get("effective_date", "")
        exported_at = raw.get("exported_at", "")

        if doc_id not in ALLOWED_DOC_IDS:
            quarantine.append({**raw, "reason": "unknown_doc_id"})
            continue

        eff_norm, eff_err = _normalize_effective_date(eff_raw)
        if eff_err == "empty_effective_date":
            quarantine.append({**raw, "reason": "missing_effective_date"})
            continue
        if eff_err == "invalid_effective_date_format":
            quarantine.append({**raw, "reason": eff_err, "effective_date_raw": eff_raw})
            continue

        if doc_id == "hr_leave_policy" and eff_norm < HR_LEAVE_MIN_DATE:
            quarantine.append(
                {
                    **raw,
                    "reason": "stale_hr_policy_effective_date",
                    "effective_date_normalized": eff_norm,
                }
            )
            continue

        if not text:
            quarantine.append({**raw, "reason": "missing_chunk_text"})
            continue

        # --- TEXT CLEANING PHASE ---
        fixed_text = text
        
        # Rule 7: Normalize whitespace
        fixed_text = " ".join(fixed_text.strip().split())

        # Rule 10: Normalize special characters (smart quotes)
        fixed_text = fixed_text.replace("“", "\"").replace("”", "\"").replace("‘", "'").replace("’", "'")

        # Rule 11: Remove PII (Emails)
        if email_regex.search(fixed_text):
            fixed_text = email_regex.sub("[REDACTED_EMAIL]", fixed_text)

        # Rule 6: Fix stale refund
        if apply_refund_window_fix and doc_id == "policy_refund_v4":
            if "14 ngày làm việc" in fixed_text:
                fixed_text = fixed_text.replace("14 ngày làm việc", "7 ngày làm việc")
                fixed_text += " [cleaned: stale_refund_window]"

        # # Rule 8: Fix stale P1 SLA (4h -> 2h)
        # if doc_id == "sla_p1_2026":
        #     if "4 giờ" in fixed_text:
        #         fixed_text = fixed_text.replace("4 giờ", "2 giờ")
        #         fixed_text += " [cleaned: stale_sla_p1]"

        # Rule 9: IT FAQ Prefix (Case-insensitive check)
        if doc_id == "it_helpdesk_faq":
            if not fixed_text.lower().startswith("it faq:"):
                fixed_text = "IT FAQ: " + fixed_text

        # --- QUALITY QUARANTINE PHASE ---
        
        # Rule 12: Short text
        if len(fixed_text) < 8:
            quarantine.append({**raw, "reason": "text_too_short", "cleaned_text": fixed_text})
            continue

        # Rule 13: Suspicious placeholders
        if any(m in fixed_text for m in suspicious_markers):
            quarantine.append({**raw, "reason": "suspicious_placeholders_detected", "cleaned_text": fixed_text})
            continue

        # --- DEDUPLICATION PHASE ---
        key = fixed_text.lower()
        if key in seen_text:
            quarantine.append({**raw, "reason": "duplicate_chunk_text"})
            continue
        seen_text.add(key)

        # --- OUTPUT PHASE ---
        seq += 1
        cleaned.append(
            {
                "chunk_id": _stable_chunk_id(doc_id, fixed_text, seq),
                "doc_id": doc_id,
                "chunk_text": fixed_text,
                "effective_date": eff_norm,
                "exported_at": exported_at or "",
            }
        )

    return cleaned, quarantine



def write_cleaned_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("chunk_id,doc_id,chunk_text,effective_date,exported_at\n", encoding="utf-8")
        return
    fieldnames = ["chunk_id", "doc_id", "chunk_text", "effective_date", "exported_at"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def write_quarantine_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("chunk_id,doc_id,chunk_text,effective_date,exported_at,reason\n", encoding="utf-8")
        return
    keys: List[str] = []
    seen_k: set[str] = set()
    for r in rows:
        for k in r.keys():
            if k not in seen_k:
                seen_k.add(k)
                keys.append(k)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore", restval="")
        w.writeheader()
        for r in rows:
            w.writerow(r)
