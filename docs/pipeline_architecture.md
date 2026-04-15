# Kiến trúc pipeline — Lab Day 10

**Nhóm:** C401-D5  
**Cập nhật:** 2026-04-15T07:08Z

---

## 1. Sơ đồ luồng

```mermaid
flowchart LR
    A["raw export\n(policy_export_dirty.csv)\nraw_records=11"] -->|"load_raw_csv()|B["Transform\nclean_rows()\n13 rules"]
    B -->|"cleaned=7|C["Quality\nrun_expectations()\n10 expectations\nPydantic V2"]
    B -->|"quarantine=4|Q["Quarantine\nartifacts/quarantine/\nquarantine_YYYY-MM-DD.csv"]
    C -->|"halt=false|D["Embed\ncmd_embed_internal()\nChromaDB PersistentClient\ncollection=day10_kb\nmodel=all-MiniLM-L6-v2"]
    D -->|"upsert by chunk_id\nprune stale IDs|E["Serving\nDay 08/09 retrieval\neval_retrieval.py\ngrading_run.py"]
    D -->|"write manifest|F["Manifest\nartifacts/manifests/\nmanifest_YYYY-MM-DD.json"]
    F -->|"check_manifest_freshness()\nSLA=24h|G["Monitor\nfreshness_check.py\nPASS/WARN/FAIL"]

    subgraph Logging
    L["run_id logged at every step\nartifacts/logs/run_YYYY-MM-DD.log"]
    end
    A -.-> L
    B -.-> L
    C -.-> L
    D -.-> L
    G -.-> L
```

**Điểm đoFreshness:** `check_manifest_freshness()` đọc trường `latest_exported_at` từ manifest, so sánh với thời điểm hiện tại và ngưỡng SLA (mặc định 24h từ `FRESHNESS_SLA_HOURS`). Kết quả trả về PASS/WARN/FAIL kèm `age_hours`.

**Ghi nhận run_id:** Mỗi lần chạy pipeline sinh ra `run_id` (UTC timestamp hoặc truyền qua `--run-id`), được ghi vào:
- Log file: `artifacts/logs/run_{run_id}.log`
- Manifest: `artifacts/manifests/manifest_{run_id}.json`
- Metadata vector: mỗi document trong Chroma mang trường `run_id`

**File quarantine:** Nằm tại `artifacts/quarantine/quarantine_{run_id}.csv`, chứa các bản ghi bị loại kèm `reason` (unknown_doc_id, stale_hr_policy_effective_date, duplicate_chunk_text, suspicious_placeholders_detected, text_too_short, …).

**Kết quả run thực tế (2026-04-15T07-08Z):** raw=11 → cleaned=7 → quarantine=4, tất cả 10 expectations PASS, freshness=PASS.

---

## 2. Ranh giới trách nhiệm

| Thành phần | Input | Output | Owner (file) |
|------------|-------|--------|--------------|
| **Ingest** | `data/raw/policy_export_dirty.csv` (CSV từ DB/API export) | List[Dict] raw rows (11 records) | `src/etl_pipeline.py::cmd_run()` → `load_raw_csv()` |
| **Transform** | Raw rows + `contracts/data_contract.yaml` (allowlist, HR cutoff) | `cleaned` (7 rows) + `quarantine` (4 rows) → CSV trong `artifacts/cleaned/` và `artifacts/quarantine/` | `src/transform/cleaning_rules.py::clean_rows()` — 13 rules: allowlist doc_id, normalize dates (DD/MM/YYYY→YYYY-MM-DD), quarantine stale HR (<2026-01-01), fix refund 14→7 ngày, normalize whitespace, fix SLA 4h→2h, IT FAQ prefix, normalize smart quotes, remove PII emails, quarantine short text (<8 ký tự), quarantine placeholders (TODO/FIXME/???), dedupe chunk_text |
| **Quality** | Cleaned rows (List[Dict]) | Tuple[List[ExpectationResult], should_halt] — 10 expectations với severity halt/warn | `src/quality/expectations.py::run_expectations()` — Pydantic V2 model `CleanedRow` validate schema + business rules: min_one_row, no_empty_doc_id, refund_no_stale_14d, effective_date_iso, hr_leave_no_stale_10d, sla_p1_no_stale_4h, no_raw_emails_pii, chunk_min_length_8, no_suspicious_placeholders, has_exported_at |
| **Embed** | Cleaned CSV + env config (CHROMA_DB_PATH, CHROMA_COLLECTION, EMBEDDING_MODEL) | ChromaDB collection `day10_kb` tại `./chroma_db`, mỗi vector mang metadata `{doc_id, effective_date, run_id}` | `src/etl_pipeline.py::cmd_embed_internal()` — ChromaDB PersistentClient, SentenceTransformerEmbeddingFunction (all-MiniLM-L6-v2), upsert idempotent + prune stale |
| **Monitor** | Manifest JSON từ bước Embed | Status PASS/WARN/FAIL + detail {latest_exported_at, age_hours, sla_hours} | `src/monitoring/freshness_check.py::check_manifest_freshness()` — gọi từ `etl_pipeline.py` sau khi ghi manifest, hoặc standalone qua `python etl_pipeline.py freshness --manifest <path>` |

---

## 3. Idempotency & rerun

**Strategy: Upsert theo `chunk_id` + Prune stale IDs**

Pipeline đảm bảo idempotent qua cơ chế 2 lớp trong `cmd_embed_internal()` (`src/etl_pipeline.py:131-177`):

1. **Upsert by chunk_id:** `chunk_id` được sinh ổn định từ `_stable_chunk_id(doc_id, chunk_text, seq)` → SHA-256 hash 16 ký tự đầu (`{doc_id}_{seq}_{h[:16]}`). ChromaDB `col.upsert(ids=ids, ...)` sẽ ghi đè vector cũ nếu `chunk_id` đã tồn tại, không tạo duplicate.

2. **Prune stale IDs (snapshot publish):** Trước khi upsert, pipeline lấy toàn bộ `prev_ids` đang có trong collection, tính `drop = sorted(prev_ids - set(current_ids))`, rồi `col.delete(ids=drop)`. Điều này đảm bảo:
   - Document không còn trong cleaned run mới → bị xóa khỏi index
   - Collection luôn là snapshot chính xác của run gần nhất
   - Log ghi nhận: `embed_prune_removed=N` (số vector bị xóa)

**Chứng minh rerun không duplicate:**

| Lần chạy | run_id | raw | cleaned | quarantine | Embed behavior |
|----------|--------|-----|---------|------------|----------------|
| 1 | `run-idempotent-1` | 10 | 6 | 4 | Upsert 6 vector, collection size = 6 |
| 2 | `run-idempotent-1` (rerun) | 10 | 6 | 4 | prev_ids=6, current_ids=6 → drop=0 → upsert 6 (overwrite) → collection size vẫn = 6 |

Log `artifacts/logs/run_run-idempotent-1.log` xác nhận cả 2 lần chạy đều sinh ra cùng 6 cleaned records, không có duplicate vector trong `day10_kb`. Nếu raw data thay đổi (ví dụ: 1 record mới hợp lệ), run sau sẽ upsert record mới và giữ nguyên các record cũ — collection phản ánh đúng snapshot hiện tại.

---

## 4. Liên hệ Day 09

Pipeline Day 10 và multi-agent retrieval Day 09 dùng **cùng corpus nguồn** tại `data/docs/` (4 tài liệu: `policy_refund_v4.txt`, `sla_p1_2026.txt`, `it_helpdesk_faq.txt`, `hr_leave_policy.txt`), nhưng khác lớp xử lý:

| | Day 09 (multi-agent) | Day 10 (ETL pipeline) |
|---|---|---|
| **Nguồn** | Đọc trực tiếp `data/docs/*.txt` | Đọc CSV export từ DB/API (`data/raw/policy_export_dirty.csv`) — đại diện cho lớp ingestion |
| **Xử lý** | Chunk + embed trực tiếp vào Chroma | Clean → Validate → Embed qua pipeline có kiểm chất lượng |
| **Chroma collection** | `day10_kb` (cùng tên) | `day10_kb` (cùng tên, cùng DB path `./chroma_db`) |
| **Retrieval** | Agent query trực tiếp collection | `eval_retrieval.py` và `grading_run.py` query cùng collection để đánh giá |

**Luồng tích hợp:** Day 10 pipeline *làm mới* collection `day10_kb` với dữ liệu đã qua kiểm chất lượng (không stale data, không PII, đúng version policy). Các agent Day 09 khi query collection này sẽ nhận kết quả retrieval đáng tin cậy hơn — đúng tinh thần "data observability before retrieval".

**Đánh giá retrieval:** `src/eval_retrieval.py` đọc golden questions từ `data/test_questions.json`, query `day10_kb` với top-k, kiểm tra `must_contain_any` / `must_not_contain` / `expect_top1_doc_id`. `src/grading_run.py` làm tương tự với `data/grading_questions.json`, output JSONL tại `artifacts/eval/grading_run.jsonl`.

---

## 5. Rủi ro đã biết

| # | Rủi ro | Mức độ | Mô tả chi tiết | Mitigation trong code |
|---|--------|--------|----------------|----------------------|
| 1 | **Stale refund policy** | Cao | Raw export chứa "14 ngày làm việc" trong `policy_refund_v4`, trong khi policy v4 quy định 7 ngày | Cleaning rule 6: tự động fix `14 ngày làm việc` → `7 ngày làm việc` + append `[cleaned: stale_refund_window]`. Expectation E3 halt nếu còn stale sau clean. Flag `--no-refund-fix` cho phép inject corruption để demo (Sprint 3) |
| 2 | **Stale SLA P1** | Cao | Raw export chứa "4 giờ" trong `sla_p1_2026`, SLA 2026 đã giảm xuống 2 giờ | Cleaning rule 8: tự động fix `4 giờ` → `2 giờ` + append `[cleaned: stale_sla_p1]`. Expectation E7 halt nếu còn stale |
| 3 | **PII leakage (email trong chunk)** | Cao | Raw text có thể chứa email nhân viên/khách hàng, nếu embed vào vector store sẽ expose qua retrieval | Cleaning rule 11: regex phát hiện email → thay bằng `[REDACTED_EMAIL]`. Expectation E10 halt nếu còn raw email sau clean |
| 4 | **HR policy version conflict** | Trung bình | Raw export có thể chứa bản HR policy cũ (effective_date < 2026-01-01), gây mâu thuẫn version | Cleaning rule 3: quarantine các chunk `hr_leave_policy` có `effective_date < HR_LEAVE_MIN_DATE` (đọc từ `contracts/data_contract.yaml`). Expectation E6 halt nếu lọt qua |
| 5 | **Freshness SLA trên sample data** | Trung bình | Manifest `latest_exported_at` = `2026-04-10T08:00:00`, run timestamp = `2026-04-15T07:09:25Z` → age ≈ 119 giờ, vượt SLA 24h → FAIL | `check_manifest_freshness()` trả về FAIL nếu `age_hours > sla_hours`. Trong thực tế, SLA cần điều chỉnh theo chu kỳ export thực hoặc cập nhật `latest_exported_at` từ nguồn DB watermark |
| 6 | **Unknown doc_id trong export** | Thấp | Raw export có thể chứa doc_id không thuộc allowlist (catalog sai, data leak từ hệ thống khác) | Cleaning rule 1: đối chiếu với `allowed_doc_ids` từ `contracts/data_contract.yaml`, quarantine nếu không khớp |
| 7 | **Suspicious placeholders** | Thấp | Chunk chứa "???", "TODO", "FIXME", "lỗi migration" — dấu hiệu data chưa hoàn thiện hoặc lỗi migration | Cleaning rule 13: quarantine các chunk có marker nghi vấn. Expectation E8 warn nếu lọt qua |
| 8 | **Data contract hard-code fallback** | Thấp | Nếu `contracts/data_contract.yaml` không đọc được, code dùng fallback hard-coded (`cleaning_rules.py:30-33`) | Nên đảm bảo contract file luôn tồn tại; fallback chỉ là safety net, không phải nguồn config chính thức |
