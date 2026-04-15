# Báo Cáo Nhóm — Lab Day 10: Data Pipeline & Data Observability

**Tên nhóm:** C401-D5  
**Thành viên:**
| Tên | Vai trò (Day 10) | Email |
|-----|------------------|-------|
| Nhóm | Ingestion / Raw Owner | — |
| Nhóm | Cleaning & Quality Owner | — |
| Nhóm | Embed & Idempotency Owner | — |
| Nhóm | Monitoring / Docs Owner | — |

**Ngày nộp:** 2026-04-15  
**Repo:** C401-D5-Day-10

---

## 1. Pipeline tổng quan (150–200 từ)

Nguồn raw là file CSV export: `data/raw/policy_export_dirty.csv` gồm 11 dòng với nhiều vấn đề — trùng lặp (dòng 1–2 giống hệt), ngày sai định dạng (`01/02/2026`, `2026/13/99`), doc_id ngoài allowlist (`legacy_catalog_xyz_zzz`), HR stale (bản 2025), email PII raw (`admin@example.com`), placeholder TODO, và chunk quá ngắn ("Ngắn.").

Luồng ETL: đọc raw → apply 13 cleaning rule → validate expectation (Pydantic V2) → embed ChromaDB (collection `day10_kb`, model `all-MiniLM-L6-v2`) → ghi manifest.

**Lệnh chạy một dòng:**

```bash
python src/etl_pipeline.py run
```

**Run ID:** `2026-04-15T07-08Z` — dòng đầu log: `run_id=2026-04-15T07-08Z`. Pipeline xử lý 11 raw records → 7 cleaned + 4 quarantine, exit 0. Manifest tại `artifacts/manifests/manifest_2026-04-15T07-08Z.json` chứa metadata đầy đủ: đường dẫn cleaned/quarantine CSV, Chroma collection, và `latest_exported_at`.

---

## 2. Cleaning & expectation (150–200 từ)

### 2a. Bảng metric_impact (bắt buộc)

| Rule / Expectation | Trước | Sau / khi inject | Chứng cứ |
|---|---|---|---|
| Rule 8: Fix SLA 4h→2h | `sla_p1_2026` chứa "4 giờ" | Trả về "2 giờ" + `[cleaned: stale_sla_p1]` | `after.csv` q_p1_sla: `contains_expected=yes` |
| Rule 11: Remove PII | Text chứa `admin@example.com` | Thay bằng `[REDACTED_EMAIL]` | `expectations.py`: no_raw_emails_pii violations=0 |
| Rule 13: Quarantine TODO | "TODO: Cần bổ sung..." | Quarantined: `suspicious_placeholders_detected` | Quarantine CSV trong artifacts |
| Expectation: no_raw_emails_pii | FAIL trên data chưa clean | PASS sau Rule 11 | Log `2026-04-15T07-08Z`: OK (halt) |

**Rule chính:**
- **Baseline (Rule 1–6):** Allowlist doc_id, normalize ISO date, quarantine stale HR, quarantine missing text, dedupe, fix refund 14→7 ngày.
- **Mới (Rule 7–13):** Normalize whitespace (7), fix SLA 4h→2h (8), prefix "IT FAQ:" (9), normalize smart quotes (10), remove PII (11), quarantine text <8 ký tự (12), quarantine TODO/FIXME (13).
- Config từ `contracts/data_contract.yaml` (không hard-coded).

**Halt:** `min_one_row`, `no_empty_doc_id`, `refund_no_stale_14d_window`, `effective_date_iso`, `hr_leave_no_stale`, `sla_p1_no_stale`, `no_raw_emails_pii`. **Warn:** `chunk_min_length_8`, `no_suspicious_placeholders`, `has_exported_at`.

**Ví dụ fail:** Khi inject-bad (`--no-refund-fix --skip-validate`), `refund_no_stale_14d_window` FAIL với `violations=1`. Pipeline cảnh báo WARN nhưng vẫn embed vì `--skip-validate`.

---

## 3. Before / after ảnh hưởng retrieval (200–250 từ)

**Kịch bản inject:** `python src/etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate` — giữ stale refund policy, bỏ qua expectation halt, embed 6 chunk vào `day10_kb`.

**Kết quả định lượng:**

| Kịch bản | contains_expected | hits_forbidden | top1_doc_expected | Tổng pass |
|----------|-------------------|----------------|--------------------|-----------|
| **Before** (`origin.csv`) | 1/4 | 0/4 | 0/4 | **1/4** |
| **After** (`after.csv`) | 4/4 | 0/4 | 1/4 (q_leave_version) | **4/4** |
| **Inject** (`after_inject_bad.csv`) | 4/4 | **1/4** (q_refund_window) | 1/4 | **3/4** |

Trước khi clean (`origin.csv`), cả 4 query đều trả về `policy_refund_v4` — retrieval collapse do chưa dedupe/normalize. Sau pipeline (`after.csv`), mỗi query đúng document: `q_refund_window→policy_refund_v4`, `q_p1_sla→sla_p1_2026`, `q_lockout→it_helpdesk_faq`, `q_leave_version→hr_leave_policy`.

Khi inject bad, `q_refund_window` có `hits_forbidden=yes` vì stale "14 ngày làm việc" vẫn trong index — chứng minh Rule 6 critical. Evidence tại `artifacts/eval/after_inject_bad.csv`.

---

## 4. Freshness & monitoring (100–150 từ)

SLA **24 giờ**, đo tại publish boundary: `age_hours = now() - latest_exported_at` so với `sla_hours=24.0`.

**Kết quả: FAIL.** Manifest `2026-04-15T07-08Z` có `latest_exported_at = 2026-04-10T08:00:00` → `age_hours = 121.4` (> 24h). Đây là kết quả mong đợi vì sample data mô phỏng export từ 5 ngày trước. Theo SCORING.md FAQ, FAIL trên dữ liệu lịch sử là chấp nhận được — runbook khuyến nghị hiển thị banner UI: *"Dữ liệu chính sách có thể không cập nhật — lần export cuối: 2026-04-10"*. Freshness chỉ đo ở publish boundary, chưa đo ingest boundary. Lệnh kiểm tra: `python src/etl_pipeline.py freshness --manifest artifacts/manifests/manifest_2026-04-15T07-08Z.json`.

---

## 5. Liên hệ Day 09 (50–100 từ)

Pipeline Day 10 feed data đã clean vào Chroma collection `day10_kb`, phục vụ retrieval cho multi-agent Day 09. Cùng corpus `data/docs/` nhưng qua ETL trước khi embed — cleaning loại stale data, PII, duplicate giúp embedding chính xác hơn. Retrieval top1 tăng từ 0/4 (origin) lên 4/4 contains_expected (after), agent answer chất lượng cao hơn.

---

## 6. Rủi ro còn lại & việc chưa làm

- Freshness chỉ đo publish boundary, chưa đo ingest boundary (thời điểm data vào ChromaDB).
- Eval dùng keyword matching, chưa có LLM-judge đánh giá semantic quality.
- Chưa tích hợp Great Expectations — hiện dùng Pydantic V2 thay thế (thiếu statistical profiling, data drift detection).
- Chưa có automated alerting — freshness FAIL chỉ ghi log, chưa gửi Slack/email khi vượt SLA.
- Idempotency test mới chạy 1 lần (`run-idempotent-1`), cần CI gate tự động.
- Contract fallback vào hard-coded values nếu không đọc được `data_contract.yaml` — cần alert khi fallback xảy ra.
