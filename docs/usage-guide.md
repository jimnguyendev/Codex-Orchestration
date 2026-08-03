# Hướng dẫn sử dụng từng bước

## 1. Cài plugin

```bash
codex plugin marketplace add jimnguyendev/Codex-Orchestration
codex plugin add codex-orchestration@codex-orchestration
codex plugin list --json
```

Kiểm tra plugin ở trạng thái enabled, source trỏ đến marketplace Git chính thức
của fork và version là 0.10.0 trở lên. Sau khi cài/update, thoát hoàn toàn Codex,
mở lại và tạo task mới.

## 2. Dùng task-local routing

Đây là cách mặc định, không ghi persistent policy:

```text
$codex-orchestration:codex-orchestration route implementation này
```

Root phân loại:

- task quá nhỏ: Root tự làm;
- routine, contract rõ, rủi ro thấp: Luna Max;
- khó, mơ hồ, security/state/migration/concurrency: Terra Max.

Có thể override rõ ràng trong task hiện tại:

```text
$codex-orchestration:codex-orchestration dùng Luna Max cho phần CRUD này
$codex-orchestration:codex-orchestration dùng Terra Max vì migration này có rủi ro dữ liệu
$codex-orchestration:codex-orchestration không dùng subagents
```

Override không được lưu sang task sau.

## 3. Persistent setup Fable–Sol–Luna

Cấu hình người dùng yêu cầu:

- Planner: Claude Fable 5, High;
- Advisor: GPT-5.6 Sol, High;
- routine Executor: GPT-5.6 Luna, Max;
- hard/risky lane: GPT-5.6 Terra, Max do policy 0.10 pin sẵn.

Fresh persistent setup chỉ nhận đúng Luna Max. Executor model khác, effort khác hoặc
custom Executor đều fail trước khi ghi config; các route đó vẫn có thể dùng task-local.

Từ skill, yêu cầu tự nhiên là:

```text
$codex-orchestration:codex-orchestration setup planner: Claude Fable 5 High, advisor: GPT-5.6 Sol High, executor: GPT-5.6 Luna Max
```

Configurator tương ứng phải được chạy preview trước:

```bash
python3 <skill-dir>/scripts/configure_native_routing.py \
  --codex-bin <active-codex-binary> \
  --planner-fable \
  --planner-effort high \
  --advisor-model gpt-5.6-sol \
  --advisor-effort high \
  --executor-model gpt-5.6-luna \
  --executor-effort max
```

Chỉ khi preview sạch mới thêm `--apply`. Không thêm
`--allow-incompatible-client`, `--replace-existing-policy` hoặc
`--confirm-unlisted-models` nếu chưa có lý do và quyền rõ ràng.

Fable dùng Claude Code CLI chính thức và login first-party hiện có. Setup không
tạo credential. Fable và Sol chỉ là seat tùy chọn; cấu hình xong vẫn không tự gọi
chúng nếu task hiện tại không yêu cầu planning/review hoặc repository gate không
bắt buộc.

Routine task mặc định dùng 0 Planner/Advisor call. Mọi task có budget mặc định tối
đa một Planner-or-Advisor model call. Nếu repo cần exact final-tree review, giữ lượt
đó tới cây cuối. Finding hoặc `PLAN_REVISE` không tự mở lượt thứ hai; Root phải
hỏi người dùng trước khi gọi model re-review. Số file cũng không phải hard Luna
limit: thay đổi mechanical/low-risk trong một module vẫn có thể chạm hơn ba file.

## 4. Xác nhận policy

```bash
python3 <skill-dir>/scripts/configure_native_routing.py \
  --codex-bin <active-codex-binary> \
  --status --require-effective
```

Kết quả này chứng minh config và saved state nhất quán. Nó chưa chứng minh child
route thực tế đã chạy. Cần task mới và exact child call để nâng evidence thành
`route accepted`; cần runtime metadata để báo `used and confirmed`.

Nếu status báo `legacy workflow active`, policy được tạo trước 0.10. Hãy chạy một
fresh explicit setup để migrate managed hints hoặc disable policy cũ. Migration chỉ
đổi marker/hints sẽ giữ nguyên Fable hoặc Opus seat hợp lệ nếu command mới không nhắc
lại seat đó. Nếu status báo hints còn nhưng saved state đã mất, repair và disable không
khả dụng; review hints rồi chạy fresh setup để tạo state mới.

## 5. Dùng Planner và Advisor đúng lúc

Ví dụ yêu cầu rõ ràng:

```text
Hãy dùng Fable tạo kế hoạch cho migration này, Sol review kế hoạch một lần,
sau đó route implementation theo Luna/Terra.
```

Root giữ canonical plan. Planner và Advisor không nói chuyện trực tiếp, không sửa
implementation và không tự spawn agent. Không cần chúng cho task routine nhỏ.

## 6. Repair

Repair chỉ dùng khi exact managed mode/usage hints drift nhưng saved state vẫn hợp
lệ. Luôn preview rồi apply:

```bash
python3 <skill-dir>/scripts/configure_native_routing.py \
  --codex-bin <active-codex-binary> --repair
python3 <skill-dir>/scripts/configure_native_routing.py \
  --codex-bin <active-codex-binary> --repair --apply
```

Nếu ownership hoặc state mơ hồ, repair phải dừng thay vì ghi đè.

## 7. Disable

Disable khôi phục đúng giá trị trước setup:

```bash
python3 <skill-dir>/scripts/configure_native_routing.py \
  --codex-bin <active-codex-binary> --disable
python3 <skill-dir>/scripts/configure_native_routing.py \
  --codex-bin <active-codex-binary> --disable --apply
```

Plugin không xóa managed field đã bị bên khác thay đổi sau setup. Disable không
đụng credential, chat, session hoặc custom role thuộc người dùng.
Nếu managed hints còn nhưng saved restore state đã mất, disable fail closed và giữ
config byte-for-byte; hãy fresh setup Luna Max sau khi review hoặc tự xử lý stale hints.

## 8. Update

```text
$codex-orchestration:codex-orchestration --update
```

Update chỉ chấp nhận canonical marketplace của fork. Sau update phải restart và
tạo task mới; task đã load không hot-reload skill, MCP bridge hoặc policy.

## 9. Xử lý lỗi thường gặp

| Triệu chứng | Ý nghĩa | Hành động |
| --- | --- | --- |
| Exact model không có trong catalog | Route unavailable | Không tự fallback; kiểm tra đúng Codex host/version. |
| Fable status báo auth unavailable | Claude first-party login chưa sẵn sàng | Login bằng Claude Code ngoài plugin rồi chạy status lại. |
| Fable tool lỗi nhưng fresh status báo ready | Task đang giữ MCP bridge cũ | Thoát hoàn toàn Codex, mở lại, tạo task mới; không yêu cầu login lại. |
| `legacy workflow active` | Managed hints trước 0.10 | Fresh setup hoặc disable. |
| Policy conflict với user-authored hints | Plugin không sở hữu field | Dừng và review; chỉ replace khi người dùng chủ động cho phép. |
| Child không trả runtime metadata | Không đủ bằng chứng model thực tế | Báo `route accepted`, không báo `used and confirmed`. |

## 10. Phát triển plugin

```bash
python3 scripts/preflight.py quick
python3 scripts/preflight.py full
```

Thay đổi behavior cần regression test. Thay đổi payload cần bump SemVer. Thay đổi
security/state cần threat model, malformed/negative tests và fresh final-tree
review gắn với đúng head SHA. Local result là `PARTIAL`; hosted checks mới là gate
phát hành cuối.
