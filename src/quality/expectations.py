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

    # # E12: Đảm bảo các facts quan trọng không bị mất mát trong quá trình chunking
    # sla_chunks = [r for r in cleaned_rows if r.get("doc_id") == "sla_p1_2026"]
    # has_15_mins = any("15 phút" in (r.get("chunk_text") or "").lower() for r in sla_chunks)
    
    # faq_chunks = [r for r in cleaned_rows if r.get("doc_id") == "it_helpdesk_faq"]
    # has_5_fails = any("5 lần" in (r.get("chunk_text") or "").lower() for r in faq_chunks)
    
    # leave_chunks = [r for r in cleaned_rows if r.get("doc_id") == "hr_leave_policy"]
    # has_12_days = any("12 ngày" in (r.get("chunk_text") or "").lower() for r in leave_chunks)

    # failed_facts = []
    # # Chỉ cảnh báo fact mất nếu document đó có tồn tại
    # if sla_chunks and not has_15_mins:
    #     failed_facts.append("Missing '15 phút' in sla_p1_2026")
    # if faq_chunks and not has_5_fails:
    #     failed_facts.append("Missing '5 lần' in it_helpdesk_faq")
    # if leave_chunks and not has_12_days:
    #     failed_facts.append("Missing '12 ngày' in hr_leave_policy")
        
    # ok12 = len(failed_facts) == 0
    # results.append(
    #     ExpectationResult(
    #         "critical_facts_intact",
    #         ok12,
    #         "halt",
    #         f"failed_facts={failed_facts}",
    #     )
    # )

    # -------------------------------------------------------------------------
    # E12: Đảm bảo các Facts quan trọng (Số liệu định lượng) không bị mất mát
    # Sử dụng Pattern Builder tự động sinh Regex cho các form: x ngày, x-y giờ, x%...
    # -------------------------------------------------------------------------
    
    def build_fact_pattern(value: str, unit: str) -> str:
        """
        Hàm tạo Regex chuẩn xác cho các định dạng số liệu.
        - value: "15" (số fix), "x" (số bất kỳ), "2-4" (khoảng fix), "x-y" (khoảng bất kỳ)
        - unit: "ngày", "tuần", "tháng", "năm", "giờ", "phút", "%", "ngày/năm", ...
        """
        num_regex = r"\d+(?:[.,]\d+)?"  # Bắt số nguyên hoặc số thập phân (vd: 1.5, 10)
        
        if value == "x":
            v_pattern = num_regex
        elif value == "x-y":
            v_pattern = rf"{num_regex}\s*-\s*{num_regex}"
        elif "-" in value and "x" not in value:
            # Khoảng fix cứng (VD: "2-4" -> "2 - 4")
            parts = value.split("-")
            v_pattern = rf"{parts[0].strip()}\s*-\s*{parts[1].strip()}"
        else:
            v_pattern = str(value)

        # Escape đơn vị để an toàn với các ký tự đặc biệt như / hoặc %
        u_pattern = re.escape(unit)
        
        # \b đảm bảo ranh giới từ, tránh bắt nhầm (vd: bắt "15" không bắt nhầm trong "150")
        return rf"\b{v_pattern}\s*{u_pattern}"

    # Cấu hình Expectation E12 dựa trên Data Catalog thực tế
    FACT_RULES = {
        "sla_p1_2026": [
            build_fact_pattern("15", "phút"),      # Phản hồi P1
            build_fact_pattern("4", "giờ"),        # Xử lý P1
            build_fact_pattern("10", "phút"),      # Escalate P1
            build_fact_pattern("30", "phút"),      # Update P1
            build_fact_pattern("2", "giờ"),        # Phản hồi P2
            build_fact_pattern("1", "ngày"),       # Xử lý P2 & P3
            build_fact_pattern("90", "phút"),      # Escalate P2
            build_fact_pattern("5", "ngày"),       # Xử lý P3
            build_fact_pattern("3", "ngày"),       # Phản hồi P4
            build_fact_pattern("2-4", "tuần"),     # Xử lý P4
            build_fact_pattern("24", "giờ"),       # Incident report
        ],
        "hr_leave_policy": [
            build_fact_pattern("12", "ngày/năm"),  # Phép < 3 năm
            build_fact_pattern("15", "ngày/năm"),  # Phép 3-5 năm
            build_fact_pattern("18", "ngày/năm"),  # Phép > 5 năm
            build_fact_pattern("10", "ngày/năm"),  # Nghỉ ốm
            build_fact_pattern("3", "ngày"),       # Xin nghỉ trước 3 ngày / ốm 3 ngày
            build_fact_pattern("5", "ngày"),       # Chuyển phép năm sau
            build_fact_pattern("6", "tháng"),      # Nghỉ sinh con
            build_fact_pattern("1", "tiếng/ngày"), # Nghỉ nuôi con
            build_fact_pattern("12", "tháng"),     # Thời gian nuôi con
            build_fact_pattern("150", "%"),        # OT thường
            build_fact_pattern("200", "%"),        # OT cuối tuần
            build_fact_pattern("300", "%"),        # OT lễ
            build_fact_pattern("2", "ngày/tuần"),  # Remote work
        ],
        "it_helpdesk_faq": [
            build_fact_pattern("5", "lần"),        # Khóa tài khoản
            build_fact_pattern("5", "phút"),       # Gửi mật khẩu mới
            build_fact_pattern("90", "ngày"),      # Hạn mật khẩu
            build_fact_pattern("7", "ngày"),       # Nhắc đổi mật khẩu
            build_fact_pattern("30", "ngày"),      # Nhắc license
            build_fact_pattern("2", "thiết bị"),   # VPN
            build_fact_pattern("50", "GB"),        # Dung lượng mail
        ],
        "policy_refund_v4": [
            build_fact_pattern("7", "ngày"),       # Yêu cầu hoàn tiền
            build_fact_pattern("1", "ngày"),       # CS xem xét
            build_fact_pattern("3-5", "ngày"),     # Finance xử lý
            build_fact_pattern("100", "%"),        # Hoàn tiền gốc
            build_fact_pattern("110", "%"),        # Hoàn store credit
        ]
    }

    failed_facts = []

    # Quét tất cả rule trên dữ liệu chunk
    for doc_id, patterns in FACT_RULES.items():
        # Tìm tất cả text của doc_id này (nếu doc bị drop, E11 đã bắt lỗi rồi nên ta có thể bỏ qua an toàn)
        doc_chunks = [r.get("chunk_text") or "" for r in cleaned_rows if r.get("doc_id") == doc_id]
        if not doc_chunks:
            continue  
            
        # Gộp toàn bộ chunk của một doc lại để check. 
        # Điều này giúp bắt được fact ngay cả khi parser vô tình cắt chunk ngay giữa câu.
        full_text = " ".join(doc_chunks).lower()
        
        for pattern in patterns:
            # re.IGNORECASE giúp không phân biệt chữ hoa/chữ thường (Ngày = ngày)
            if not re.search(pattern, full_text, flags=re.IGNORECASE):
                failed_facts.append(f"Missing pattern '{pattern}' in doc: {doc_id}")

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
