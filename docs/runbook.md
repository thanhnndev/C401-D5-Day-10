# Runbook — Lab Day 10

Runbook này dùng để xử lý nhanh các sự cố thường gặp của pipeline Day 10 theo thứ tự: freshness, quality, publish boundary, rồi mới đến retrieval. Mục tiêu là tìm ra lỗi ở lớp dữ liệu trước khi đổ lỗi cho prompt hoặc agent.

---

## Symptom

Các dấu hiệu thường gặp từ phía user hoặc evaluator:

- Agent trả lời sai policy refund, ví dụ nói `14 ngày` thay vì `7 ngày`.
- Kết quả retrieval top-k có chunk stale dù top-1 nhìn có vẻ đúng.
- Pipeline chạy xong nhưng `freshness_check=FAIL`.
- `grading_run.jsonl` hoặc `eval_retrieval.py` cho thấy `hits_forbidden=yes` hay `top1_doc_expected=no`.

---

## Detection

Nguồn quan sát chính:

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
| 1 | Mở `artifacts/logs/run_<run-id>.log` | Thấy đủ `run_id`, `raw_records`, `cleaned_records`, `quarantine_records`, expectation status, `PIPELINE_OK` |
| 2 | Mở `artifacts/manifests/manifest_<run-id>.json` | Có `run_timestamp`, `latest_exported_at`, `cleaned_csv`, `chroma_collection` |
| 3 | Chạy `python etl_pipeline.py freshness --manifest ...` | Biết rõ trạng thái `PASS`, `WARN`, hoặc `FAIL` và lý do |
| 4 | Mở `artifacts/quarantine/quarantine_<run-id>.csv` | Xác định record nào bị loại khỏi cleaned và vì sao |
| 5 | Chạy `python eval_retrieval.py --out artifacts/eval/check_eval.csv` | Kiểm tra retrieval có kéo stale chunk hoặc miss keyword mong đợi không |
| 6 | Nếu nghi index stale, đối chiếu log `embed_prune_removed` và `embed_upsert` | Xác nhận Chroma đã phản ánh đúng cleaned snapshot mới nhất |

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
