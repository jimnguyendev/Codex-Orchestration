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
| Số file bị hiểu thành hard Luna limit | File count chỉ là tín hiệu phụ. Thay đổi mechanical/low-risk có một contract thống nhất trong cùng module vẫn có thể là Luna dù chạm hơn ba file; contract, state boundary, ambiguity và blast radius mới quyết định lane. |
| Slice stateful bị gọi là routine chỉ vì ownership đã khóa | Warm-root gate giữ việc ở Root khi Root đã có context hoặc dirty paths đang tích hợp. Slice gồm schema + migration + seed + API + tests bắt buộc là Terra/state work dù ownership đã khóa hoặc số file ít. |
| Luna đọc lặp lại nhưng chưa tạo artifact | Packet có `FIRST ARTIFACT` và `READ BUDGET`: tối đa ba lượt đọc theo batch trước edit/test đầu tiên; trong 120 giây phải tạo artifact nhỏ nhất hoặc trả `BLOCKED`. Các giới hạn thời gian, lượt đọc và token là policy instruction/stop condition của orchestration, không phải giới hạn được host cưỡng chế. |
| Root coi im lặng là stall dù child đã sửa file | Đến progress gate, Root đọc diff của owned paths trước khi nhắn hoặc kết luận. Artifact trên shared worktree là evidence kể cả khi child chưa gửi checkpoint. |
| Interrupt làm mất attribution hoặc Root sửa chồng | Root snapshot diff trước interrupt, cho checkpoint cuối tối đa 60 giây, chờ child terminal, snapshot lại, reconcile partial edits rồi mới nhận ownership. Không được nói “không có thay đổi” hoặc chạm cùng path trước handoff. |
| Saved Luna Executor bắt luôn việc khó | Managed hints 0.10 có marker hai lane và pin Terra Max cho hard/risky. Policy trước 0.10 thiếu marker phải làm strict status thất bại cho đến khi fresh setup hoặc disable. |
| Fresh setup lưu route routine không phải Luna Max | Argument validation chỉ nhận `gpt-5.6-luna@max`; custom hoặc model/effort khác fail trước App Server write. State cũ khác route chỉ còn status/repair/disable compatibility. |
| Configured Planner/Advisor tự sinh thêm vòng gọi | Routine mặc định dùng 0 Planner/Advisor call. Mỗi task chỉ có budget mặc định tối đa một Planner-or-Advisor model call khi current-task request hoặc repository/risk gate yêu cầu; exact final-tree gate phải giữ lượt đó tới cây cuối. Finding/`PLAN_REVISE` không tự cấp lượt thứ hai, Root phải hỏi người dùng trước khi re-review bằng model. |
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
- Luna vượt read budget mà chưa có artifact phải trả `BLOCKED`; Root chỉ được gửi
  một checkpoint request trước khi dừng.
- Interrupt không được chuyển ownership cho Root cho tới khi child terminal và hai
  snapshot owned-path diff đã được reconcile.
- Routine task hoặc configured seat không được tự tạo Planner/Advisor call. Lượt thứ
  hai sau finding/`PLAN_REVISE` phải dừng trước model call nếu chưa có current-task
  user authorization rõ ràng.

## Rủi ro còn lại

Codex hiện tạo child mới cho task-local model routing, nên 0.10.0 không thể cung
cấp same-session prewalk thật. Runtime identity phụ thuộc metadata của host.
Designer và các field fallback cũ vẫn nằm trong validator để upgrade/disable an
toàn, dù không còn thuộc default workflow.
