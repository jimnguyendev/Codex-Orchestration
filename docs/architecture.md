# Kiến trúc

## Tổng quan

Root là model đang điều khiển task. Plugin chỉ thêm policy và công cụ để Root có
thể chọn một worker phù hợp; nó không tạo orchestrator thứ hai.

```mermaid
flowchart TD
    U["Người dùng"] --> R["Root Codex model"]
    R --> C{"Phân loại một lần"}
    C -->|"Quá nhỏ"| R
    C -->|"Routine, rõ, ít rủi ro"| L["GPT-5.6 Luna Max"]
    C -->|"Hard/risky, Root là GPT-6 Astra"| R
    C -->|"Hard/risky, Root khác"| T["GPT-5.6 Terra Max"]
    L --> H["Handoff: diff, checks, rủi ro còn lại"]
    T --> H
    H --> V["Root đọc diff và chạy verification"]
    V --> O["Kết quả cuối cho người dùng"]
```

Nếu Luna phát hiện rủi ro ẩn, Luna dừng trước khi mở rộng scope. Astra Root giữ
việc khó ở Root; Root khác có thể cập nhật packet và thử Terra đúng một lần.
Không chạy hai lane cạnh tranh. Direct `gpt-6-astra` child chỉ hợp lệ khi catalog
callable hiện tại có đúng ID đó.

## Thành phần

```mermaid
flowchart LR
    subgraph Repo["Plugin package"]
        S["SKILL.md\nquy tắc routing"]
        N["configure_native_routing.py\nsetup, status, repair, disable"]
        B["Fable 5.1/Opus 5 MCP bridge\nplanning và review read-only"]
        ST["State validators\nCAS, lock, restore"]
    end

    subgraph Host["Codex host"]
        AS["App Server config"]
        A["agents.spawn_agent"]
        M["Active model catalog"]
    end

    subgraph Optional["Provider tùy chọn"]
        CC["Claude Code CLI\nfirst-party Pro/Max/Team login"]
    end

    S --> A
    N <--> AS
    N --> M
    N <--> ST
    B --> CC
```

- `SKILL.md` định nghĩa classification, handoff và evidence language.
- Native configurator dùng App Server `config/read` và `config/batchWrite`; không
  sửa TOML một cách mù quáng.
- State lưu exact restore values. Config/state ghi với compare-and-swap và lock;
  ambiguity hoặc concurrent change làm operation fail closed.
- Fable/Opus bridge không có tools, không giữ session, pin model/effort và kiểm
  tra structured output. Đây không phải implementation lane.
- Kimi/OpenRouter và generic External Model lifecycle không còn trong package.

## Luồng handoff

Mọi different-model child dùng `fork_turns=none` và nhận đúng năm phần:

```text
OBJECTIVE
OWNERSHIP
CONTRACTS
DONE WHEN
VERIFY AND RETURN
```

Packet mặc định dưới 1.200 từ. Worker tự đọc file cần thiết trong repository thay
vì nhận lại toàn bộ transcript, plan và log từ Root.

```mermaid
sequenceDiagram
    participant R as Root
    participant W as Luna hoặc Terra
    participant F as Repository và checks
    R->>W: Packet 5 phần, fork_turns=none
    W->>F: Đọc đúng phạm vi, sửa, test nhỏ nhất
    W-->>R: Files, evidence, blockers, residual risk
    R->>F: Đọc diff thật, rerun checks
    R-->>R: Accept, sửa tiếp hoặc từ chối
```

## Planner và Advisor tùy chọn

Planner/Advisor được cấu hình không có nghĩa là tự chạy. Chúng chỉ được gọi khi:

- người dùng yêu cầu planning/review trong task hiện tại; hoặc
- repository/risk gate bắt buộc independent review.

Routine mặc định dùng 0 call; mọi task có budget tối đa một Planner-or-Advisor
model call. Nếu repository bắt buộc exact final-tree review, Root giữ lượt đó
tới sau implementation/checks. Finding hoặc `PLAN_REVISE` không tự cho phép gọi
lần hai; Root sửa cục bộ và phải hỏi người dùng trước khi model re-review. Chỉ
current-task instruction rõ ràng mới được nới budget này.

Fable có thể là Planner qua sealed Claude bridge. Sol có thể là Advisor cùng
provider qua direct child route. Hai seat không trực tiếp nói chuyện với nhau;
Root giữ canonical plan và findings ledger.

## Ranh giới tin cậy

```mermaid
flowchart TB
    P["Policy/state hợp lệ"] -->|"chỉ chứng minh"| E1["Configured"]
    M["Model catalog hiện tại"] -->|"chỉ chứng minh"| E2["Available"]
    S["Spawn API nhận exact route"] --> E3["Route accepted"]
    X["Host trả effective model/effort"] --> E4["Used and confirmed"]
    E1 -. "không suy ra" .-> E3
    E2 -. "không suy ra" .-> E4
```

Không được dùng prose của child để chứng minh model identity. Policy là
model-visible instruction, không phải engine-enforced scheduler. Permission,
sandbox, approval và Goal vẫn thuộc Codex host và Root.
