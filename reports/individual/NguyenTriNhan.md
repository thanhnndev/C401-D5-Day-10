# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Nguyễn Trí Nhân  
**Vai trò:** Cleaning / Quality Owner  
**Ngày nộp:** 15/04/2026  

---

## 1. Tôi phụ trách phần nào? (80–120 từ)

**File / module:**

- `src/transform/cleaning_rules.py`: Tôi chịu trách nhiệm chính trong việc nâng cấp tập luật dọn dẹp dữ liệu (Cleaning Rules). Tôi đã thiết kế và lập trình thêm 8 custom rules (ví dụ: Lọc placeholder rỗng, loại bỏ ký tự BOM, Normalize whitespace, Fix SLA P1, chèn Prefix IT FAQ, xóa PII e-mails).

**Kết nối với thành viên khác:**
Tôi làm việc chặt chẽ với Ingestion Owner để hiểu đặc thù các lỗi rác hay gặp từ raw export (như lỗi encode `\ufeff`). Đồng thời, tôi phối hợp với Embed Owner vì luật thêm cụm "IT FAQ:" hoặc việc xóa "smart quotes" của tôi có tác động trực tiếp giúp việc tìm kiếm vector (Grounding) chính xác hơn.

**Bằng chứng (commit / comment trong code):**
Tôi đã chỉnh sửa hàm `clean_rows()`, các khối code `# Rule 8: Fix stale P1 SLA`, `# Rule 9: IT FAQ Prefix`, và `# Rule 11: Remove PII (Emails)` minh chứng rõ điều này. Trên bảng metric, nó giúp giảm số file rác lọt vào tập Cleaned và tăng lượng `quarantine_records` cần thiết khi bắt trúng các chunk dưới 15 ký tự chữ.

---

## 2. Một quyết định kỹ thuật (100–150 từ)

Trong quá trình xử lý, thay vì áp dụng Expectation `halt` hoặc tống mọi chunk có chứa ký tự lạ/sai quy cách vào Quarantine, tôi quyết định lựa chọn chiến lược **"Mutation over Quarantine"** (Biến đổi thay vì Cách ly) cho các lỗi sinh ra do định dạng văn bản. Cụ thể, đối với khoảng trắng thừa, dấu ngoặc kép dạng smart quotes ("”"), hay lỗi ký tự BOM (replacement chars), tôi dùng Regex để strip/replace cấu trúc text từ trong code.

Quyết định này mang lại lợi ích lớn: nó giúp pipeline giữ lại được khối lượng dữ liệu mang ngữ nghĩa cực kỳ quý giá, tránh tỷ lệ rơi rụng (drop data) quá lớn khiến hệ thống thiếu context rèn luyện. Việc tôi đánh dấu lại bằng format tags `[cleaned: <reason>]` (ví dụ `[cleaned: update_sla_p1]`) ở cuối cùng của mỗi chunk giúp duy trì tính Data Observability (minh bạch dòng chảy dữ liệu), để sau này khi debug model, ta có căn cứ trace được dòng đó đã bị code tự động modify.

---

## 3. Một lỗi hoặc anomaly đã xử lý (100–150 từ)

**Triệu chứng:** Khi chạy eval trên raw dataset, mô hình trả lời sai các câu hỏi liên quan đến thời hạn xử lý P1 của năm 2026 và câu trả lời liên quan tới reset password bị lẫn lộn bối cảnh. Khảo sát dữ liệu, tôi phát hiện vài sự cố (anomaly): tài liệu `sla_p1_2026` còn tồn đọng chữ SLA "4 giờ" thay vì "2 giờ"; vài chunk của tài liệu helpdesk quá ngắn dẫn tới Vector Retrieval chấm nhầm rank.

**Phát hiện và Fix:** Thông qua metric `top1_doc_expected` lúc xuất ra hay bị báo False trong kết quả CSV, tôi đã thêm **Rule 8 (Fix stale P1 SLA)** bắt cứng logic `doc_id == "sla_p1_2026"` để đổi triệt để cụm "4 giờ" sang "2 giờ". Đồng thời áp dụng **Rule 9** đính kèm cứng tiền tố `"IT FAQ: "` trên mọi chunk IT Helpdesk. Nhờ thế, Retrieval đã khớp chính xác, kết quả `hits_forbidden=false` thành công, mô hình không còn trả lời dựa trên policy hết hạn nữa.

---

## 4. Bằng chứng trước / sau (80–120 từ)

Trích đoạn chạy test logging Pipeline ở môi trường Develop (chưa có ID UUID thực tế, test mock):

- **Trước (Raw Input):**
  `{"doc_id": "sla_p1_2026", "chunk_text": "SLA cho ticket P1 được xử lý trong vòng 4 giờ."}`
- **Sau (Cleaned Output):**
  `chunk_text: SLA cho ticket P1 được xử lý trong vòng 2 giờ. [cleaned: update_sla_p1]`

Trên tệp output `artifacts/quarantine/quarantine_*.csv`, tôi đã đối chiếu thành công các dòng rác kiểu "N/A" bị chặn với Reason code rõ ràng: `meaningless_placeholder`, `chunk_too_short`. Đảm bảo hệ RAG không đọc lầm data vớ vẩn này.

---

## 5. Cải tiến tiếp theo (40–80 từ)

Nếu có thêm 2 giờ làm việc, thay vì đang lập trình cứng (hard-code) các Regex tìm-thay và giới hạn kích thước chunk 15 ký tự trong file `src/transform/cleaning_rules.py`, tôi sẽ tách và chuyển hết các ngưỡng tham số cấu hình này vào file `contracts/data_contract.yaml`. Việc này sẽ giúp thay đổi tham số chuẩn hóa nhanh chóng ở runtime mà không cần triển khai lại script code.
