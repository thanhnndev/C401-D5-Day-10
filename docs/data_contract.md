# Data contract — Lab Day 10

Tài liệu này diễn giải `contracts/data_contract.yaml` theo góc nhìn vận hành. Mục tiêu là mô tả dữ liệu cleaned nào được phép publish vào vector store, dữ liệu nào phải quarantine, và nhóm nào chịu trách nhiệm khi chất lượng hoặc freshness có vấn đề.

---

## 1. Nguồn dữ liệu (source map)

| Nguồn | Phương thức ingest | Failure mode chính | Metric / alert |
|-------|-------------------|-------------------|----------------|
| `data/raw/policy_export_dirty.csv` | `etl_pipeline.py run` đọc CSV export làm đầu vào raw | duplicate record, `doc_id` lạ, `effective_date` không đúng ISO, thiếu ngày, stale policy refund 14 ngày, version HR cũ | `raw_records`, `cleaned_records`, `quarantine_records`, expectation fail trong log |
| `data/docs/*.txt` canonical corpus | Dùng làm nguồn chuẩn để đối chiếu `doc_id` và version tài liệu trước khi embed | sai phiên bản policy, chunk stale còn sót trong index, mismatch giữa raw export và tài liệu nguồn | `hits_forbidden`, `top1_doc_expected`, `embed_prune_removed`, eval CSV |
| `artifacts/manifests/manifest_<run-id>.json` | Sinh ra sau mỗi run để theo dõi publish boundary | thiếu `latest_exported_at`, timestamp không parse được, dữ liệu quá hạn SLA | `freshness_check`, `age_hours`, `sla_hours` |

---

## 2. Schema cleaned

Schema cleaned là hợp đồng tối thiểu trước khi publish vào Chroma collection `day10_kb`.

| Cột | Kiểu | Bắt buộc | Ghi chú |
|-----|------|----------|---------|
| `chunk_id` | string | Có | ID ổn định để `upsert` idempotent vào vector store. Không được trùng giữa hai chunk khác nội dung. |
| `doc_id` | string | Có | Phải nằm trong allowlist contract: `policy_refund_v4`, `sla_p1_2026`, `it_helpdesk_faq`, `hr_leave_policy`. |
| `chunk_text` | string | Có | Nội dung chunk sau clean; cần đủ dài để có ý nghĩa retrieval. Contract hiện yêu cầu tối thiểu 8 ký tự. |
| `effective_date` | date | Có | Ngày hiệu lực ở định dạng ISO `YYYY-MM-DD`; dùng để loại bỏ policy cũ hoặc không hợp lệ. |
| `exported_at` | datetime | Có | Thời điểm export từ nguồn; được dùng làm watermark freshness qua `latest_exported_at` trong manifest. |

---

## 3. Quy tắc chất lượng chính

Các rule dưới đây là phần cốt lõi của data contract và phải nhất quán với cleaning + expectation suite:

| Rule | Loại | Mục tiêu |
|------|------|----------|
| `allowed_doc_ids` | Cleaning / contract | Chỉ publish các `doc_id` hợp lệ theo danh sách canonical. |
| Chuẩn hóa `effective_date` sang ISO | Cleaning | Tránh lệch version do dữ liệu ngày tháng không đồng nhất. |
| `no_duplicate_chunk_text` | Expectation `warn` | Phát hiện duplicate chunk để tránh retrieval top-k bị lặp. |
| `no_stale_refund_window` | Expectation `halt` | Không được publish chunk refund còn chứa cửa sổ 14 ngày thay vì 7 ngày. |
| `hr_leave_min_effective_date = 2026-01-01` | Versioning | HR leave policy cũ hơn cutoff bị xem là không canonical. |

---

## 4. Quarantine vs drop

Pipeline dùng hai cách xử lý record lỗi:

| Trường hợp | Cách xử lý | Lý do |
|-----------|------------|-------|
| `doc_id` không thuộc allowlist, ngày không chuẩn hóa được, version HR cũ, record không đạt điều kiện publish | `quarantine` | Giữ lại để điều tra, đếm metric, và làm bằng chứng trong báo cáo chất lượng. |
| Chunk cũ không còn xuất hiện trong cleaned run hiện tại | `drop` khỏi Chroma index qua `embed_prune_removed` | Giữ index phản ánh đúng publish snapshot hiện tại, tránh stale vector làm hỏng retrieval. |

Quy ước vận hành:

- Không merge lại record từ quarantine vào cleaned nếu chưa xác định được nguyên nhân gốc.
- Cleaning owner và monitoring owner cùng review các dòng quarantine có ảnh hưởng đến `quarantine_records` hoặc expectation fail.
- Nếu cần phục hồi, phải rerun pipeline để sinh cleaned CSV và manifest mới thay vì sửa tay trực tiếp trong artifact.

---

## 5. Phiên bản & canonical

Source of truth hiện tại:

| `doc_id` | Canonical source | Ghi chú |
|----------|------------------|---------|
| `policy_refund_v4` | `data/docs/policy_refund_v4.txt` | Refund window chuẩn là 7 ngày. Chunk chứa 14 ngày được xem là stale. |
| `sla_p1_2026` | `data/docs/sla_p1_2026.txt` | Dùng cho retrieval và đối chiếu SLA support. |
| `it_helpdesk_faq` | `data/docs/it_helpdesk_faq.txt` | FAQ chuẩn cho helpdesk case. |
| `hr_leave_policy` | `data/docs/hr_leave_policy.txt` | Chỉ chấp nhận version có `effective_date >= 2026-01-01` theo contract hiện tại. |

Nguyên tắc canonical:

- Vector store chỉ được xem là đúng khi cleaned CSV và Chroma index cùng phản ánh snapshot canonical mới nhất.
- Nếu raw export mâu thuẫn với canonical source, pipeline ưu tiên quarantine hoặc expectation halt thay vì publish im lặng.
- Khi thay đổi version policy trong tương lai, cần cập nhật đồng thời `contracts/data_contract.yaml`, cleaning rules, và tài liệu này.

---

## 6. Owner, SLA, và metric theo dõi

Đề xuất owner để điền đồng bộ với `contracts/data_contract.yaml`:

| Hạng mục | Owner |
|----------|-------|
| Dữ liệu raw export | Ingestion Owner |
| Cleaning / quarantine | Cleaning Owner |
| Freshness / manifest / runbook | Monitoring Owner |
| Chroma publish boundary | Embed Owner |

SLA và metric chính:

| Metric | Ý nghĩa | Ngưỡng / kỳ vọng |
|--------|--------|------------------|
| `raw_records` | Số record đầu vào raw | Không giảm bất thường giữa các run cùng nguồn |
| `cleaned_records` | Số record đủ điều kiện publish | Phản ánh snapshot canonical sau clean |
| `quarantine_records` | Số record bị giữ lại để điều tra | Không tăng bất thường nếu không có inject |
| `freshness_check` | Trạng thái freshness của manifest | `PASS` khi `age_hours <= FRESHNESS_SLA_HOURS` |
| `contains_expected` | Retrieval có chạm keyword cần có hay không | Nên là `yes` cho các câu golden |
| `hits_forbidden` | Retrieval có kéo chunk stale/sai policy hay không | Nên là `no` |

Metric impact nên được ghi lại trong `reports/group_report.md` để chứng minh rule và expectation mới có tác động thật, không phải chỉnh sửa trivial.
