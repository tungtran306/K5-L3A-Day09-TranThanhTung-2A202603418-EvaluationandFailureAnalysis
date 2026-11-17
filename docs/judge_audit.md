# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5`

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | ĐẠT (κ=0.757 ≥ 0.6, P=0.857 ≥ 0.8, R=0.800 ≥ 0.7) | DÙNG |
| helpful | 100 | 0.375 | 1.000 | 0.300 | KHÔNG ĐẠT (κ=0.375 < 0.6, Recall=0.300 < 0.7) | LOẠI (không dùng làm gate) |

## ≥5 case audit thủ công

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú & Hành động sửa Rubric |
|---|---|---|---|---|---|
| 1 | H-008 | PASS | FAIL | Người đúng | Bot dùng từ xưng hô suồng sã "Em/anh", chêm từ "nha", "check" thay vì quy chuẩn xưng hô "LogiX/quý khách". Cần thêm quy tắc cấm ngôn ngữ thân mật/suồng sã vào rubric judge tone. |
| 2 | H-017 | PASS | FAIL | Người đúng | Bot xưng hô "bạn ơi", "rồi nha" thiếu tính trang trọng, chuyên nghiệp của doanh nghiệp logistics. Cần định nghĩa rõ danh sách từ cảm thán không phù hợp trong prompt judge. |
| 3 | H-029 | PASS | FAIL | Người đúng | Bot bảo khách "không cần nhắn thêm" với giọng điệu cộc lốc, gây ức chế cho người dùng. Sửa rubric judge để phạt nặng thái độ gắt gỏng, thiếu tôn trọng khách hàng. |
| 4 | H-042 | FAIL | PASS | Người đúng | Bot trả lời chuẩn mực lịch sự "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ". Judge bắt lỗi nhầm do câu có mốc ngày xử lý. Cần nới lỏng rubric: cho phép thông tin thời gian ước tính hợp lý. |
| 5 | H-051 | FAIL | PASS | Người đúng | Bot dùng từ mượn "refund" thay vì "hoàn tiền", câu văn vẫn hoàn toàn chuẩn mực và lễ phép. Judge quá nhạy cảm với từ ngoại lai. Sửa rubric chấp nhận các thuật ngữ thương mại phổ biến. |
| 6 | HL-016 | PASS | FAIL | Người đúng | Bot chỉ lặp lại câu xin lỗi mẫu (boilerplate) mà không cung cấp giải pháp hay thông tin đơn hàng cụ thể. Judge helpful bị đánh lừa bởi độ dài và sự lịch sự bề ngoài. |

## Kết luận
- **Tiêu chí bị loại:** `helpful` bị LOẠI hoàn toàn khỏi CI gate.
  - Ma trận nhầm lẫn: `{"tp": 9, "fp": 0, "fn": 21, "tn": 70}` trên 100 mẫu.
  - Tỉ lệ bỏ lọt lỗi nghiêm trọng: Recall chỉ đạt 30% (bỏ sót 21/30 trường hợp câu trả lời vô dụng, unhelpful). Hệ số Cohen's Kappa chỉ đạt 0.375 (rất thấp so với sàn 0.6).
  - Nếu đưa `judge_helpful` vào CI gate, 70% các câu trả lời hời hợt, né tránh hoặc sáo rỗng sẽ lọt qua kiểm duyệt mà không bị phát hiện.
- **Tiêu chí được chấp nhận:** `tone_ok` đạt chuẩn hiệu chuẩn với độ tin cậy cao (κ=0.757, P=0.857, R=0.800), đủ điều kiện đưa vào hệ thống giám sát chất lượng phản hồi.
- **Rủi ro còn lại:** Cả hai judge hiện chỉ được hiệu chuẩn trên tập dữ liệu replay công khai; trong vận hành thực tế cần định kỳ lấy mẫu ngẫu nhiên từ production với nhãn người độc lập (held-out dataset) để giám sát hiện tượng drift và false negative.
