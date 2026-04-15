# Runbook — Lab Day 10 (Data Pipeline & Data Observability)

---

## Symptom

Khi pipeline gặp sự cố, user hoặc agent sẽ thấy các triệu chứng cụ thể sau:

1. **Agent trả lời sai chính sách hoàn tiền**: Agent trả lời "14 ngày hoàn tiền" thay vì "7 ngày" theo chính sách mới. Đây là dấu hiệu rõ nhất của dữ liệu stale — nội dung cũ (trước khi áp dụng `no_refund_fix`) vẫn còn trong vector store.

2. **Agent trả lời sai SLA**: Agent trả lời "4 giờ SLA" thay vì "2 giờ" xử lý. Tương tự, đây là pattern stale data khi export mới chưa được ingest vào Chroma.

3. **Retrieval eval có `hits_forbidden=yes`**: Khi chạy `python src/eval_retrieval.py --out artifacts/eval/before_after_eval.csv`, cột `hits_forbidden` xuất hiện giá trị `yes` cho query `q_refund_window`. Điều này chứng tỏ top-k retrieval vẫn trả về document cũ đã bị loại bỏ (stale content).

---

## Detection

Các chỉ số và check sau sẽ báo hiệu sự cố:

| Check | Nguồn | Trạng thái | Ý nghĩa |
|-------|-------|------------|---------|
| **Freshness check** | `python src/etl_pipeline.py freshness --manifest artifacts/manifests/manifest_<run-id>.json` | `PASS` / `WARN` / `FAIL` | `FAIL` khi `age_hours > sla_hours` (mặc định 24h). VD: Run `2026-04-15T07-08Z` có `latest_exported_at = 2026-04-10` → freshness FAIL vì dữ liệu đã stale 5 ngày |
| **Expectation failures** | `artifacts/logs/run_<run_id>.log` | `expectation[NAME] FAIL (halt/warn)` | Pipeline log ghi rõ expectation nào failed. VD: `expectation[no_refund_fix] FAIL` khi vẫn còn rows chứa chính sách hoàn tiền cũ |
| **Eval hits_forbidden** | `artifacts/eval/after.csv` | Cột `hits_forbidden=yes` | Retrieval vẫn tìm thấy document không nên xuất hiện. VD: query `q_refund_window` hits document chứa "14 ngày" |
| **Embed prune removed** | Log embed step | `embed_prune_removed > 0` | Cho thấy có vector cũ bị xóa khỏi Chroma collection — xác nhận có dữ liệu stale đã được loại bỏ |

---

## Diagnosis

| Bước | Việc làm | Kết quả mong đợi |
|------|----------|------------------|
| 1 | **Kiểm tra manifest** tại `artifacts/manifests/manifest_2026-04-15T07-08Z.json` — đọc các trường `no_refund_fix`, `skipped_validate`, `raw_records`, `cleaned_records`, `quarantine_records`, `latest_exported_at` | Nếu `no_refund_fix=true` → pipeline đã bỏ qua fix chính sách hoàn tiền. Nếu `skipped_validate > 0` → có rows bị bỏ qua validation. So sánh `raw_records=11` vs `cleaned_records=7` → 4 rows bị loại. `latest_exported_at=2026-04-10` → dữ liệu stale 5 ngày |
| 2 | **Mở quarantine file** tại `artifacts/quarantine/quarantine_2026-04-15T07-08Z.csv` — xem cột lý do reject | File chứa 4 rows bị quarantine với lý do cụ thể (VD: `invalid_policy_version`, `missing_required_field`, `sla_out_of_range`, `duplicate_entry`). Xác định xem rows chứa chính sách cũ có bị quarantine hay không |
| 3 | **Chạy eval retrieval**: `python src/eval_retrieval.py --out artifacts/eval/before_after_eval.csv` — kiểm tra cột `contains_expected` và `hits_forbidden` | Với query `q_refund_window`: nếu `contains_expected=no` và `hits_forbidden=yes` → retrieval đang trả về document sai (stale content). Nếu `top1_doc_expected=no` → document top-1 không phải document đúng |
| 4 | **Kiểm tra log** tại `artifacts/logs/run_2026-04-15T07-08Z.log` — tìm các dòng `expectation[*] FAIL` | Log ghi rõ: `expectation[no_refund_fix] FAIL (halt)`, `expectation[sla_max_2h] FAIL (warn)`, record counts (`raw=11, cleaned=7, quarantine=4`), embed info (`chroma_collection=kb_v1`, `latest_exported_at=2026-04-10`). Đây là bằng chứng trực tiếp cho diagnosis |

---

## Mitigation

Các hành động khắc phục cụ thể theo thứ tự ưu tiên:

1. **Rerun pipeline không có flag `--no-refund-fix`**:
   ```bash
   python src/etl_pipeline.py run
   ```
   Chạy lại pipeline đầy đủ (ingest → clean → validate → embed) để áp dụng đúng fix chính sách hoàn tiền. Đảm bảo không truyền `--no-refund-fix` để expectation `no_refund_fix` được thực thi.

2. **Xóa flag `--skip-validate` để enforcement expectations**:
   Nếu pipeline trước đó chạy với `--skip-validate`, các rows vi phạm data contract đã không bị quarantine. Rerun mà không có flag này để đảm bảo validation được thực thi.

3. **Rollback Chroma collection nếu embed bị corrupt**:
   ```bash
   # Xóa collection cũ
   # Re-embed từ cleaned CSV mới
   python src/etl_pipeline.py run
   ```
   Nếu phát hiện `embed_prune_removed` lớn bất thường hoặc `hits_forbidden` vẫn còn sau rerun, xóa Chroma collection và re-embed toàn bộ từ `artifacts/cleaned/cleaned_<run_id>.csv`.

4. **Tạm thời hiển thị banner "data stale" nếu freshness FAIL**:
   Khi `python src/etl_pipeline.py freshness` trả về `FAIL`, kích hoạt banner cảnh báo trên UI: *"Dữ liệu chính sách có thể không cập nhật — lần export cuối: 2026-04-10"*. Giảm thiểu tác động đến user cho đến khi pipeline chạy thành công.

---

## Prevention

Các biện pháp ngăn chặn tái diễn:

1. **Thêm expectation mới cho stale patterns**:
   Mở rộng `data_contract.yaml` với các expectation phát hiện stale data sớm:
   - `expectation[sda_max_age]`: Cảnh báo khi `latest_exported_at` quá 24h
   - `expectation[no_stale_refund]`: Reject rows chứa từ khóa "14 ngày" (chính sách cũ)
   - `expectation[sla_consistency]`: Đảm bảo tất cả rows có cùng SLA threshold

2. **Alert khi freshness FAIL quá 2 lần liên tiếp**:
   Thiết lập automation flow trong Directus: nếu 2 lần run liên tiếp có `freshness=FAIL`, gửi notification cho owner và tự động halt pipeline. Không cho phép pipeline tiếp tục ingest dữ liệu stale.

3. **Owner review khi thay đổi `data_contract.yaml`**:
   Mọi thay đổi đến data contract (thêm/bớt expectation, thay đổi threshold) yêu cầu owner review và approve trước khi merge. Đây là gate quan trọng để tránh vô tình weaken validation.

4. **Kết nối sang Day 11 — Guardrail concepts**:
   Các phòng ngừa trên chính là nền tảng của guardrail system (Day 11):
   - **Pre-flight check**: Freshness check trước khi ingest = guardrail đầu tiên
   - **In-flight validation**: Expectations trong pipeline = guardrail kiểm soát chất lượng data
   - **Post-flight eval**: Retrieval eval với `hits_forbidden` = guardrail đo lường hiệu quả
   - **Circuit breaker**: Halt pipeline khi 2 lần FAIL liên tiếp = guardrail ngăn lỗi lan rộng

   Day 11 sẽ mở rộng các khái niệm này thành hệ thống guardrail hoàn chỉnh với policy enforcement, real-time monitoring, và automated remediation.
