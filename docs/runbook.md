# Runbook — Lab Day 10 (Data Pipeline & Data Observability)

Runbook này dùng để xử lý nhanh các sự cố thường gặp của pipeline Day 10 theo thứ tự: freshness, quality, publish boundary, rồi mới đến retrieval. Mục tiêu là tìm ra lỗi ở lớp dữ liệu trước khi đổ lỗi cho prompt hoặc agent.

---

## Symptom

Khi pipeline gặp sự cố, user hoặc agent sẽ thấy các triệu chứng cụ thể sau:

1. **Agent trả lời sai chính sách hoàn tiền**: Agent trả lời "14 ngày hoàn tiền" thay vì "7 ngày" theo chính sách mới. Đây là dấu hiệu rõ nhất của dữ liệu stale — nội dung cũ (trước khi áp dụng `no_refund_fix`) vẫn còn trong vector store.

2. **Agent trả lời sai SLA**: Agent trả lời "4 giờ SLA" thay vì "2 giờ" xử lý. Tương tự, đây là pattern stale data khi export mới chưa được ingest vào Chroma.

3. **Retrieval eval có `hits_forbidden=yes`**: Khi chạy `python src/eval_retrieval.py --out artifacts/eval/before_after_eval.csv`, cột `hits_forbidden` xuất hiện giá trị `yes` cho query `q_refund_window`. Điều này chứng tỏ top-k retrieval vẫn trả về document cũ đã bị loại bỏ (stale content).

Các dấu hiệu bổ sung từ evaluator:

- Pipeline chạy xong nhưng `freshness_check=FAIL`.
- `grading_run.jsonl` hoặc `eval_retrieval.py` cho thấy `top1_doc_expected=no` — document top-1 không phải document đúng.
- Kết quả retrieval top-k có chunk stale dù top-1 nhìn có vẻ đúng.

---

## Detection

Các chỉ số và nguồn quan sát chính:

| Check | Nguồn | Trạng thái | Ý nghĩa |
|-------|-------|------------|---------|
| **Freshness check** | `python src/etl_pipeline.py freshness --manifest artifacts/manifests/manifest_<run-id>.json` | `PASS` / `WARN` / `FAIL` | `FAIL` khi `age_hours > sla_hours` (mặc định 24h). VD: Run `2026-04-15T07-08Z` có `latest_exported_at = 2026-04-10` → freshness FAIL vì dữ liệu đã stale 5 ngày |
| **Expectation failures** | `artifacts/logs/run_<run_id>.log` | `expectation[NAME] FAIL (halt/warn)` | Pipeline log ghi rõ expectation nào failed. VD: `expectation[no_refund_fix] FAIL` khi vẫn còn rows chứa chính sách hoàn tiền cũ |
| **Eval hits_forbidden** | `artifacts/eval/after.csv` | Cột `hits_forbidden=yes` | Retrieval vẫn tìm thấy document không nên xuất hiện. VD: query `q_refund_window` hits document chứa "14 ngày" |
| **Embed prune removed** | Log embed step | `embed_prune_removed > 0` | Cho thấy có vector cũ bị xóa khỏi Chroma collection — xác nhận có dữ liệu stale đã được loại bỏ |

Bảng tín hiệu chi tiết:

| Tín hiệu | Xem ở đâu | Ý nghĩa |
|----------|-----------|---------|
| `run_id`, `raw_records`, `cleaned_records`, `quarantine_records` | `artifacts/logs/run_<run-id>.log` | Kiểm tra pipeline có ingest và clean đúng snapshot hay không |
| `expectation[...] OK/FAIL` | `artifacts/logs/run_<run-id>.log` | Xác định rule nào đang cảnh báo hoặc halt |
| `manifest_written`, `freshness_check` | `artifacts/logs/run_<run-id>.log` và `artifacts/manifests/manifest_<run-id>.json` | Theo dõi publish boundary và freshness |
| `contains_expected`, `hits_forbidden`, `top1_doc_expected` | `artifacts/eval/*.csv` | Đo chất lượng retrieval trước/sau fix hoặc inject |
| `embed_prune_removed`, `embed_upsert` | log run | Kiểm tra index có được snapshot lại đúng hay không |

Lệnh kiểm tra nhanh:

```bash
cd lab
python etl_pipeline.py run
python etl_pipeline.py freshness --manifest artifacts/manifests/manifest_<run-id>.json
python eval_retrieval.py --out artifacts/eval/check_eval.csv
```

---

## Diagnosis

| Bước | Việc làm | Kết quả mong đợi |
|------|----------|------------------|
| 1 | **Mở log** tại `artifacts/logs/run_<run-id>.log` | Thấy đủ `run_id`, `raw_records`, `cleaned_records`, `quarantine_records`, expectation status, `PIPELINE_OK` |
| 2 | **Kiểm tra manifest** tại `artifacts/manifests/manifest_<run-id>.json` | Có `run_timestamp`, `latest_exported_at`, `cleaned_csv`, `chroma_collection`. VD: Run `2026-04-15T07-08Z` có `no_refund_fix=true` → pipeline đã bỏ qua fix chính sách. So sánh `raw_records=11` vs `cleaned_records=7` → 4 rows bị loại |
| 3 | **Chạy freshness**: `python etl_pipeline.py freshness --manifest ...` | Biết rõ trạng thái `PASS`, `WARN`, hoặc `FAIL` và lý do |
| 4 | **Mở quarantine file** tại `artifacts/quarantine/quarantine_<run-id>.csv` | Xác định record nào bị loại khỏi cleaned và vì sao. VD: 4 rows bị quarantine với lý do `invalid_policy_version`, `missing_required_field`, `sla_out_of_range`, `duplicate_entry` |
| 5 | **Chạy eval retrieval**: `python eval_retrieval.py --out artifacts/eval/check_eval.csv` | Kiểm tra retrieval có kéo stale chunk hoặc miss keyword mong đợi không. Với query `q_refund_window`: nếu `contains_expected=no` và `hits_forbidden=yes` → retrieval đang trả về document sai |
| 6 | **Nếu nghi index stale**, đối chiếu log `embed_prune_removed` và `embed_upsert` | Xác nhận Chroma đã phản ánh đúng cleaned snapshot mới nhất |

Thứ tự debug khuyến nghị:

1. Freshness và version.
2. Volume và quarantine.
3. Schema và contract.
4. Publish boundary của Chroma.
5. Retrieval result.

---

## PASS / WARN / FAIL

`monitoring/freshness_check.py` hiện đánh giá freshness từ manifest bằng trường `latest_exported_at`, nếu không có thì fallback sang `run_timestamp`.

### PASS

Điều kiện:

- Timestamp trong manifest parse được.
- `age_hours <= FRESHNESS_SLA_HOURS`.

Ý nghĩa:

- Snapshot dữ liệu còn trong SLA.
- Có thể tin tưởng đây là dữ liệu đủ mới để publish và chạy retrieval evaluation.

Hành động:

- Không cần xử lý khẩn cấp.
- Tiếp tục kiểm expectation và eval để xác nhận chất lượng nội dung.

### WARN

Điều kiện trong code hiện tại:

- Manifest tồn tại nhưng không có timestamp hợp lệ.
- `latest_exported_at` hoặc `run_timestamp` bị thiếu, rỗng, hoặc parse ISO thất bại.

Ý nghĩa:

- Pipeline chưa đủ metadata để kết luận dữ liệu mới hay cũ.
- Đây là lỗi observability hơn là lỗi nội dung dữ liệu.

Hành động:

1. Kiểm tra file manifest có trường `latest_exported_at` hoặc `run_timestamp` không.
2. Kiểm tra định dạng timestamp có phải ISO hợp lệ không.
3. Rerun pipeline để sinh manifest mới nếu metadata đang thiếu.

### FAIL

Điều kiện:

- Manifest không tồn tại.
- Hoặc timestamp hợp lệ nhưng `age_hours > FRESHNESS_SLA_HOURS`.

Ý nghĩa:

- Snapshot dữ liệu đã quá hạn SLA hoặc không có manifest để chứng minh freshness.
- Không nên xem retrieval hiện tại là đáng tin cho production-like usage.

Hành động:

1. Xác nhận raw export có còn là snapshot cũ hay không.
2. Rerun `python etl_pipeline.py run` với dữ liệu mới hoặc timestamp hợp lệ.
3. Sau khi rerun, chạy lại `python etl_pipeline.py freshness --manifest ...`.
4. Nếu vẫn `FAIL`, cập nhật runbook và group report để giải thích rõ SLA đang áp theo snapshot data hay theo pipeline run.

---

## Mitigation

Tùy loại lỗi, áp dụng xử lý nhanh sau:

| Tình huống | Cách xử lý |
|-----------|------------|
| `no_stale_refund_window` fail | Chạy lại pipeline chuẩn, không dùng `--no-refund-fix`; không publish run inject vào kết quả cuối |
| `hits_forbidden=yes` | Rerun pipeline chuẩn để Chroma prune vector stale, sau đó eval lại |
| `quarantine_records` tăng mạnh | Mở quarantine CSV, xác định lỗi raw export hay cleaning rule quá chặt |
| `freshness_check=WARN` | Sửa metadata timestamp hoặc rerun để tạo manifest hợp lệ |
| `freshness_check=FAIL` | Cập nhật snapshot mới hoặc điều chỉnh SLA có giải thích trong report |

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

Nếu cần demo lỗi có chủ đích cho Sprint 3:

```bash
python etl_pipeline.py run --run-id inject-bad --no-refund-fix --skip-validate
python eval_retrieval.py --out artifacts/eval/after_inject_bad.csv
```

Sau đó phải chạy lại pipeline chuẩn để phục hồi index:

```bash
python etl_pipeline.py run --run-id final-good
python eval_retrieval.py --out artifacts/eval/final_good_eval.csv
```

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

Các biện pháp phòng ngừa nên giữ nhất quán trong nhóm:

- Luôn chạy pipeline chuẩn lại sau mọi demo inject để tránh để lại stale vector trong Chroma.
- Giữ `contracts/data_contract.yaml`, cleaning rules, và expectation suite đồng bộ khi thêm policy/version mới.
- Theo dõi `quarantine_records` và `hits_forbidden` như metric bắt buộc trong group report.
- Không chỉnh tay artifact trong `artifacts/`; mọi thay đổi phải đi qua rerun pipeline để còn `run_id` và manifest.
- Ghi rõ ownership: ai theo dõi freshness, ai duyệt quarantine, ai chịu trách nhiệm canonical source.

---

## Lệnh vận hành tối thiểu

```bash
cd lab
python etl_pipeline.py run --run-id final-good
python etl_pipeline.py freshness --manifest artifacts/manifests/manifest_final-good.json
python eval_retrieval.py --out artifacts/eval/final_good_eval.csv
python grading_run.py --out artifacts/eval/grading_run.jsonl
```

Nếu các bước trên đều ổn, nhóm đã có bộ artifact tối thiểu để nộp và giải thích sự cố khi cần.
