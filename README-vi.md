# Codex Orchestration — Hướng dẫn tiếng Việt

Codex Orchestration giữ model đang được chọn trong task làm Root và chỉ chia phần
implementation sang hai lane rõ ràng:

- **GPT-5.6 Luna Max** cho việc routine, phạm vi hẹp, yêu cầu đã rõ và rủi ro thấp.
- **GPT-5.6 Terra Max** cho việc khó, còn mơ hồ hoặc rủi ro cao.
- **GPT-6 Astra** (`gpt-6-astra`) giữ việc hard/risky ở Root khi đây là model của
  task; plugin không hạ tuyến xuống Terra.

Root vẫn chịu trách nhiệm hiểu yêu cầu, quyết định kiến trúc, tích hợp thay đổi, chạy
kiểm tra và trả kết quả cuối. Plugin không tự động tạo Planner, Advisor, Designer hay
vòng final review cho mọi task.

Đây là fork được duy trì độc lập tại
[`jimnguyendev/Codex-Orchestration`](https://github.com/jimnguyendev/Codex-Orchestration),
dựa trên project gốc của CJ Zafir và tiếp tục dùng giấy phép MIT.

## Cách chọn lane

| Dạng công việc | Lane |
| --- | --- |
| Sửa cơ học, wiring, CRUD, test thẳng, bug cục bộ | Luna Max |
| Security/auth/state, concurrency, migration, debug khó, refactor rộng, legacy contract chưa rõ | Terra Max |
| Cùng loại việc hard/risky khi GPT-6 Astra đã là Root | Giữ ở Astra Root |

Với Root không phải Astra, nếu chưa chắc thì chọn Terra. Chỉ route Astra child khi
catalog callable hiện tại có đúng ID `gpt-6-astra`; nếu không thì fail closed. Việc quá
nhỏ nên để Root làm trực tiếp vì chi phí handoff có thể lớn hơn phần việc.

Worker chỉ nhận packet gồm năm phần: mục tiêu, file sở hữu, contract, điều kiện hoàn
thành và cách kiểm tra. Child khác model dùng `fork_turns=none`, không nhận toàn bộ hội
thoại của Root. Đây là cold handoff có giới hạn, không phải same-session prewalk của
Elves và không chuyển KV cache giữa model.

Sau khi worker xong, Root phải xem diff thật và chạy lại kiểm tra liên quan. Báo cáo của
worker không phải bằng chứng cuối cùng.

Số file chỉ là tín hiệu phụ, không phải hard limit của Luna: thay đổi routine trong một
module có thể chạm hơn ba file. Routine mặc định dùng 0 Planner/Advisor call; mọi task
đều có budget mặc định tối đa một call khi người dùng hoặc repository/risk gate yêu
cầu. Muốn model review lần hai phải có current-task approval rõ ràng.

Tài liệu đầy đủ bằng tiếng Việt, gồm sơ đồ kiến trúc, same-session prewalk, phép tính
chi phí/cache, threat model và hướng dẫn từng bước, nằm tại
[`docs/README.md`](docs/README.md).

## Cài đặt

Yêu cầu Codex client hỗ trợ plugin và multi-agent v2. Python 3.11+ chỉ cần cho persistent
setup tùy chọn.

```bash
codex plugin marketplace add jimnguyendev/Codex-Orchestration
codex plugin add codex-orchestration@codex-orchestration
codex plugin list --json
```

Inventory phải cho thấy plugin enabled, source là Git marketplace chính thức của fork,
và version 0.11.0 trở lên. Sau khi cài hoặc update, hãy thoát hoàn toàn Codex rồi mở lại
và tạo task mới.

Ví dụ sử dụng:

```text
$codex-orchestration:codex-orchestration route implementation này
$codex-orchestration:codex-orchestration dùng Luna Max vì task này routine
$codex-orchestration:codex-orchestration dùng Terra Max vì migration này rủi ro cao
```

## Persistent setup là tùy chọn

Task-local routing là mặc định. Persistent setup lưu Luna làm routine route và sinh
thêm Terra Max hard/risky lane trong managed policy. Phiên bản 0.11 chỉ nhận đúng Luna
Max làm persistent Executor; route Executor tùy ý/custom chỉ dùng task-local:

```text
$codex-orchestration:codex-orchestration setup executor: GPT-5.6 Luna Max
```

Các thao tác quản lý:

```text
$codex-orchestration:codex-orchestration status
$codex-orchestration:codex-orchestration repair
$codex-orchestration:codex-orchestration --update
$codex-orchestration:codex-orchestration disable
```

Setup, repair và disable đều preview trước khi ghi. Configurator dùng Codex App Server
compare-and-swap, giữ nguyên setting không liên quan và lưu chính xác dữ liệu để restore.
Status chỉ chứng minh policy/state khớp nhau, không chứng minh child route đang callable.
Sau khi upgrade policy được tạo trước 0.11, strict status sẽ báo `legacy workflow
active`; hãy chạy một fresh setup hoặc disable policy cũ trước khi dựa vào hai lane mới.
Marker-only migration giữ nguyên Fable/Opus seat hợp lệ nếu fresh setup không nhắc lại
seat đó. Nếu saved state đã mất, status phải báo repair và disable không còn dùng được.

## Fable và Opus vẫn được giữ

Claude Fable 5.1 và Claude Opus 5 vẫn là route Planner hoặc Advisor tùy chọn. Chúng
dùng Claude Code CLI chính thức với login first-party Pro, Max hoặc Team hiện có,
không dùng tools, không giữ session và kiểm tra đúng model runtime. Fresh setup Fable
pin `claude-fable-5-1`; state `claude-fable-5` cũ vẫn tương thích. Plugin không tự gọi
hai route này và không dùng chúng làm implementation worker.

```text
$codex-orchestration:codex-orchestration setup planner: Claude Fable 5.1 High, executor: GPT-5.6 Luna Max
$codex-orchestration:codex-orchestration setup advisor: Claude Opus 5 High, executor: GPT-5.6 Luna Max
```

Chỉ một bundled Claude subscription seat được lưu. Fable 5.1 yêu cầu Claude Code
2.1.255+; Opus yêu cầu 2.1.219+. Setup/status không gọi model Claude.

## Phần đã gỡ ở 0.10.0

Kimi K3, OpenRouter setup, credential enrollment, paid Gate 0 probe và toàn bộ generic
External Model lifecycle đã được gỡ. Kimi là API-model route duy nhất được bundle và
là nguồn tạo ra phần lớn nhánh hướng dẫn, runtime và test không còn cần thiết.

Saved Executor fallback cũ vẫn được đọc để tương thích state, nhưng không còn được dùng
như cơ chế phân loại Luna/Terra. Task mới chọn lane ngay trước khi spawn.

## Token, chi phí và tốc độ

Không có một phần trăm tiết kiệm cố định. Cần tính tổng model-weighted input/output,
context bị lặp, reasoning output, tool call, retry, latency và rework do chất lượng.

Giảm reasoning level của Root có thể giữ cơ hội cache cùng model và giảm reasoning.
Luna vẫn có thể rẻ hơn sau cold handoff nhờ đơn giá thấp hơn. Nên benchmark trên task
thật và kiểm tra bảng giá hiện tại trước khi công bố con số cụ thể.

## Phát triển và kiểm tra

```bash
python3 scripts/preflight.py quick
python3 scripts/preflight.py full
```

Mỗi behavior fix cần regression test chính xác. Thay đổi plugin payload phải tăng
SemVer. Thay đổi security/state cần threat model, test negative/malformed và final-tree
review mới gắn với đúng head SHA. Kết quả local là `PARTIAL`; protected checks trên CI
mới là nguồn xác nhận cuối cùng.

## Giấy phép

Project gốc do CJ Zafir phát triển. Fork này tiếp tục phát hành theo giấy phép MIT;
xem [LICENSE](LICENSE).
