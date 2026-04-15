# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Đào Phước Thịnh - 2A202600029  
**Vai trò:** Monitoring / Contract / Docs Owner — 2A202600029  
**Ngày nộp:** 2026-04-15  

---

## 1. Tôi phụ trách phần nào? (80–120 từ)

Trong dự án Lab Day 10, tôi đảm nhận vai trò **Monitoring và Contract Owner**. Trách nhiệm chính của tôi xoay quanh việc thiết lập "luật chơi" cho dữ liệu thông qua Data Contract và đảm bảo hệ thống có khả năng quan sát (observability) tốt để phát hiện sai lệch version hoặc dữ liệu cũ (stale data).

**File / module:**

- `contracts/data_contract.yaml`: Định nghĩa schema cleaned, các quy tắc chất lượng (quality rules), ngưỡng SLA freshness (24 giờ), và sơ đồ nguồn dữ liệu (source map).
- `docs/data_contract.md`: Diễn giải chi tiết hợp đồng dữ liệu cho các bên liên quan, làm rõ quy trình xử lý quarantine vs drop.
- `docs/runbook.md`: Xây dựng quy trình 6 bước (Symptom → Prevention) để đội ngũ vận hành có thể tự fix lỗi freshness hoặc quality mà không cần can thiệp sâu vào code.

**Kết nối với thành viên khác:**
Tôi làm việc chặt chẽ với **Cleaning Owner** để đồng bộ các rule `halt` (như stale refund window) vào contract, và với **Embed Owner** để định nghĩa ranh giới publish boundary trong manifest, đảm bảo Chroma index luôn phản ánh đúng snapshot cleaned mới nhất.

**Bằng chứng (commit / comment trong code):**
Tôi đã thực hiện khai báo quyền sở hữu trong file `contracts/data_contract.yaml` qua các commit:
- `ab7ead2`: add contracts
- `e878af7`: add docs_ 2A202600029
- Khai báo ownership trong code tại dòng 112-117 của file config.

---

## 2. Một quyết định kỹ thuật (100–150 từ)

Một quyết định kỹ thuật quan trọng mà tôi đưa ra là thiết lập mức độ nghiêm trọng (severity) là **`halt`** cho quy tắc **`no_stale_refund_window`** trong Data Contract. 

Khi phân tích rủi ro kinh doanh, việc trả lời sai chính sách hoàn tiền (ví dụ nói 14 ngày trong khi thực tế đã đổi thành 7 ngày ở version 4) gây thiệt hại trực tiếp về tài chính và uy tín hỗ trợ khách hàng. Do đó, thay vì chỉ đưa ra cảnh báo (`warn`) và cho phép dữ liệu bẩn đi vào Vector Store, tôi quyết định dùng cơ chế `halt` để dừng ngay pipeline nếu phát hiện vi phạm. 

Quyết định này ép buộc hệ thống phải "fail fast". Điều này được chứng minh qua log của `run_id=inject-bad`, trong đó expectation này đã `FAIL (halt)` với 1 violation, ngăn chặn việc publish im lặng dữ liệu sai lệch. Mặc dù trong demo Sprint 3 chúng tôi dùng `--skip-validate` để quan sát lỗi, nhưng trong môi trường production, `halt` là chốt chặn an toàn bắt buộc để giữ vững tính integrity của Knowledge Base.

---

## 3. Một lỗi hoặc anomaly đã xử lý (100–150 từ)

Tôi đã phát hiện và xử lý một lỗi về **Data Freshness** trong quá trình kiểm thử `run_id=inject-bad`. Khi chạy lệnh kiểm tra freshness, hệ thống báo trạng thái `FAIL` với thông tin: `age_hours: 121.406` vượt quá `sla_hours: 24.0`.

**Triệu chứng:** Kết quả retrieval đối với câu hỏi về refund (`q_refund_window`) vẫn trả về nội dung chứa "14 ngày" (stale) dù pipeline chuẩn đã chạy.
**Phát hiện:** Tôi sử dụng công cụ `freshness_check.py` để phân tích manifest. Timestamp `latest_exported_at` thu được từ file `manifest_inject-bad.json` là ngày cũ (2026-04-10), dẫn đến dữ liệu bị coi là quá hạn SLA.
**Xử lý:** 
1. Tôi đã cập nhật lại quy trình trong **Runbook** (mục 101/FAIL) yêu cầu rerun pipeline với dữ liệu snapshot mới nhất. 
2. Thực hiện xóa manifest cũ và chạy lại luồng chuẩn (`run_id=clean-after-bad`).
3. Sau khi rerun, `age_hours` giảm về mức < 1 giờ, và trạng thái freshness chuyển sang `PASS`. Việc này giúp đảm bảo toàn bộ kết quả retrieval sau đó đều dựa trên dữ liệu canonical mới nhất.

---

## 4. Bằng chứng trước / sau (80–120 từ)

Tôi sử dụng metric `hits_forbidden` trong file eval để chứng minh hiệu quả của việc kiểm soát chất lượng qua contract. Với `run_id=inject-bad`, do bỏ qua validation, dữ liệu stale đã lọt vào index.

**Trước fix (run_id: inject-bad):**
```csv
question_id,question,hits_forbidden
q_refund_window,Khách hàng có bao nhiêu ngày...,yes
```
*Ghi chú: Log `run_inject-bad.log` dòng 22 báo `freshness_check=FAIL` và dòng 9 báo `stale_14d_window FAIL`.*

**Sau fix (run_id: clean-after-bad):**
```csv
question_id,question,hits_forbidden
q_refund_window,Khách hàng có bao nhiêu ngày...,no
```
Kết quả `hits_forbidden=no` chứng minh dữ liệu bẩn đã bị loại bỏ thành công nhờ cơ chế prune và validation mà tôi đã thiết lập trong contract và monitoring suite.

---

## 5. Cải tiến tiếp theo (40–80 từ)

Nếu có thêm 2 giờ, tôi sẽ triển khai việc **đa tầng SLA freshness**. Thay vì chỉ có một ngưỡng 24h, tôi sẽ thêm vùng `WARN` (24h - 48h) và `FAIL` (>48h). Đồng thời, tôi sẽ tích hợp thông báo tự động qua Slack/Teams mỗi khi manifest sinh ra có `age_hours` tiệm cận ngưỡng SLA, giúp đội vận hành chủ động rerun pipeline trước khi dữ liệu kịp trở nên "stale" đối với người dùng cuối. 
