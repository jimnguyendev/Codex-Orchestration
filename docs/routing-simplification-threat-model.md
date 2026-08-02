# Mô hình đe dọa khi đơn giản hóa routing

## Phạm vi và tài sản

Phiên bản 0.10.0 chuyển workflow mặc định thành một lần phân loại task, một
handoff có giới hạn sang Luna Max hoặc Terra Max, rồi Root tự xác minh. Tài sản
cần bảo vệ gồm: lane chính xác, phạm vi file, contract của task, quyền của người
dùng, routing state cũ và bằng chứng trung thực về model đã chạy.

## Đe dọa và kiểm soát

| Đe dọa | Kiểm soát và bằng chứng |
| --- | --- |
| Việc rủi ro bị đưa cho Luna | Policy liệt kê security/auth/state, destructive operation, migration, concurrency, legacy contract mơ hồ, broad refactor và blast radius lớn là Terra. Không chắc thì chọn Terra. Test kiểm tra exact Terra Max route. |
| Saved Luna Executor bắt luôn việc khó | Managed hints 0.10 có marker hai lane và pin Terra Max cho hard/risky. Policy trước 0.10 thiếu marker phải làm strict status thất bại cho đến khi fresh setup hoặc disable. |
| Fresh setup lưu route routine không phải Luna Max | Argument validation chỉ nhận `gpt-5.6-luna@max`; custom hoặc model/effort khác fail trước App Server write. State cũ khác route chỉ còn status/repair/disable compatibility. |
| Configured Planner/Advisor tự sinh thêm vòng gọi | Managed mode và usage hint ghi rõ config không đồng nghĩa invoke. Chỉ current-task request hoặc repository/risk gate mới được gọi; regression test cấm ngôn ngữ auto-loop cũ. |
| Token tăng vì copy context | Child dùng `fork_turns=none`; packet chỉ có năm mục và mặc định dưới 1.200 từ. Không copy toàn bộ transcript, plan, log hoặc file mà worker tự đọc được. |
| Gọi Luna rồi Terra theo kiểu đua | Chọn một lane trước spawn. Nếu Luna phát hiện rủi ro ẩn, Luna phải dừng; Root chỉ được sửa packet và thử Terra tối đa một lần. |
| Handoff lạnh bị quảng bá thành prewalk/cache handoff | Tài liệu tách rõ cold child handoff và same-session prewalk; không tuyên bố KV cache chuyển giữa model. |
| Kimi/provider state còn sót trong package | Xóa OpenRouter manifest, credential helpers, configurator, registry/recovery, External Model reference và test suite tương ứng. Packaging tests kiểm tra các path đó không tồn tại. |
| Generic custom-role helper tái tạo OpenRouter | Retire provider flags trước mọi write. 0.10 chỉ tạo active-provider role không có `model_provider`; existing managed provider-pinned file chỉ còn đường inspect/remove. Test dùng OpenRouter đã có trong config và xác nhận không tạo file. |
| Người dùng Fable/Opus mất sealed route | Giữ hai provider manifest, subscription dispatcher, MCP bridge, launcher config và test contract. |
| Marker-only migration làm rơi sealed seat | Khi policy/state cũ còn khớp và chỉ thiếu marker 0.10, setup bảo toàn exact Fable/Opus route bị omitted. Fable và Opus đều có regression riêng. |
| State cũ không thể repair/disable | Giữ exact schema validators, CAS, lock, restore snapshot, repair/disable và compatibility-only fallback. |
| Runtime route bị nói quá bằng chứng | Chỉ báo `route accepted` khi spawn API nhận đúng route; chỉ báo `used and confirmed` khi host expose effective model/effort. |
| Payload mới dùng lại cache identity cũ | Tăng mọi plugin identity lên 0.10.0; lifecycle smoke cài fixture lịch sử 0.5.0 rồi upgrade lên package 0.10.0 và xác nhận cache path/payload mới. |

## Negative và malformed paths bắt buộc

- Unknown field, sai schema/policy, route binding lệch hoặc marker thiếu phải fail
  closed.
- Model/effort không có trong active catalog không được tự đổi sang model khác.
- User-authored hint không được ghi đè nếu thiếu `--replace-existing-policy`.
- Concurrent config/state change phải giữ thay đổi mới và rollback phần plugin.
- Mất saved restore state phải làm repair/disable fail trước write, kể cả khi marker
  vẫn còn; config được kiểm tra byte-for-byte trong negative test.
- Permission, auth, timeout, cancellation và task error không được biến thành
  fallback signal.
- Child đã có provenance không được kích hoạt retry legacy.

## Rủi ro còn lại

Codex hiện tạo child mới cho task-local model routing, nên 0.10.0 không thể cung
cấp same-session prewalk thật. Runtime identity phụ thuộc metadata của host.
Designer và các field fallback cũ vẫn nằm trong validator để upgrade/disable an
toàn, dù không còn thuộc default workflow.
