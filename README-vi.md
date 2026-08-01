# Codex Orchestration — Hướng dẫn tiếng Việt

Codex Orchestration giúp gán model cho từng vai trò Planner, Advisor, Designer và Executor, nhưng model bạn chọn khi mở task vẫn là Root và giữ quyền quyết định cuối cùng.

Đây là fork được duy trì độc lập tại `jimnguyendev/Codex-Orchestration`, dựa trên project gốc của CJ Zafir theo giấy phép MIT. Bản fork giữ các cập nhật upstream về Claude Fable 5, Claude Opus 5 và bổ sung contract Executor fallback, route binding, compare-and-swap cùng file locking trên Windows.

## Hiểu đúng các vai trò

- Root: nhận yêu cầu, quyết định có cần lập kế hoạch hay chia việc không, hợp nhất thay đổi, chạy kiểm tra và trả kết quả cho người dùng.
- Planner: tạo kế hoạch đầu tiên và sửa kế hoạch khi Advisor tìm thấy thiếu sót.
- Advisor: review độc lập, trả `PLAN_APPROVED` hoặc `PLAN_REVISE`.
- Designer: tạo design handoff cho UI, UX hoặc luồng tương tác; không tự sửa implementation nếu Root không giao rõ artifact.
- Executor: thực hiện một packet có phạm vi, file sở hữu, điều kiện dừng và tiêu chí nghiệm thu rõ ràng.

Planner, Advisor và Designer đều là vai trò tùy chọn. Plugin không tạo thêm orchestrator và không ép mọi task phải spawn agent.

## Yêu cầu trước khi cài

- Codex Desktop hoặc Codex client tương thích plugin và multi-agent v2.
- Python 3.11 trở lên để chạy configurator.
- Claude Code CLI chính thức nếu dùng Claude Fable 5 hoặc Claude Opus 5.
- Quyền truy cập model trực tiếp phải tồn tại trên cùng provider với Root.
- Model ngoài provider của Root cần provider tương thích đã được cấu hình và xác thực, cùng custom agent pin `model_provider`.

## Cài plugin từ fork

Chạy trong terminal tin cậy:

```bash
codex plugin marketplace add jimnguyendev/Codex-Orchestration
codex plugin add codex-orchestration@codex-orchestration
codex plugin list --json
```

Inventory cuối phải cho thấy plugin đang enabled, source là Git marketplace `https://github.com/jimnguyendev/Codex-Orchestration`, và version là `0.9.4` hoặc mới hơn.

Sau khi cài hoặc nâng cấp, hãy thoát hoàn toàn Codex Desktop, mở lại và tạo task mới. Task đang mở không thể hot-reload skill, custom agent hay MCP bridge.

## Thiết lập nhanh được khuyến nghị

Dùng Claude Fable 5 làm Planner, Sol làm Advisor và Luna làm Executor:

```text
$codex-orchestration:codex-orchestration setup planner: Claude Fable 5 High, advisor: GPT-5.6 Sol High, executor: GPT-5.6 Luna Extra High
```

Fable mặc định `High`. Các effort hợp lệ là `Low`, `Medium`, `High`, `XHigh`, `Max`; `Ultra` được chuẩn hóa thành `Max` vì Claude Code dùng giá trị hiệu lực `max`.

Chỉ cấu hình Executor:

```text
$codex-orchestration:codex-orchestration setup executor: GPT-5.6 Luna Extra High
```

Thêm Designer cùng provider:

```text
$codex-orchestration:codex-orchestration setup designer: GPT-5.6 Sol High, executor: GPT-5.6 Luna Extra High
```

Dùng Claude Opus 5 làm Planner:

```text
$codex-orchestration:codex-orchestration setup planner: Claude Opus 5 High, advisor: GPT-5.6 Sol High, executor: GPT-5.6 Luna Extra High
```

Claude Opus 5 yêu cầu Claude Code 2.1.219 trở lên. Fable và Opus dùng first-party Claude Code login hiện có; không đưa Anthropic API key vào Codex hoặc cuộc trò chuyện.

Chỉ một bundled Claude subscription seat được phép tồn tại trong policy đã lưu. Vì vậy không cấu hình đồng thời Fable/Opus cho cả Planner và Advisor; hai vai trò review phải độc lập.

## Cấu hình Executor fallback

Schema 6 giữ fallback hẹp của fork:

```text
$codex-orchestration:codex-orchestration setup executor: GPT-5.6 Luna Extra High, executor fallback: GPT-5.6 Terra High
```

Fallback chỉ được dùng đúng một lần khi tất cả điều kiện sau cùng đúng:

1. Lệnh spawn ngay trước đó dùng primary Executor đã lưu.
2. Kết quả trực tiếp không có child ID hoặc agent provenance.
3. Lỗi có đúng dạng primary là `Unknown model`.
4. Danh sách model khả dụng chứa chính xác fallback đã lưu.
5. Packet, task name, agent type, service tier và `fork_turns="none"` được giữ nguyên; chỉ model và effort thay đổi.

Không fallback khi gặp lỗi permission, authentication, provider, rate limit, timeout, cancel, post-child, task failure, mixed error hoặc kết quả mơ hồ. Nếu người dùng chỉ định Executor cho task hiện tại hoặc nói `no subagents`, cả primary và fallback đã lưu đều bị vô hiệu cho task đó.

## Kiểm tra route thật sự dùng được

Xem policy và compatibility của workspace:

```text
$codex-orchestration:codex-orchestration status
```

Phân biệt rõ các mức bằng chứng:

- `native policy installed`: state và config đã khớp.
- `pinned custom agent available`: agent đã load nhưng chưa chạy.
- `route accepted`: công cụ spawn đã chấp nhận route được yêu cầu.
- `used and confirmed`: client có metadata cơ học xác nhận model/provider/effort runtime.

Status không chứng minh route đang callable trong task hiện tại và không chứng minh fallback đang đủ điều kiện. Với custom agent hoặc route quan trọng, mở task mới và giao một packet read-only kiểm tra Git HEAD/worktree trước khi giao quyền sửa code.

## Tạo custom role

Tạo role trong project hiện tại:

```text
$codex-orchestration:codex-orchestration create project role: researcher
```

Project role nằm trong `.codex/agents/`; personal role nằm trong `~/.codex/agents/`. File mới chỉ được load ở task mới. Nếu project và personal có cùng tên, project có thể shadow personal; status sẽ fail closed thay vì đoán route.

Một packet Executor tốt nên có:

- mục tiêu và phần không được thay đổi;
- file/module thuộc quyền sở hữu;
- dữ kiện repo cần thiết;
- dependency và điều kiện dừng;
- tiêu chí nghiệm thu;
- kiểm tra nhỏ nhất cần chạy;
- format handoff gồm trạng thái, file đổi, checks và rủi ro còn lại.

## External Model và Kimi K3

Câu hỏi sau chỉ cho phép discovery read-only:

```text
is Kimi available to use as Designer?
```

Kết quả phải tách bốn trạng thái: supported, configured, locally ready và callable now. Discovery không cho phép tạo provider, nhập credential, chạy billable Gate 0 hoặc ghi config.

Khi cần authentication cho external provider, nhập key trong hidden local prompt của terminal tin cậy. Không dán key vào chat, command argument, file `.env`, Git, prompt, registry hoặc log.

## Update, repair và disable

Chỉ nâng cấp plugin này từ canonical marketplace:

```text
$codex-orchestration:codex-orchestration --update
```

Sau update phải restart Codex Desktop và tạo task mới.

Nếu status báo drift chỉ giới hạn ở managed mode/usage hint:

```text
$codex-orchestration:codex-orchestration repair
```

Repair chỉ phục hồi byte đã lưu của hai hint đó qua App Server CAS. Nó không thay route, restore snapshot, MCP launcher, credential, chat hay session.

Tắt native routing đã lưu:

```text
$codex-orchestration:codex-orchestration disable
```

`disable` phục hồi các giá trị routing trước setup và xóa state do plugin sở hữu sau khi validation thành công. Nó không gỡ plugin và không xóa custom role do người dùng sở hữu.

## Gỡ cài đặt an toàn

1. Dùng version hiện tại để chạy `disable`.
2. Xác nhận native policy đã inactive.
3. Gỡ plugin và marketplace bằng native Codex plugin manager.
4. Review riêng các file custom role do người dùng tạo; không xóa hàng loạt.
5. Restart Codex Desktop.

Nếu đã gỡ plugin trước khi disable, cài lại đúng version hiện tại, disable sạch rồi mới gỡ lần nữa. Trước khi downgrade xuống version không hiểu schema đã lưu, luôn disable bằng version mới trước.

Upstream 0.9.0–0.9.3 đã dùng schema 5 cho state chứa Opus, trong khi fork này đã dùng schema 5 cho fallback và route binding. Nếu chuyển một installation đang active từ upstream sang fork, hãy chạy `disable` bằng bản upstream trước, sau đó cài fork và tạo policy schema 6 mới. Validator sẽ không đoán giữa hai shape schema 5 trùng số nhưng khác contract.

## Phát triển và kiểm tra

Phản hồi nhanh:

```bash
python3 scripts/preflight.py quick
```

Gate local đầy đủ trước handoff:

```bash
python3 scripts/preflight.py full
```

Mỗi behavior fix cần regression test chính xác. Mọi thay đổi plugin payload phải tăng SemVer. Thay đổi security hoặc state cần threat model, test malformed/negative path và final-tree review mới, gắn với đúng HEAD SHA. Kết quả local chỉ là `PARTIAL`; protected checks trên hosted CI mới là nguồn xác nhận cuối cùng.

## Giấy phép và ghi nhận

Project gốc do CJ Zafir phát triển. Fork này được duy trì độc lập và tiếp tục phân phối theo MIT license; xem [LICENSE](LICENSE).
