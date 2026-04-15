# Quality report — Lab Day 10 (nhóm)

**run_id:** `2026-04-15T07-08Z`
**Ngày:** 2026-04-15

---

## 1. Tóm tắt số liệu

| Chỉ số | Trước | Sau | Ghi chú |
|--------|-------|-----|---------|
| raw_records | 11 | — | Từ `policy_export_dirty.csv` |
| cleaned_records | — | 7 | Records vượt qua validation |
| quarantine_records | — | 4 | Records bị loại (stale, PII, short chunk) |
| Expectation halt? | — | No | Clean run: tất cả halt expectations đều OK |

**Reference run_id:** `2026-04-15T07-08Z` — manifest tại `artifacts/manifests/manifest_2026-04-15T07-08Z.json`

**Idempotent run** (`run-idempotent-1`): raw=10, cleaned=6, quarantine=4. Tất cả halt expectations OK trừ `critical_facts_intact` FAIL (dự kiến — đây là kiểm tra rộng trên toàn bộ doc, không phải halt blocker). Log chi tiết: `artifacts/logs/run_run-idempotent-1.log`.

**10+ expectations** (Pydantic V2) từ `src/quality/expectations.py`:
- **Halt:** `min_one_row`, `no_empty_doc_id`, `refund_no_stale_14d_window`, `effective_date_iso`, `hr_leave_no_stale`, `sla_p1_no_stale`, `no_raw_emails_pii`
- **Warn:** `chunk_min_length_8`, `no_suspicious_placeholders`, `has_exported_at`

---

## 2. Before / after retrieval (bắt buộc)

Nguồn: `artifacts/eval/origin.csv` (trước) và `artifacts/eval/after.csv` (sau).

### Câu hỏi then chốt: refund window (`q_refund_window`)

**Trước (`origin.csv`):**
```
q_refund_window | top1=policy_refund_v4 | contains_expected=yes | hits_forbidden=no
```
→ Đây là trường hợp đặc biệt: `q_refund_window` vẫn có `contains_expected=yes` ngay cả trước khi fix vì policy_refund_v4 là document mặc định duy nhất trong index gốc. Nhưng các câu hỏi KHÁC hoàn toàn sai.

### Các câu hỏi sai nghiêm trọng trước khi fix

| question_id | Trước: top1_doc_id | Trước: contains_expected | Trước: hits_forbidden |
|-------------|-------------------|-------------------------|----------------------|
| `q_p1_sla` | `policy_refund_v4` | **no** | no |
| `q_lockout` | `policy_refund_v4` | **no** | no |
| `q_leave_version` | `policy_refund_v4` | **no** | no |

→ **Chỉ 1/4 câu hỏi pass `contains_expected`** (top1 luôn là `policy_refund_v4` — sai hoàn toàn cho SLA, lockout, leave).

### Sau khi fix (`after.csv`)

| question_id | Sau: top1_doc_id | Sau: contains_expected | Sau: hits_forbidden | top1_doc_expected |
|-------------|-----------------|----------------------|-------------------|-------------------|
| `q_refund_window` | `policy_refund_v4` | yes | no | — |
| `q_p1_sla` | `sla_p1_2026` | **yes** | no | — |
| `q_lockout` | `it_helpdesk_faq` | **yes** | no | — |
| `q_leave_version` | `hr_leave_policy` | **yes** | no | **yes** |

→ **4/4 câu hỏi pass `contains_expected=yes`**, `hits_forbidden=no` cho tất cả.

### Merit: versioning HR — `q_leave_version`

**Trước:** `contains_expected=no`, `top1_doc_expected=no` (trả về `policy_refund_v4` với preview về refund 7 ngày — hoàn toàn không liên quan đến nghỉ phép).

**Sau:** `contains_expected=yes`, `hits_forbidden=no`, **`top1_doc_expected=yes`**. Top1 là `hr_leave_policy` với preview: _"Nhân viên dưới 3 năm kinh nghiệm được 12 ngày phép năm theo chính sách 2026."_ — chính xác với câu hỏi về chính sách nghỉ phép 2026.

---

## 3. Freshness & monitor

**Kết quả freshness check:** **FAIL**

**Giải thích:**
- SLA freshness: **24 giờ** — đo tại thời điểm "publish" (trường `exported_at` trong raw data).
- Dữ liệu mẫu có `latest_exported_at = 2026-04-10T08:00:00` (từ manifest).
- Run đo tại `2026-04-15T07:09:25` → chênh lệch **~5 ngày** → vượt SLA 24h → **FAIL là đúng**.

**Đây là hành vi dự kiến** theo FAQ trong `SCORING.md`: _"CSV mẫu có `exported_at` cũ — FAIL là hợp lý."_ Freshness monitor hoạt động chính xác: nó phát hiện dữ liệu đã stale và report FAIL. Trong môi trường production, điều này sẽ trigger alert để đội data engineering kiểm tra pipeline ingest.

**Giới hạn hiện tại:** Freshness chỉ đo tại boundary "publish" (`exported_at` trong source CSV), không đo tại thời điểm ingest vào pipeline. Nếu source system export dữ liệu cũ nhưng pipeline ingest ngay, freshness vẫn FAIL — đây là design choice intentional để đảm bảo end-to-end data freshness.

---

## 4. Corruption inject (Sprint 3)

**Mục tiêu:** Chứng minh hệ thống expectations + eval có thể phát hiện dữ liệu bị hỏng (stale/corrupted).

**Command inject:**
```bash
python src/etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate
```

**Cách làm hỏng:**
- `--no-refund-fix`: Bỏ qua rule sửa stale refund window (giữ nguyên dữ liệu 7 ngày thay vì 14 ngày)
- `--skip-validate`: Bỏ qua validation step để cho phép dữ liệu hỏng đi vào index

**Kết quả eval** (`artifacts/eval/after_inject_bad.csv`):

| question_id | top1_doc_id | contains_expected | hits_forbidden |
|-------------|-------------|-------------------|----------------|
| `q_refund_window` | `policy_refund_v4` | yes | **yes** ⚠️ |
| `q_p1_sla` | `sla_p1_2026` | yes | no |
| `q_lockout` | `it_helpdesk_faq` | yes | no |
| `q_leave_version` | `hr_leave_policy` | yes | no |

**Phát hiện:** `q_refund_window` có **`hits_forbidden=yes`** — chứng tỏ eval đã phát hiện document trả về chứa thông tin stale (7 ngày thay vì 14 ngày đúng). Đây là bằng chứng hệ thống quality gate hoạt động: khi dữ liệu bị inject corruption, eval flag `hits_forbidden` ngay lập tức.

---

## 5. Hạn chế & việc chưa làm

1. **Freshness chỉ đo tại publish boundary** — Không đo tại thời điểm ingest vào pipeline. Nếu source system export dữ liệu cũ nhưng pipeline chạy ngay, freshness vẫn FAIL. Cần thêm metric "time-to-ingest" để phân biệt stale source vs stale pipeline.

2. **Không tích hợp Great Expectations** — Hệ thống dùng Pydantic V2 cho validation thay vì Great Expectations framework. Pydantic đủ cho use case hiện tại nhưng thiếu features như data profiling, expectation suites reuse, và data docs auto-generation.

3. **Eval là keyword-based, không phải LLM-judge** — Retrieval evaluation dựa trên keyword matching (`contains_expected`, `hits_forbidden`) thay vì LLM-judge semantic similarity. Điều này có thể bỏ sót trường hợp document đúng nhưng dùng từ ngữ khác với expected patterns.

4. **Không có automated alerting** — Khi freshness FAIL hoặc expectation halt, hiện tại chỉ log ra console và file. Chưa có integration với Slack, email, hoặc PagerDuty để notify đội on-call.

5. **`critical_facts_intact` FAIL trên idempotent run** — Expectation này kiểm tra sự hiện diện của các pattern quan trọng trong toàn bộ document (SLA times, leave days, v.v.). FAIL trên run idempotent cho thấy một số document trong cleaned data bị mất thông tin do cleaning rules quá aggressive. Cần tune threshold hoặc thêm rule bảo vệ critical facts.

6. **13 cleaning rules nhưng không có rule priority** — Các rule chạy theo thứ tự hardcoded trong `src/transform/cleaning_rules.py`. Nếu có conflict giữa rules (ví dụ: PII removal vs special char normalize), không có cơ chế resolve priority. Cần thêm rule ordering configuration.
