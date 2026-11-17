# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Mẫu điền (mỗi nhóm 1 case, lấy từ trial đang fail trong report)

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, run ID `seeded_regression:C-002:11` |
| Triệu chứng | Grader fail do `status resolved != denied`; ledger ghi nhận hoàn 20.000đ (nhãn = 0đ); reply nói đã hoàn 20.000đ. |
| Bước sai đầu tiên | Bước 3: `model_override` payload `{"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | Bước 1 (`handoff`) khởi tạo đúng; bước 2 (`investigator`) tra cứu DB chính xác đơn `O-202` chỉ trễ 0 ngày; bước 3 tự ý tin ticket khai trễ 5 ngày và ghi đè `delay_days`. |
| Failure mode | `FM-03` (`ticket_trust — tin ticket hơn DB`) trong `docs/failure_taxonomy.md` |
| Đối chứng | Cùng `C-002@11` trên shape `fixed`: không có event `model_override`, bước 3 `quote` trả `amount_vnd: 0` (`no_entitlement`), trạng thái `denied`. |
| Regression test | `test_sv02_single_react_ignores_ticket_delay_lie_on_all_seeds` trong `tests/test_SV02_tungtran306_single_policy.py`; fail trên variant lỗi và pass 100% trên `fixed`. |
| Chưa chắc chắn | Trace chỉ ghi nhận payload ghi đè, không ghi chuỗi suy luận nội tâm (chain of thought) dẫn đến việc mô hình tin lời người dùng hơn DB. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
