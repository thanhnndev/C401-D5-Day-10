# Summary — Lab Day 10: Data Pipeline & Data Observability

**Nhóm:** C401-D5  
**Run ID:** `2026-04-15T07-08Z`  
**Ngày:** 2026-04-15

---

## Deliverables tổng quan

| # | File | Nội dung chính | Trạng thái |
|---|------|---------------|------------|
| 1 | [`docs/pipeline_architecture.md`](docs/pipeline_architecture.md) | Sơ đồ Mermaid, 5 thành phần (Ingest→Monitor), idempotency proof, liên hệ Day 09, 8 rủi ro | ✅ Hoàn thành |
| 2 | [`docs/data_contract.md`](docs/data_contract.md) | 3 nguồn dữ liệu, 5-field schema cleaned, 8 quarantine reason codes, versioning từ YAML contract | ✅ Hoàn thành |
| 3 | [`docs/runbook.md`](docs/runbook.md) | 5-section incident runbook (Symptom → Detection → Diagnosis → Mitigation → Prevention) | ✅ Hoàn thành |
| 4 | [`docs/quality_report.md`](docs/quality_report.md) | Quality report với run_id, before/after eval (1/4 → 4/4), inject evidence, freshness FAIL analysis | ✅ Hoàn thành |
| 5 | [`reports/group_report.md`](reports/group_report.md) | Báo cáo nhóm: metric_impact, before/after/inject retrieval, freshness monitoring, Day 09 connection | ✅ Hoàn thành |

---

## Kết quả pipeline

| Chỉ số | Giá trị |
|--------|---------|
| Raw records | 11 |
| Cleaned records | 7 |
| Quarantine records | 4 |
| Cleaning rules | 13 |
| Expectations (Pydantic V2) | 10 (7 halt + 3 warn) |
| Halt trên clean run | Không |
| Freshness | FAIL (age ≈ 119h > SLA 24h — dự kiến trên sample data) |

---

## Before / After retrieval

| Kịch bản | contains_expected | hits_forbidden | Tổng pass |
|----------|-------------------|----------------|-----------|
| **Before** (`origin.csv`) | 1/4 | 0/4 | 1/4 |
| **After** (`after.csv`) | 4/4 | 0/4 | 4/4 |
| **Inject** (`after_inject_bad.csv`) | 4/4 | 1/4 | 3/4 |

- Trước: retrieval collapse — tất cả query trả về `policy_refund_v4`.
- Sau: mỗi query đúng document (`q_p1_sla→sla_p1_2026`, `q_lockout→it_helpdesk_faq`, `q_leave_version→hr_leave_policy`).
- Inject bad: `q_refund_window` có `hits_forbidden=yes` — chứng minh quality gate hoạt động.

---

## Idempotency

Run `run-idempotent-1` chạy 2 lần: upsert by `chunk_id` (SHA-256) + prune stale IDs → collection size giữ nguyên = 6. Không duplicate vector.

---

## Điểm nổi bật (Merit/Distinction)

| Tiêu chí | Chứng cứ |
|----------|----------|
| Versioning HR không hard-code | Cutoff `2026-01-01` đọc từ `contracts/data_contract.yaml`, không hard-code trong Python |
| `q_leave_version` top1 match | `top1_doc_expected=yes` sau pipeline — HR leave policy 2026 đúng |
| Pydantic V2 validate | 10 expectations với model `CleanedRow` |
| Inject corruption Sprint 3 | `--no-refund-fix --skip-validate` → `hits_forbidden=yes` |
| 8 quarantine reason codes | Từ `unknown_doc_id` đến `suspicious_placeholders_detected` |

---

## Lệnh chạy nhanh

```bash
# Pipeline đầy đủ
python src/etl_pipeline.py run

# Kiểm tra freshness
python src/etl_pipeline.py freshness --manifest artifacts/manifests/manifest_2026-04-15T07-08Z.json

# Eval retrieval
python src/eval_retrieval.py --out artifacts/eval/before_after_eval.csv

# Inject corruption (Sprint 3)
python src/etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate
python src/eval_retrieval.py --out artifacts/eval/after_inject_bad.csv
```

---

## Hạn chế còn lại

1. Freshness chỉ đo publish boundary, chưa đo ingest boundary.
2. Eval dùng keyword matching, chưa có LLM-judge.
3. Chưa tích hợp Great Expectations (dùng Pydantic V2 thay thế).
4. Chưa có automated alerting (Slack/email) khi freshness FAIL.
5. `critical_facts_intact` FAIL trên idempotent run — cần tune threshold.
6. Contract fallback vào hard-coded values nếu không đọc được YAML.
