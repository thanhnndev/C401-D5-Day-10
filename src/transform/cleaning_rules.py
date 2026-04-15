"""
Cleaning rules — raw export → cleaned rows + quarantine.

Baseline gồm các failure mode mở rộng (allowlist doc_id, parse ngày, HR stale version).
Sinh viên thêm ≥3 rule mới: mỗi rule phải ghi `metric_impact` (xem README — chống trivial).
"""

from __future__ import annotations

import csv
import hashlib
import re
import os
import yaml
from pathlib import Path
from typing import Any, Dict, List, Tuple

CONTRACT_PATH = Path(__file__).resolve().parent.parent.parent / "contracts" / "data_contract.yaml"

def get_hr_cutoff() -> str:
    try:
        with CONTRACT_PATH.open("r", encoding="utf-8") as f:
            contract = yaml.safe_load(f)
            # Fetch from section policy_versioning
            if contract and "policy_versioning" in contract:
                return contract["policy_versioning"].get("hr_leave_min_effective_date", "2026-01-01")
    except Exception:
        pass
    return os.environ.get("HR_MIN_DATE", "2026-01-01")

# Khớp export hợp lệ trong lab (mở rộng khi nhóm thêm doc mới — phải đồng bộ contract).
ALLOWED_DOC_IDS = frozenset(
    {
        "policy_refund_v4",
        "sla_p1_2026",
        "it_helpdesk_faq",
        "hr_leave_policy",
    }
)

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DMY_SLASH = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")


def _norm_text(s: str) -> str:
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
    m = _DMY_SLASH.match(s)
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
    3) Quarantine: chunk hr_leave_policy có effective_date < 2026-01-01 (bản HR cũ / conflict version).
    4) Quarantine: chunk_text rỗng hoặc effective_date rỗng sau chuẩn hoá.
    5) Loại trùng nội dung chunk_text (giữ bản đầu).
    6) Fix stale refund: policy_refund_v4 chứa '14 ngày làm việc' → 7 ngày.
    """
    quarantine: List[Dict[str, Any]] = []
    seen_text: set[str] = set()
    cleaned: List[Dict[str, Any]] = []
    seq = 0

    hr_cutoff = get_hr_cutoff()

    for raw in rows:
        doc_id = raw.get("doc_id", "")
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

        if doc_id == "hr_leave_policy" and eff_norm < hr_cutoff:
            quarantine.append(
                {
                    **raw,
                    "reason": "stale_hr_policy_effective_date",
                    "effective_date_normalized": eff_norm,
                    "cutoff_applied": hr_cutoff,
                }
            )
            continue

        if not text:
            quarantine.append({**raw, "reason": "missing_chunk_text"})
            continue

        # Rule 1: Lọc junk/placeholders
        if text.upper() in ["N/A", "NULL", "UNDEFINED"]:
            quarantine.append({**raw, "reason": "meaningless_placeholder"})
            continue
            
        key = _norm_text(text)
        if key in seen_text:
            quarantine.append({**raw, "reason": "duplicate_chunk_text"})
            continue
        seen_text.add(key)

        fixed_text = text
        
        # Rule 2: Xóa ký tự rác (BOM, replacement char)
        if "\ufeff" in fixed_text or "\ufffd" in fixed_text:
            fixed_text = fixed_text.replace("\ufeff", "").replace("\ufffd", "")
            fixed_text += " [cleaned: removed_garbage_chars]"
            
        # Rule 3: Chunk quá ngắn (nhỏ hơn 15 ký tự thường không mang lại đủ context/semantic)
        if len(fixed_text.strip()) < 15:
            quarantine.append({**raw, "reason": "chunk_too_short"})
            continue

        if apply_refund_window_fix and doc_id == "policy_refund_v4":
            if "14 ngày làm việc" in fixed_text:
                fixed_text = fixed_text.replace(
                    "14 ngày làm việc",
                    "7 ngày làm việc",
                )
                fixed_text += " [cleaned: stale_refund_window]"

        # Rule 7: Normalize whitespace
        fixed_text = re.sub(r'\s+', ' ', fixed_text).strip()

        # Rule 8: Fix stale P1 SLA
        if doc_id == "sla_p1_2026":
            if "4 giờ" in fixed_text:
                fixed_text = fixed_text.replace("4 giờ", "2 giờ")
                fixed_text += " [cleaned: update_sla_p1]"

        # Rule 9: IT FAQ Prefix
        if doc_id == "it_helpdesk_faq":
            if not fixed_text.startswith("IT FAQ: "):
                fixed_text = f"IT FAQ: {fixed_text}"

        # Rule 10: Normalize special characters
        fixed_text = fixed_text.replace('“', '"').replace('”', '"').replace('‘', "'").replace('’', "'")

        # Rule 11: Remove PII (Emails)
        if "@" in fixed_text:
            fixed_text = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[EMAIL_REMOVED]', fixed_text)

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

if __name__ == "__main__":
    print("--- TESTING CLEANING RULES ---")
    test_rows: List[Dict[str, str]] = [
        # Normal row
        {"doc_id": "it_helpdesk_faq", "chunk_text": "Tài liệu hướng dẫn về quy trình reset password.", "effective_date": "2026-05-01", "exported_at": "2026-05-01T08:00:00Z"},
        # Rule 1: Meaningless placeholder
        {"doc_id": "it_helpdesk_faq", "chunk_text": "N/A", "effective_date": "2026-05-01", "exported_at": "2026-05-01T08:00:00Z"},
        # Rule 2: Garbage chars (Replacement \ufffd)
        {"doc_id": "sla_p1_2026", "chunk_text": "SLA cho ticket P1 được xử lý trong vòng 15 phút. \ufffd", "effective_date": "2026-05-01", "exported_at": "2026-05-01T08:00:00Z"},
        # Rule 3: Too short
        {"doc_id": "policy_refund_v4", "chunk_text": "Cực kì ngắn", "effective_date": "2026-05-01", "exported_at": "2026-05-01T08:00:00Z"},
        # Baseline Rules (Stale Refund)
        {"doc_id": "policy_refund_v4", "chunk_text": "Quy định cũ: Khách được hoàn trả lại sau 14 ngày làm việc kể từ lúc hủy.", "effective_date": "2026-05-01", "exported_at": "2026-05-01T08:00:00Z"},
        {"doc_id": "hr_leave_policy", "chunk_text": "Nhân viên dưới 3 năm nhận 10 ngày phép năm.", "effective_date": "2025-12-31", "exported_at": "2026-05-01T08:00:00Z"},
    ]

    cleaned, quarantine = clean_rows(test_rows)

    print(f"\n=> Total input rows: {len(test_rows)}")
    
    print("\n--- CLEANED ---")
    for idx, c in enumerate(cleaned, 1):
        print(f"{idx}. [{c['doc_id']}] {c['chunk_text']}")

    print("\n--- QUARANTINE ---")
    for idx, q in enumerate(quarantine, 1):
        print(f"{idx}. [{q['reason']}] {q['chunk_text']}")


