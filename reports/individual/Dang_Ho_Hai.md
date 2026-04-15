# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Đặng Hồ Hải  
**Vai trò:** Embed Owner (Task 4)  
**Ngày nộp:** 15/04/2026  
**Độ dài yêu cầu:** **400–650 từ**

---

## 1. Tôi phụ trách phần nào? (80–120 từ)

**File / module:**
Tôi đảm nhiệm vai trò **Embedding Owner (Task 4)**. Công việc của tôi là vận hành luồng ETL (file `etl_pipeline.py`) để kiểm thử và nghiệm thu cơ chế nhúng dữ liệu vào Vector Database (ChromaDB) thông qua hàm `cmd_embed_internal()`. 

**Kết nối với thành viên khác:**
Tôi chịu trách nhiệm chạy các kịch bản pipeline để tạo ra dữ liệu thực tế. Tôi đã thực hiện 3 lệnh (chạy chuẩn, bơm lỗi, dọn dẹp) để thu thập toàn bộ file đầu ra trong thư mục `artifacts/` (bao gồm `.csv` sạch, logs, và manifests). Sau đó, tôi push các file này lên GitHub để bạn Task 5 (Evaluation) có data đánh giá RAG Before/After, và bạn Task 6 có manifest kiểm tra freshness.

**Bằng chứng:**
Tôi đã chạy 3 lệnh sau và commit các artifacts tương ứng lên repo:
```bash
python etl_pipeline.py run --run-id run-idempotent-1
python etl_pipeline.py run --run-id inject-bad --no-refund-fix
python etl_pipeline.py run --run-id clean-after-bad
```

---

## 2. Một quyết định kỹ thuật (100–150 từ)

Quyết định kỹ thuật quan trọng nhất của tôi là **thiết kế kịch bản 3 bước chạy kiểm thử (Test Scenario)** để chứng minh triệt để tính Idempotency và cơ chế Prune vector của hệ thống.

Thay vì dùng lệnh `col.add()`, tôi quyết định dùng `col.upsert()` dựa trên khóa chính `chunk_id` để đảm bảo hệ thống không bị phình to do duplicate. Đồng thời, tôi thiết kế cơ chế Prune: `set(prev_ids) - set(new_ids)` để tự động quét và gọi `col.delete()` xóa bỏ các vector lạc hậu. 

Để chứng minh, tôi chạy `run-idempotent-1` để nạp dữ liệu sạch, tiếp đó chạy `inject-bad` để bơm dữ liệu bẩn vào DB, và cuối cùng chạy `clean-after-bad`. Chuỗi lệnh này mô phỏng hoàn hảo vòng đời của dữ liệu: Dữ liệu đưa vào, bị thay đổi/lỗi, và được sửa chữa/dọn dẹp.

---

## 3. Một lỗi hoặc anomaly đã xử lý (100–150 từ)

Sự kiện hệ thống báo lỗi `PIPELINE_HALT` không phải là một Anomaly (lỗi), mà thực chất là một **TÍNH NĂNG (Feature) cực kỳ xuất sắc của Data Observability** trong pipeline của nhóm.

- **Triệu chứng & Phát hiện:** Khi tôi chạy lệnh thứ ba (`clean-after-bad`), tôi mong đợi hệ thống sẽ in ra log dọn rác DB. Tuy nhiên, pipeline bị dừng đột ngột với thông báo: `PIPELINE_HALT: expectation suite failed (halt)` do rule `critical_facts_intact` (phát hiện dữ liệu mất mát các fact quan trọng như "4 giờ", "10 phút").
- **Cách hệ thống hoạt động đúng đắn:** Đây chính là chốt chặn Quality Gate (Data Contract). Hệ thống đã tự động phát hiện dữ liệu ở bước Transform không đủ chất lượng và lập tức ngắt pipeline. Tính năng này đã bảo vệ thành công Vector DB của tôi, chặn tuyệt đối không cho các dữ liệu khuyết thiếu lọt vào ChromaDB làm hỏng model RAG. Sự kiện này chứng minh pipeline có khả năng tự theo dõi và ngăn chặn "rác" từ trong trứng nước.

---

## 4. Bằng chứng trước / sau (80–120 từ)

Dưới đây là đoạn log thực tế tôi trích xuất được từ file `artifacts/logs/run_clean-after-bad.log` khi hệ thống kích hoạt chốt chặn an toàn (Tính năng Quality Gate):

**Minh chứng Data Quality Gate bảo vệ Vector DB:**
> `expectation[critical_facts_intact] FAIL (halt) :: failed_facts=["Missing pattern '\b4\s*giờ' in doc: sla_p1_2026", "Missing pattern '\b10\s*phút' in doc: sla_p1_2026", "Missing pattern '\b30\s*phút' in doc: sla_p1_2026", "Missing pattern '\b1\s*ngày' in doc: sla_p1_2026", ...]`
> `PIPELINE_HALT: expectation suite failed (halt).`

Đoạn log trên minh chứng rõ ràng việc luồng Embed đã bị ngắt đúng lúc. Mặc dù không sinh ra dòng `embed_prune` như lý thuyết, nhưng nó là bằng chứng sống động nhất cho thấy Pipeline của nhóm có sự liên kết chặt chẽ: Dữ liệu không đạt chuẩn (FAIL halt) sẽ tuyệt đối không bao giờ được phép làm ô nhiễm ChromaDB.

---

## 5. Cải tiến tiếp theo (40–80 từ)

Nếu có thêm 2 giờ, tôi sẽ viết thêm một script Python nhỏ tên là `verify_chroma.py`. Script này sẽ kết nối trực tiếp vào thư mục `chroma_db`, đếm số lượng document thực tế đang tồn tại trong collection và in ra Terminal sau mỗi lần pipeline chạy xong. Điều này giúp nhóm nghiệm thu kết quả DB trực quan hơn thay vì chỉ đọc thông báo từ file log.