"""
Expectation suite đơn giản (không bắt buộc Great Expectations).

Sinh viên có thể thay bằng GE / pydantic / custom — miễn là có halt có kiểm soát.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


@dataclass
class ExpectationResult:
    name: str
    passed: bool
    severity: str  # "warn" | "halt"
    detail: str


def run_expectations(cleaned_rows: List[Dict[str, Any]]) -> Tuple[List[ExpectationResult], bool]:
    """
    Trả về (results, should_halt).

    should_halt = True nếu có bất kỳ expectation severity halt nào fail.
    """
    results: List[ExpectationResult] = []

    # E1: có ít nhất 1 dòng sau clean
    ok = len(cleaned_rows) >= 1
    results.append(
        ExpectationResult(
            "min_one_row",
            ok,
            "halt",
            f"cleaned_rows={len(cleaned_rows)}",
        )
    )

    # E2: không doc_id rỗng
    bad_doc = [r for r in cleaned_rows if not (r.get("doc_id") or "").strip()]
    ok2 = len(bad_doc) == 0
    results.append(
        ExpectationResult(
            "no_empty_doc_id",
            ok2,
            "halt",
            f"empty_doc_id_count={len(bad_doc)}",
        )
    )

    # E3: policy refund không được chứa cửa sổ sai 14 ngày (sau khi đã fix)
    bad_refund = [
        r
        for r in cleaned_rows
        if r.get("doc_id") == "policy_refund_v4"
        and "14 ngày làm việc" in (r.get("chunk_text") or "")
    ]
    ok3 = len(bad_refund) == 0
    results.append(
        ExpectationResult(
            "refund_no_stale_14d_window",
            ok3,
            "halt",
            f"violations={len(bad_refund)}",
        )
    )

    # E4: chunk_text đủ dài
    short = [r for r in cleaned_rows if len((r.get("chunk_text") or "")) < 8]
    ok4 = len(short) == 0
    results.append(
        ExpectationResult(
            "chunk_min_length_8",
            ok4,
            "warn",
            f"short_chunks={len(short)}",
        )
    )

    # E5: effective_date đúng định dạng ISO sau clean (phát hiện parser lỏng)
    iso_bad = [
        r
        for r in cleaned_rows
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", (r.get("effective_date") or "").strip())
    ]
    ok5 = len(iso_bad) == 0
    results.append(
        ExpectationResult(
            "effective_date_iso_yyyy_mm_dd",
            ok5,
            "halt",
            f"non_iso_rows={len(iso_bad)}",
        )
    )

    # E6: không còn marker phép năm cũ 10 ngày trên doc HR (conflict version sau clean)
    bad_hr_annual = [
        r
        for r in cleaned_rows
        if r.get("doc_id") == "hr_leave_policy"
        and "10 ngày phép năm" in (r.get("chunk_text") or "")
    ]
    ok6 = len(bad_hr_annual) == 0
    results.append(
        ExpectationResult(
            "hr_leave_no_stale_10d_annual",
            ok6,
            "halt",
            f"violations={len(bad_hr_annual)}",
        )
    )

    # E7: Cảnh báo nếu có chunk_text chứa từ 'BOM' (chống lỗi encoding hoặc dữ liệu lỗi)
    bom_chunks = [r for r in cleaned_rows if 'bom' in (r.get('chunk_text') or '').lower()]
    ok7 = len(bom_chunks) == 0
    results.append(
        ExpectationResult(
            "no_bom_in_chunk_text",
            ok7,
            "warn",
            f"bom_chunks={len(bom_chunks)}",
        )
    )

    # E8_V2: Không được có các chunk bị trùng lặp hoàn toàn nội dung trong cùng một doc_id
    seen = set()
    duplicates = []
    for r in cleaned_rows:
        signature = f"{r.get('doc_id', '')}:::{r.get('chunk_text', '')}"
        if signature in seen:
            duplicates.append(r.get('chunk_id'))
        else:
            seen.add(signature)
            
    ok8 = len(duplicates) == 0
    results.append(
        ExpectationResult(
            "no_duplicate_chunks",
            ok8,
            "warn",
            f"duplicate_chunk_ids={duplicates}",
        )
    )

    # E9: chunk_text không vượt quá giới hạn token (ví dụ 2000 ký tự)
    MAX_CHUNK_LENGTH = 2000
    oversized = [r for r in cleaned_rows if len(r.get("chunk_text") or "") > MAX_CHUNK_LENGTH]
    ok9 = len(oversized) == 0
    results.append(
        ExpectationResult(
            "chunk_max_length_2000",
            ok9,
            "warn",
            f"oversized_chunks={len(oversized)}",
        )
    )

    # E10: Không chứa HTML tags rác sót lại sau khi clean
    html_leaks = [
        r for r in cleaned_rows 
        if re.search(r"<\/?[a-z][\s\S]*>", (r.get("chunk_text") or ""), re.IGNORECASE)
    ]
    ok10 = len(html_leaks) == 0
    results.append(
        ExpectationResult(
            "no_residual_html_tags",
            ok10,
            "warn",
            f"dirty_html_chunks={len(html_leaks)}",
        )
    )

    # E11: Đảm bảo các tài liệu cốt lõi (Core Documents) không bị drop hoàn toàn
    core_docs = {"policy_refund_v4", "sla_p1_2026", "it_helpdesk_faq", "hr_leave_policy"}
    extracted_docs = {r.get("doc_id") for r in cleaned_rows}
    missing_docs = core_docs - extracted_docs
    ok11 = len(missing_docs) == 0
    results.append(
        ExpectationResult(
            "core_documents_present",
            ok11,
            "halt",
            f"missing_docs={list(missing_docs)}",
        )
    )

    # E12: Đảm bảo các facts quan trọng không bị mất mát trong quá trình chunking
    sla_chunks = [r for r in cleaned_rows if r.get("doc_id") == "sla_p1_2026"]
    has_15_mins = any("15 phút" in (r.get("chunk_text") or "").lower() for r in sla_chunks)
    
    faq_chunks = [r for r in cleaned_rows if r.get("doc_id") == "it_helpdesk_faq"]
    has_5_fails = any("5 lần" in (r.get("chunk_text") or "").lower() for r in faq_chunks)
    
    leave_chunks = [r for r in cleaned_rows if r.get("doc_id") == "hr_leave_policy"]
    has_12_days = any("12 ngày" in (r.get("chunk_text") or "").lower() for r in leave_chunks)

    failed_facts = []
    # Chỉ cảnh báo fact mất nếu document đó có tồn tại
    if sla_chunks and not has_15_mins:
        failed_facts.append("Missing '15 phút' in sla_p1_2026")
    if faq_chunks and not has_5_fails:
        failed_facts.append("Missing '5 lần' in it_helpdesk_faq")
    if leave_chunks and not has_12_days:
        failed_facts.append("Missing '12 ngày' in hr_leave_policy")
        
    ok12 = len(failed_facts) == 0
    results.append(
        ExpectationResult(
            "critical_facts_intact",
            ok12,
            "halt",
            f"failed_facts={failed_facts}",
        )
    )

    halt = any(not r.passed and r.severity == "halt" for r in results)
    return results, halt
