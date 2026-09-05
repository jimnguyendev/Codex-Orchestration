# Mô hình đe dọa của Executor fallback cũ

## Phạm vi

Tài liệu này mô tả cơ chế fallback được lưu trong routing state schema 5 và 6.
Từ phiên bản 0.10.0, đây chỉ là lớp tương thích để đọc, sửa hoặc tắt policy cũ.
Workflow mới không dùng fallback để quyết định Luna hay Terra.

Tài sản cần bảo vệ là request ủy quyền chính xác của Root: model và effort dự
kiến, các trường spawn còn lại, giới hạn chạy một lần và bằng chứng trung thực
về việc fallback có được dùng hay không. Policy chỉ hướng dẫn model; nó không ép
Codex engine phải schedule, load hoặc gọi thành công một model.

## Đe dọa và biện pháp kiểm soát

| Đe dọa | Biện pháp và test bắt buộc |
| --- | --- |
| Hạ cấp model âm thầm | Fallback phải được người dùng bật rõ ràng, là direct model khác primary và chỉ được thử lại một lần. Override trong task hiện tại hoặc `no subagents` phải vô hiệu hóa fallback. |
| State bị sửa tay hoặc hỏng | Validator kiểm tra schema, policy version, exact top-level shape, route type, marker và canonical JSON binding trong cả hai managed hint. Field lạ, model trùng nhau hoặc custom-agent fallback đều bị từ chối. |
| Xung đột lịch sử schema 5 | Fork giữ schema 5 theo contract fallback; upstream từng dùng cùng số schema cho contract khác. Không đoán. Phải disable bằng phiên bản đã tạo state rồi setup mới. Schema 6 kết hợp fallback với Fable/Opus. |
| Giả mạo lỗi để kích hoạt fallback | Chỉ immediate result của `agents.spawn_agent`, chưa có child/agent provenance, với lỗi chuẩn hóa chính xác `Unknown model <primary>. Available models: <list>` và có đúng fallback mới đủ điều kiện. |
| Nhầm provenance | Chỉ cần đã có child/agent ID thì kết quả không còn đủ điều kiện. Output từ child, log, prompt hoặc lỗi task về sau không được kích hoạt retry. |
| Chạy implementation hai lần | Quyền retry được consume trước khi gọi fallback. Mọi field ngoài `model` và `reasoning_effort` phải giữ nguyên; sau retry phải dừng. |
| Race khi ghi config/state | Setup và disable dùng App Server version check, digest compare-and-swap và installer lock. State đổi giữa chừng phải được giữ nguyên, còn config write phải rollback. |
| Bỏ qua lock theo hệ điều hành | Chỉ ghi khi host có `fcntl` hoặc Windows `msvcrt` byte-range locking. Không có backend phù hợp thì dừng trước mutation. |
| Lệch version payload | Manifest, package, lifecycle fixture, validator và tài liệu phải cùng version 0.11.0. Release check từ chối version không đồng bộ hoặc state schema không biết. |

Permission, authentication, provider, rate limit, timeout, cancellation và lỗi
thực thi thông thường đều là negative case: không retry và báo thất bại.

## Ranh giới còn lại

- Một policy hợp lệ không chứng minh child route callable trong task hiện tại.
- Setup/status không chứng minh runtime model identity.
- Host không expose metadata thì chỉ được báo `route accepted`, không được báo
  `used and confirmed`.
- Classification mới phải chọn Luna Max hoặc Terra Max trước spawn. Fallback cũ
  không phải bộ phân loại độ khó.
