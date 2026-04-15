# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Trần Xuân Trường
**Vai trò:** Evaling, Data
**Ngày nộp:** 15/4/2026
**Độ dài yêu cầu:** **400–650 từ**


---

## 1. Tôi phụ trách phần nào? (80–120 từ)

**File / module:**

- etl_pipeline: chạy test, so sánh kết quả giữa các lần chạy khác nhau

**Kết nối với thành viên khác:**

_________________

**Bằng chứng (commit / comment trong code):**
eval: origin, cleaned, inject-bad, clear_pii

---

## 2. Một quyết định kỹ thuật (100–150 từ)

> Chạy test ban đầu với 1 row, sau đó chạy tất cả bộ dữ liệu
> Chạy test với dữ liệu ịnect-bad
> Chạy test với dữ dữ liệu đã được cleaned
> Đã thêm row kiểm tra PII cho dự án


---

## 3. Một lỗi hoặc anomaly đã xử lý (100–150 từ)

> Dữ liệu chứa thông tin nhạy cảm -> thêm rules để ẩn thông tin nhạy cam


---

## 4. Bằng chứng trước / sau (80–120 từ)

> q_pii,Ai chịu trách nhiệm yêu cầu hoàn tiền,it_helpdesk_faq,Tài khoản bị khóa sau 5 lần đăng nhập sai liên tiếp.,yes,no,no,3
-> dữ liệu chỉ được ẩn khi dùng cleaned_rules

_________________

---

## 5. Cải tiến tiếp theo (40–80 từ)

> Chuyển dữ liệu từ *.txt sang .csv đồng bộ 1 luồng chạy, từ đó tìm ra được thêm nhiều insight

_________________
