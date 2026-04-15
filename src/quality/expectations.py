"""
Expectation suite tích hợp Pydantic V2.
Sử dụng Pydantic để validate schema và các business rules phức tạp (PII, stale data).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple
from pydantic import BaseModel, Field, field_validator, model_validator, ValidationError


@dataclass
class ExpectationResult:
    name: str
    passed: bool
    severity: str  # "warn" | "halt"
    detail: str


class CleanedRow(BaseModel):
    """Schema Pydantic cho bản ghi đã dọn dẹp"""
    chunk_id: str
    doc_id: str = Field(min_length=1)
    chunk_text: str
    effective_date: str
    exported_at: str

    @field_validator("effective_date")
    @classmethod
    def validate_iso_date(cls, v: str) -> str:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v.strip()):
            raise ValueError("effective_date_not_iso")
        return v

    @model_validator(mode="after")
    def validate_business_logic(self) -> 'CleanedRow':
        text = self.chunk_text
        doc = self.doc_id

        # Refund stale
        if doc == "policy_refund_v4" and "14 ngày làm việc" in text:
            raise ValueError("stale_refund_window_detected")
        
        # HR stale
        if doc == "hr_leave_policy" and "10 ngày phép năm" in text:
            raise ValueError("stale_hr_policy_detected")

        # PII Check (Emails)
        raw_email = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
        if raw_email.search(text):
            raise ValueError("raw_pii_email_detected")

        return self


def run_expectations(cleaned_rows: List[Dict[str, Any]]) -> Tuple[List[ExpectationResult], bool]:
    """
    Trả về (results, should_halt).
    Tích hợp Pydantic để kiểm tra schema và logic nghiệp vụ.
    """
    results: List[ExpectationResult] = []
    
    # E1: Global check (min one row)
    results.append(
        ExpectationResult(
            "min_one_row",
            len(cleaned_rows) >= 1,
            "halt",
            f"cleaned_rows={len(cleaned_rows)}",
        )
    )

    # Chạy Pydantic validation cho từng dòng
    pydantic_errors = []
    for i, row in enumerate(cleaned_rows):
        try:
            CleanedRow(**row)
        except ValidationError as e:
            for error in e.errors():
                pydantic_errors.append({
                    "row_index": i,
                    "msg": error["msg"],
                    "type": error["type"]
                })

    # Mapping Pydantic errors back to individual Expectations for logging clarity
    
    # E2: doc_id rỗng (Pydantic Field min_length=1)
    bad_doc_ids = [e for e in pydantic_errors if "String should have at least 1 character" in e["msg"] and "doc_id" in str(e)]
    results.append(ExpectationResult("no_empty_doc_id", len(bad_doc_ids) == 0, "halt", f"violations={len(bad_doc_ids)}"))

    # E3: Refund stale 14d
    bad_refund = [e for e in pydantic_errors if "stale_refund_window_detected" in e["msg"]]
    results.append(ExpectationResult("refund_no_stale_14d_window", len(bad_refund) == 0, "halt", f"violations={len(bad_refund)}"))

    # E5: ISO Date
    bad_iso = [e for e in pydantic_errors if "effective_date_not_iso" in e["msg"]]
    results.append(ExpectationResult("effective_date_iso_yyyy_mm_dd", len(bad_iso) == 0, "halt", f"violations={len(bad_iso)}"))

    # E6: HR stale
    bad_hr = [e for e in pydantic_errors if "stale_hr_policy_detected" in e["msg"]]
    results.append(ExpectationResult("hr_leave_no_stale_10d_annual", len(bad_hr) == 0, "halt", f"violations={len(bad_hr)}"))

    # E7: SLA stale
    # bad_sla = [e for e in pydantic_errors if "stale_sla_p1_detected" in e["msg"]]
    # results.append(ExpectationResult("sla_p1_no_stale_4h_window", len(bad_sla) == 0, "halt", f"violations={len(bad_sla)}"))

    # E10: PII
    bad_pii = [e for e in pydantic_errors if "raw_pii_email_detected" in e["msg"]]
    results.append(ExpectationResult("no_raw_emails_pii", len(bad_pii) == 0, "halt", f"violations={len(bad_pii)}"))

    # Manual Warn Checks (Các check không làm halt pipeline)
    
    # E4: chunk_text đủ dài (warn)
    short = [r for r in cleaned_rows if len((r.get("chunk_text") or "")) < 8]
    results.append(ExpectationResult("chunk_min_length_8", len(short) == 0, "warn", f"short_chunks={len(short)}"))

    # E8: Ký tự nghi vấn (warn)
    suspicious = [r for r in cleaned_rows if any(m in (r.get("chunk_text") or "") for m in ["???", "TODO", "FIXME", "lỗi migration"])]
    results.append(ExpectationResult("no_suspicious_placeholders", len(suspicious) == 0, "warn", f"suspicious_chunks={len(suspicious)}"))

    # E9: Thiếu exported_at (warn)
    no_exported = [r for r in cleaned_rows if not (r.get("exported_at") or "").strip()]
    results.append(ExpectationResult("has_exported_at_timestamp", len(no_exported) == 0, "warn", f"missing_exported_at={len(no_exported)}"))

    halt = any(not r.passed and r.severity == "halt" for r in results)
    return results, halt
