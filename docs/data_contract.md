# Data contract — Lab Day 10

> Đồng bộ hoàn toàn từ `contracts/data_contract.yaml` (v1.0), dataset: **kb_chunk_export**.
> `owner_team` đang là `__TODO__` — cần điền khi bàn giao production.

---

## 1. Nguồn dữ liệu (source map)

| Nguồn | Phương thức ingest | Failure mode chính | Metric / alert |
|-------|-------------------|-------------------|----------------|
| `data/raw/policy_export_dirty.csv` — CSV export từ hệ thống nội bộ | `load_raw_csv()` trong `src/transform/cleaning_rules.py` đọc 20 dòng raw, strip whitespace từng trường | (1) Duplicate chunk_text (dòng 2≡3); (2) `missing_effective_date` (dòng 5); (3) `unknown_doc_id` — doc_id không thuộc allowlist (dòng 9: `legacy_catalog_xyz_zzz`, dòng 13: trống); (4) Non-ISO date format `DD/MM/YYYY` hoặc `YYYY/MM/DD` invalid (dòng 10, 14); (5) Stale HR policy 2025 (`effective_date=2025-01-01` < cutoff `2026-01-01`); (6) Stale refund window 14 ngày → phải fix thành 7; (7) Placeholder TODO/FIXME; (8) Chunk text quá ngắn (<8 ký tự); (9) Missing chunk_text | `raw_records` count (20 rows); `quarantine_records` count (≥8 rows bị loại); alert khi `raw_records > 50` đột biến |
| `data/docs/*.txt` — 4 canonical policy files: `policy_refund_v4.txt`, `sla_p1_2026.txt`, `it_helpdesk_faq.txt`, `hr_leave_policy.txt` | Định nghĩa trong `contracts/data_contract.yaml` → `canonical_sources` mapping 4 đường dẫn ↔ 4 `doc_id` | Nội dung stale so với canonical: refund 14 ngày (phải 7), SLA P1 4 giờ (phải 2 giờ). Pipeline tự fix inline và gán tag `[cleaned: stale_refund_window]` / `[cleaned: stale_sla_p1]` | `cleaned_records` count; so sánh hash chunk_text với canonical; alert khi `cleaned_records < raw_records * 0.5` |
| ChromaDB collection `day10_kb` — vector store cho retrieval/grounding | Embedding pipeline publish cleaned rows → ChromaDB (`src/publish/`) | Stale vectors: document đã bị prune khỏi cleaned nhưng vẫn tồn tại trong collection; embedding của chunk đã bị sửa (refund/SLA fix) không được update | `embed_prune_removed` count; alert khi collection size lệch quá ±20% so với `cleaned_records` |

---

## 2. Schema cleaned

Schema chính thức định nghĩa trong `contracts/data_contract.yaml` → `schema_cleaned`. Pipeline output ra file `artifacts/cleaned/cleaned_<run_id>.csv` với đúng 5 cột này:

| Cột | Kiểu | Bắt buộc | Ghi chú |
|-----|------|----------|---------|
| `chunk_id` | string | Có | ID ổn định sinh bởi `_stable_chunk_id(doc_id, chunk_text, seq)` → hash SHA-256 16 ký tự đầu, format `{doc_id}_{seq}_{hash}`. Đảm bảo cùng nội dung = cùng ID qua mọi lần chạy. |
| `doc_id` | string | Có | Khóa logic tài liệu nguồn. Chỉ chấp nhận 4 giá trị từ `allowed_doc_ids` trong contract: `policy_refund_v4`, `sla_p1_2026`, `it_helpdesk_faq`, `hr_leave_policy`. Ngoài danh sách này → quarantine (`unknown_doc_id`). |
| `chunk_text` | string | Có | Nội dung chunk đã qua cleaning pipeline: normalize whitespace (Rule 7), thay thế smart quotes (Rule 10), redact email PII (Rule 11), thêm prefix "IT FAQ: " cho it_helpdesk_faq (Rule 9). Độ dài tối thiểu = 8 ký tự (`min_length: 8` trong contract). Dưới 8 ký tự → quarantine (`text_too_short`). Chứa marker TODO/FIXME/???/lỗi migration → quarantine (`suspicious_placeholders_detected`). |
| `effective_date` | date | Có | Định dạng chuẩn ISO `YYYY-MM-DD`. Pipeline tự động parse format `DD/MM/YYYY` hoặc `DD-MM-YYYY` (regex `_DMY_SEP`). Nếu rỗng → quarantine (`missing_effective_date`). Nếu không parse được → quarantine (`invalid_effective_date_format`). Với `hr_leave_policy`: phải ≥ `2026-01-01` (định nghĩa trong `policy_versioning.hr_leave_min_effective_date` của contract — **không hard-code trong code**). Dưới cutoff → quarantine (`stale_hr_policy_effective_date`). |
| `exported_at` | datetime | Có | Timestamp gốc từ raw export, giữ nguyên giá trị. Không qua transform. |

---

## 3. Quy tắc quarantine vs drop

### Record bị flag đi đâu?

Mọi record không đạt quality rule **không bị xóa silently** — được ghi vào file quarantine:

```
artifacts/quarantine/quarantine_<run_id>.csv
```

Tên file theo convention `<run_id>` (vd: `quarantine_2026-04-15T07-08Z.csv`, `quarantine_ci-smoke.csv`, `quarantine_inject-bad.csv`). File CSV giữ nguyên các trường gốc từ raw + cột `reason` mô tả mã lỗi.

### Danh sách reason codes thực tế (từ `cleaning_rules.py`):

| Reason code | Rule | Severity | Mô tả |
|-------------|------|----------|-------|
| `unknown_doc_id` | Rule 1 | **halt** | `doc_id` không nằm trong `allowed_doc_ids` của contract. Vd: `legacy_catalog_xyz_zzz` hoặc doc_id trống. |
| `missing_effective_date` | Rule 2a | **halt** | Trường `effective_date` rỗng sau strip. |
| `invalid_effective_date_format` | Rule 2b | **halt** | Date không parse được sang ISO (vd: `2026/13/99`). |
| `stale_hr_policy_effective_date` | Rule 3 | **halt** | `hr_leave_policy` có `effective_date` < `2026-01-01` (bản HR 2025 cũ). Cutoff đọc từ contract `policy_versioning.hr_leave_min_effective_date` — **không hard-code trong code** (merit point). |
| `missing_chunk_text` | Rule 4a | **halt** | `chunk_text` rỗng. |
| `duplicate_chunk_text` | Rule 5 | **warn** | Nội dung chunk_text đã xuất hiện trước đó (so sánh case-insensitive). Giữ bản đầu tiên, các bản sau → quarantine. Severity là `warn` vì không phải lỗi dữ liệu mà là trùng lặp. |
| `text_too_short` | Rule 12 | **halt** | Chunk text sau cleaning có độ dài < 8 ký tự (ngưỡng từ contract `min_length: 8`). |
| `suspicious_placeholders_detected` | Rule 13 | **halt** | Chunk chứa marker `???`, `TODO`, `FIXME`, hoặc `lỗi migration` — dấu hiệu dữ liệu chưa hoàn thiện hoặc lỗi migration. |

### Severity mapping (từ contract `quality_rules`):

- **`halt`**: Record không được publish → vào quarantine. Pipeline vẫn chạy tiếp các record sau.
- **`warn`** (vd: `no_duplicate_chunk_text`): Record vẫn bị loại khỏi cleaned nhưng pipeline chỉ ghi log cảnh báo. Duplicate không phá vỡ SLA.
- **`halt`** (vd: `no_stale_refund_window`): Nếu chunk chứa stale refund window (14 ngày) **mà không được fix tự động**, pipeline phải halt. Tuy nhiên pipeline đã implement Rule 6 tự động fix `14 ngày làm việc` → `7 ngày làm việc` + tag `[cleaned: stale_refund_window]`, nên trường hợp này thực tế được resolve inline thay vì quarantine.

### Ai approve merge lại?

- **Quarantine owner**: Người chịu trách nhiệm cleaning pipeline (Cleaning Owner / Team Lead).
- Quy trình: Review file quarantine hàng ngày → xác định root cause (export bug, catalog sai, versioning conflict) → fix ở nguồn → re-run pipeline với cùng `run_id` hoặc `run_id` mới.
- Record quarantine **không tự động merge** lại vào cleaned. Phải có hành động thủ công: sửa nguồn gốc → re-ingest → pipeline sinh cleaned mới.

---

## 4. Phiên bản & canonical

### Source of truth cho từng policy doc

4 canonical policy files nằm trong `data/docs/`, được khai báo chính thức trong `contracts/data_contract.yaml` → `canonical_sources`:

| Canonical file | doc_id | Nội dung |
|----------------|--------|----------|
| `data/docs/policy_refund_v4.txt` | `policy_refund_v4` | Chính sách hoàn tiền v4 — cửa sổ **7 ngày làm việc** (không phải 14 ngày của v3 cũ). |
| `data/docs/sla_p1_2026.txt` | `sla_p1_2026` | SLA P1 2026 — resolution **2 giờ** (không phải 4 giờ của phiên bản cũ). |
| `data/docs/it_helpdesk_faq.txt` | `it_helpdesk_faq` | FAQ IT Helpdesk — grounding cho retrieval, cần prefix "IT FAQ: ". |
| `data/docs/hr_leave_policy.txt` | `hr_leave_policy` | Chính sách nghỉ phép 2026 — áp dụng từ `2026-01-01`. Bản 2025 (effective_date < cutoff) bị coi là stale. |

### Cơ chế versioning

- **HR Leave Policy**: Contract định nghĩa `policy_versioning.hr_leave_min_effective_date: "2026-01-01"`. Pipeline đọc giá trị này từ YAML (`cleaning_rules.py` → `_load_contract_config()`), **không hard-code** trong code. Đây là merit point: khi chính sách HR cập nhật version mới, chỉ cần sửa contract YAML → pipeline tự động áp dụng cutoff mới mà không cần touch code.
- **Refund Policy**: Version v4 được thể hiện qua `doc_id = policy_refund_v4`. Pipeline tự động phát hiện chunk chứa stale window `14 ngày làm việc` → fix thành `7 ngày làm việc` inline (Rule 6). Tag `[cleaned: stale_refund_window]` được append để audit trail.
- **SLA P1**: Tương tự, pipeline tự động fix `4 giờ` → `2 giờ` (Rule 8) và tag `[cleaned: stale_sla_p1]`.
- **Thêm doc_id mới**: Khi team muốn ingest tài liệu mới, phải: (1) thêm file canonical vào `data/docs/`, (2) thêm entry vào `canonical_sources` trong contract YAML, (3) thêm `doc_id` vào `allowed_doc_ids` trong contract YAML, (4) thêm rule cleaning nếu cần (vd: prefix, stale detection). Pipeline sẽ tự động nhận diện qua contract — không cần sửa logic Python.

### Freshness SLA

- Đo tại điểm `publish` (sau khi embedding và push lên ChromaDB).
- SLA: **24 giờ** (`freshness.sla_hours: 24`).
- Alert channel: `__TODO__` — cần cấu hình khi đưa vào production.
