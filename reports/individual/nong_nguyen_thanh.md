# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Data Observability

**Họ và tên:** Nông Nguyễn Thành  
**Vai trò:** Monitoring / Docs Owner — Quản lý repo, tài liệu hóa pipeline, hỗ trợ team  
**Ngày nộp:** 15/04/2026  
**Độ dài:** ~500 từ

---

## 1. Phụ trách

Tôi đảm nhận vai trò **Monitoring / Docs Owner** và **quản lý source code repository** cho nhóm C401-D5-Day-10. Cụ thể:

**Tài liệu (Docs):**
- `docs/pipeline_architecture.md`: Sơ đồ Mermaid mô tả luồng ETL (ingest → clean → validate → embed → monitor), ranh giới trách nhiệm từng thành phần, cơ chế idempotency (upsert by chunk_id + prune stale IDs), và liên hệ với Day 09 multi-agent.
- `docs/data_contract.md`: Source map (2 nguồn chính: raw CSV export + canonical `data/docs/*.txt`), schema cleaned 5 cột (`chunk_id`, `doc_id`, `chunk_text`, `effective_date`, `exported_at`), quy tắc quarantine vs drop, versioning policy, và ownership mapping.
- `docs/runbook.md`: 5 mục Symptom → Detection → Diagnosis → PASS/WARN/FAIL → Mitigation → Prevention, bao gồm lệnh vận hành tối thiểu và liên hệ Day 11 guardrail concepts.
- `docs/quality_report.md`: Hoàn thiện từ template, điền số liệu run_id `2026-04-15T07-08Z`, bảng before/after retrieval, freshness analysis, và corruption inject evidence.

**Quản lý repo:**
- Cấu trúc thư mục theo README.md chuẩn, đảm bảo các file `.py`, `contracts/data_contract.yaml`, artifacts, và reports được tổ chức đúng quy ước.
- Hỗ trợ team resolve conflict, review cấu trúc file trước commit, đảm bảo consistency giữa code và tài liệu.

**Hỗ trợ team:**
- Check và hỗ trợ các vấn đề lặt vặt: setup môi trường (`pip install -r requirements.txt`), debug lỗi import, kiểm tra artifact trước khi nộp.
- Học hỏi từ các thành viên khác về cleaning rules (Hồ Sỹ Minh Hà), embed idempotency, và grading JSONL.

**Bằng chứng (commit history):**

| Commit | File thay đổi | Mô tả |
|--------|---------------|-------|
| `f29c75f` | `README.md` | Refactor cấu trúc thư mục, di chuyển code vào `src/`, cập nhật hướng dẫn chạy pipeline |
| `947fbc7` | `docs/pipeline_architecture.md` (+95 dòng), `docs/data_contract.md` (+78), `docs/runbook.md` (+71), `docs/quality_report.md` (mới 121 dòng), `reports/group_report.md` | Điền bằng chứng artifact thực tế: sơ đồ Mermaid, schema 5 cột, 8 quarantine reason codes, before/after eval (1/4→4/4), inject evidence, freshness FAIL analysis |
| `4a6df02` | `docs/data_contract.md` (+29), `docs/runbook.md` (+4) | Sync contract YAML → docs: owner_team, quarantine_policy (8 rules), ownership mapping (4 roles), xóa TODO placeholders |
| `f2e7996` | `reports/individual/nong_nguyen_thanh.md` (+97), `reports/individual/template.md` (+41) | Viết báo cáo cá nhân và template tham khảo |

Nội dung docs khớp với code thực tế trong `src/etl_pipeline.py`, `src/transform/cleaning_rules.py`, `src/quality/expectations.py`.

---

## 2. Quyết định kỹ thuật

**Quản lý versioning qua data contract thay vì hard-code:**

Tôi đề xuất và thực hiện việc đọc cutoff HR `2026-01-01` từ `contracts/data_contract.yaml` (`policy_versioning.hr_leave_min_effective_date`) thay vì hard-code trong Python. Cleaning rule 3 trong `src/transform/cleaning_rules.py` gọi `_load_contract_config()` để lấy giá trị này.

**Lý do:**
1. **Distinction criterion (d):** SCORING.md yêu cầu rule versioning không hard-code ngày cố định. Việc đọc từ contract giúp pipeline linh hoạt khi policy thay đổi — chỉ cần sửa YAML, không cần touch code.
2. **Separation of concerns:** Business logic (cutoff date) tách khỏi implementation (Python). Monitoring Owner và Cleaning Owner có thể thảo luận threshold mà không cần modify code.
3. **Audit trail:** Contract YAML là source of truth cho cả team, dễ review trong pull request.

**Trade-off:** Nếu contract file không đọc được, code fallback vào hard-coded values (`cleaning_rules.py:30-33`). Đây là safety net nhưng cần alert khi fallback xảy ra — tôi đã ghi nhận rủi ro này trong `docs/pipeline_architecture.md` (Risk #8).

---

## 3. Sự cố / anomaly

**Sự cố nhóm — mismatch giữa eval CSV và grading JSONL:**

Khi chạy `grading_run.py` sau pipeline chuẩn, nhóm phát hiện `grading_run.jsonl` chỉ có 2 dòng thay vì 3 dòng yêu cầu (`gq_d10_01` … `gq_d10_03`). Nguyên nhân: file `data/grading_questions.json` mới được public sau 17:00 (theo timeline), nhưng team đã chạy eval trước đó với `data/test_questions.json` (4 câu, không phải grading questions).

**Fix:**
1. Kiểm tra lại `data/grading_questions.json` sau 17:00 — xác nhận có 3 câu đúng format.
2. Chạy lại: `python src/grading_run.py --out artifacts/eval/grading_run.jsonl`.
3. Dùng `python src/instructor_quick_check.py --grading artifacts/eval/grading_run.jsonl` để validate format trước khi nộp.

**Evidence:** File `grading_run.jsonl` cuối cùng có đúng 3 dòng JSON hợp lệ, mỗi dòng chứa `contains_expected`, `hits_forbidden`, và `top1_doc_expected` theo yêu cầu SCORING.md mục 4.

---

## 4. Before/after

**Log pipeline run (`artifacts/logs/run_2026-04-15T07-08Z.log`):**
```
run_id=2026-04-15T07-08Z
raw_records=11
cleaned_records=7
quarantine_records=4
expectation[min_one_row] OK (halt)
expectation[refund_no_stale_14d_window] OK (halt)
expectation[hr_leave_no_stale] OK (halt)
freshness_check=FAIL {"latest_exported_at": "2026-04-10T08:00:00", "age_hours": 121.4, "sla_hours": 24.0}
PIPELINE_OK
```

**Eval CSV before/after (`artifacts/eval/origin.csv` vs `artifacts/eval/after.csv`):**

| Scenario | contains_expected | hits_forbidden | Tổng pass |
|----------|-------------------|----------------|-----------|
| Before (`origin.csv`) | 1/4 | 0/4 | **1/4** |
| After (`after.csv`) | 4/4 | 0/4 | **4/4** |
| Inject bad (`after_inject_bad.csv`) | 4/4 | **1/4** (q_refund_window) | **3/4** |

Trước khi clean, retrieval collapse — mọi query đều trả về `policy_refund_v4`. Sau pipeline, mỗi query đúng document: `q_refund_window→policy_refund_v4`, `q_p1_sla→sla_p1_2026`, `q_lockout→it_helpdesk_faq`, `q_leave_version→hr_leave_policy`.

---

## 5. Cải tiến thêm 2 giờ

Nếu có thêm 2 giờ, tôi sẽ:

1. **Tích hợp Great Expectations hoặc pydantic model validate trên schema cleaned** (Distinction criterion a) — hiện tại chỉ dùng Pydantic V2 trong `expectations.py`, chưa có statistical profiling hoặc data drift detection.
2. **Đo freshness ở 2 boundary** (ingest + publish) — hiện tại chỉ đo publish boundary (`exported_at` trong manifest). Thêm metric "time-to-ingest" để phân biệt stale source vs stale pipeline (Distinction criterion b).
3. **Học sâu hơn về ChromaDB idempotency** — thay vì chỉ document lại, sẽ thực sự debug và viết test cho edge case: rerun pipeline với raw data thay đổi (thêm/xóa record) để chứng minh prune logic hoạt động chính xác.

Thay vì vibe-coding nhiều, tôi ưu tiên hiểu sâu các khái niệm data observability mà các thành viên khác trong nhóm đã implement — đặc biệt là cleaning rules và expectation suite.
