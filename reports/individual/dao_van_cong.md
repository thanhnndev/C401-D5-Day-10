# Báo Cáo Cá Nhân — Lab Day 10: Data Pipeline & Observability

**Họ và tên:** Đào Văn Công 
**Vai trò:** Quality  
**Ngày nộp:** 15/04/2026  
**Độ dài yêu cầu:** **400–650 từ** (ngắn hơn Day 09 vì rubric slide cá nhân ~10% — vẫn phải đủ bằng chứng)

---

> Viết **"tôi"**, đính kèm **run_id**, **tên file**, **đoạn log** hoặc **dòng CSV** thật.  
> Nếu làm phần clean/expectation: nêu **một số liệu thay đổi** (vd `quarantine_records`, `hits_forbidden`, `top1_doc_expected`) khớp bảng `metric_impact` của nhóm.  
> Lưu: `reports/individual/[ten_ban].md`

---

## 1. Tôi phụ trách phần nào? (80–120 từ)

**File / module:**

- tôi triển khai `quality/expectations.py` (E7, E8, E9, E10, E11), mục đích là để kiểm định chặt chẽ dữ liệu sau khi được clean.

- các expectation:
    - E7 : `no_bom_in_chunk_text`
    - E8 : `no_duplicate_chunks`
    - E9 : `chunk_max_length_2000`
    - E10 : `no_residual_html_tags`
    - E11 : `core_documents_present`

**Bằng chứng (commit / comment trong code):**

- commit : 

    - "feat: write code for inspecting quaily of cleaned data" 

    - "feat: added more expectations for quality/expectations.py"

---

## 2. Một quyết định kỹ thuật (100–150 từ)

> VD: chọn halt vs warn, chiến lược idempotency, cách đo freshness, format quarantine.

```text
Phân loại mức độ nghiêm trọng cho từng expectation: 
    
    - Các lỗi như : thiếu tài liệu cốt lõi (E11) hoặc dữ liệu bị rỗng, sai định dạng ngày tháng sẽ để mức “halt” để pipeline dừng lại ngay, tránh phát sinh lỗi ngầm về sau. 
    
    - Các lỗi như chunk_text chứa BOM (E7), chunk trùng lặp (E8), chunk quá dài (E9), hoặc còn sót HTML (E10) tôi để mức “warn” để cảnh báo nhưng không dừng pipeline, giúp xử lý thủ công hoặc cải tiến sau.

    => giúp pipeline vừa an toàn, vừa không bị “quá nhạy” với các lỗi nhỏ, đồng thời vẫn đảm bảo không bỏ sót lỗi nghiêm trọng.
```

---

## 3. Một lỗi hoặc anomaly đã xử lý (100–150 từ)

> Mô tả triệu chứng → metric/check nào phát hiện → fix.

Trong quá trình phát triển và kiểm thử module quality/expectations.py, tôi đã phát hiện và xử lý một số lỗi dữ liệu nhờ các expectation mới. 

- Expectation E8 (no_duplicate_chunks) giúp tôi phát hiện có chunk bị trùng lặp nội dung trong cùng một doc_id ở các bản pipeline đầu tiên.

- Expectation E11 (core_documents_present) cũng từng cảnh báo thiếu tài liệu cốt lõi khi tôi thử xóa chunk của một doc_id, giúp tôi nhận ra pipeline cần kiểm tra đủ tài liệu quan trọng trước khi embed

Các cái này đều ghi trong log `run_run-idempotent-1.log`

"expectation[no_duplicate_chunks] OK (warn) :: duplicate_chunk_ids=[]"

"expectation[core_documents_present] OK (halt) :: missing_docs=[]"

---

## 4. Bằng chứng trước / sau (80–120 từ)

> Dán ngắn 2 dòng từ `before_after_eval.csv` hoặc tương đương; ghi rõ `run_id`.

> Trong file `run_inject-bad.log`

- với run_id=inject-bad (log: run_inject-bad.log), expectation E7–E11 đều trả về OK, không còn lỗi:

expectation[no_bom_in_chunk_text] OK (warn) :: bom_chunks=0

expectation[no_duplicate_chunks] OK (warn) :: duplicate_chunk_ids=[]

expectation[chunk_max_length_2000] OK (warn) :: oversized_chunks=0

expectation[no_residual_html_tags] OK (warn) :: dirty_html_chunks=0

expectation[core_documents_present] OK (halt) :: missing_docs=[]

> So sánh kết quả eval trước/sau (artifacts/eval/origin.csv với after_inject_bad.csv):

- Trước: q_leave_version trả về doc_id sai, top1_doc_expected=no

- Sau: q_leave_version trả về đúng doc_id, top1_doc_expected=yes

---

## 5. Cải tiến tiếp theo (40–80 từ)

> Nếu có thêm 2 giờ — một việc cụ thể (không chung chung).

- Bổ sung expectation để kiểm thử các facts quan trọng không bị mất mát (ví dụ: “15 phút” trong SLA, “12 ngày” trong HR), và tự động sinh báo cáo metric_impact cho từng expectation để nhóm dễ theo dõi tác động của từng rule lên dữ liệu thực tế.
