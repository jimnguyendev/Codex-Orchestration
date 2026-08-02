# Tài liệu Codex Orchestration

Thư mục này mô tả đầy đủ kiến trúc và cách vận hành phiên bản 0.10.0 bằng tiếng
Việt. README ở root là bản giới thiệu ngắn; đây là nơi tra cứu contract chi tiết.

## Plugin giải quyết bài toán gì?

Một model mạnh làm toàn bộ task thường tốn nhiều credits và thời gian cho phần
implementation cơ học. Ngược lại, giao task thiếu context cho model rẻ có thể làm
tăng rework. Workflow nhiều role cố định còn làm phát sinh planning, review và
context duplication ngay cả khi task đơn giản.

Codex Orchestration chọn một thiết kế nhỏ hơn:

- Root đang được chọn trong task giữ toàn bộ quyền quyết định.
- Việc routine, rõ contract, rủi ro thấp đi Luna Max.
- Việc khó, mơ hồ hoặc rủi ro cao đi Terra Max.
- Task quá nhỏ ở lại Root.
- Planner/Advisor chỉ chạy khi người dùng hoặc repository gate yêu cầu.
- Mỗi child nhận packet ngắn và Root kiểm tra lại kết quả thật.

Mục tiêu là giảm model-weighted cost và latency mà không đổi lấy silent downgrade,
scope drift hoặc tuyên bố route thiếu bằng chứng.

## Bản đồ tài liệu

| Tài liệu | Nội dung |
| --- | --- |
| [Kiến trúc](architecture.md) | Thành phần, luồng routing, trust boundary và evidence levels. |
| [Same-session prewalk](same-session-prewalk.md) | Prewalk thật hoạt động ra sao, vì sao child handoff hiện tại không phải prewalk. |
| [Chi phí, cache và tốc độ](cost-cache-speed.md) | Công thức so sánh, ví dụ Luna/Sol, cache boundary và cách benchmark. |
| [Hướng dẫn sử dụng](usage-guide.md) | Cài đặt, task-local, persistent setup Fable–Sol–Luna, status, repair và disable. |
| [Threat model routing](routing-simplification-threat-model.md) | Rủi ro của workflow hai lane và negative tests. |
| [Threat model fallback cũ](executor-fallback-threat-model.md) | Contract tương thích cho saved Executor fallback schema 5/6. |
| [Kiểm toán phát hành](production-readiness-audit.md) | Provenance kiểm toán, gate local/hosted và ranh giới production. |

## Nguyên tắc không thay đổi

1. Không có route chính xác thì báo unavailable; không tự thay model hoặc effort.
2. Worker report là claim, không phải acceptance evidence.
3. Configured không đồng nghĩa callable; accepted không đồng nghĩa runtime-confirmed.
4. Plugin không tạo credential, không nới sandbox/approval và không đổi Root model.
5. Cài/update/setup xong phải mở task mới để plugin, MCP và policy cùng được load.
