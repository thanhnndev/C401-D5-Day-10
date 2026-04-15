# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Hồ Sỹ Minh Hà - 2A202600060  
**Vai trò:** Cleaning & Quality Owner  
**Ngày nộp:** 15/04/2026  
**Độ dài yêu cầu:** **400–650 từ**

---

## 1. Tôi phụ trách phần nào? (80–120 từ)

**File / module:**

- `src/transform/cleaning_rules.py`: Tôi đã thiết kế và triển khai 5 rule làm sạch mới (Rule 7, 10, 11, 12, 13) để xử lý các vấn đề về chất lượng dữ liệu như PII, placeholder và chuẩn hóa text.
- `src/quality/expectations.py`: Tôi đã nâng cấp hệ thống kiểm định sang Pydantic V2, tích hợp các business logic phức tạp trực tiếp vào schema validation để tự động hóa việc phát hiện dữ liệu lỗi thời (stale data).
- `artifacts/eval/grading_run.jsonl`: Tôi chịu trách nhiệm chạy script đánh giá trên dataset đã làm sạch để kiểm chứng hiệu quả của pipeline.

**Kết nối với thành viên khác:**
Tôi làm việc chặt chẽ với Ingestion Owner để hiểu cấu trúc `policy_export_dirty.csv` và cung cấp bộ dữ liệu sạch (`cleaned_*.csv`) cho Embed Owner thực hiện upsert vào ChromaDB.

**Bằng chứng (commit / comment trong code):**
Trong `src/transform/cleaning_rules.py`, tôi đã thêm Rule 9 để xóa PII (Email) và Rule 11 để chặn các placeholder như TODO, FIXME.

---

## 2. Một quyết định kỹ thuật (100–150 từ)

Tôi quyết định sử dụng **Pydantic V2** làm trung tâm cho `Expectation Suite` thay vì các hàm kiểm tra thủ công. 

**Lý do:**Q
1. **Declarative Validation:** Cho phép định nghĩa schema và quy tắc nghiệp vụ một cách minh bạch. Ví dụ, `field_validator` được dùng để đảm bảo `effective_date` luôn đúng chuẩn ISO.
2. **Centralized Logic:** Các rule quan trọng như phát hiện cửa sổ hoàn tiền 14 ngày (lỗi thời) được đặt ngay trong `model_validator`, giúp đảm bảo dữ liệu không bao giờ lọt qua nếu không vượt qua kiểm định nghiệp vụ.
3. **Error Mapping:** Pydantic cung cấp thông báo lỗi chi tiết, giúp tôi dễ dàng phân loại lỗi nào gây `halt` pipeline (như thiếu `doc_id`) và lỗi nào chỉ cần `warn` (như thiếu `exported_at`).

---

## 3. Một lỗi hoặc anomaly đã xử lý (100–150 từ)

Trong quá trình xử lý `policy_export_dirty.csv` (run_id: `2026-04-15T10-12Z`), tôi phát hiện hai anomaly nghiêm trọng:
1. **PII Exposure:** Một số chunk chứa email cá nhân của nhân viên IT. Nếu không xử lý, mô hình RAG có thể tiết lộ thông tin này. Tôi đã dùng Rule 11 (Regex) để chuyển thành `[REDACTED_EMAIL]`.
2. **Stale Refund Policy:** Dữ liệu raw ghi nhận 14 ngày làm việc cho chính sách hoàn tiền, trong khi thực tế đã đổi thành 7 ngày. 

**Kết quả:** 
Rule 6 đã tự động sửa lỗi 14 thành 7 ngày. Khi tôi chạy thử nghiệm với flag `--no-refund-fix`, Expectation `refund_no_stale_14d_window` đã kích hoạt trạng thái `halt`, chứng minh tính hiệu quả của hệ thống giám sát.

---

## 4. Bằng chứng trước / sau (80–120 từ)

Dựa trên kết quả từ `grading_run.jsonl` (run_id: `2026-04-15T10-12Z`):

**Trước (khi inject bad data):**
Query: "Khách có tối đa bao nhiêu ngày làm việc để gửi yêu cầu hoàn tiền?"
Kết quả: `contains_expected: false` (vì retrieval lấy nhầm bản 14 ngày).

**Sau (khi áp dụng cleaning rules):**
```json
{"id": "gq_d10_01", "question": "...hoàn tiền...", "top1_doc_id": "policy_refund_v4", "contains_expected": true}
```
`cleaned_records` là 10/20 record raw; 10 record còn lại bị đẩy vào `quarantine` với lý do chính xác như `suspicious_placeholders_detected` và `text_too_short`.

---

## 5. Cải tiến tiếp theo (40–80 từ)

Nếu có thêm 2 giờ, tôi sẽ triển khai **Fuzzy Matching** cho `doc_id` để cứu các record bị gõ sai tên tài liệu thay vì đẩy thẳng vào quarantine, đồng thời tích hợp thêm kiểm tra tính nhất quán giữa nội dung chunk và tiêu đề tài liệu bằng một mô hình nhỏ (Small Model) để lọc các nội dung "hallucination" ngay từ bước cleaning.
