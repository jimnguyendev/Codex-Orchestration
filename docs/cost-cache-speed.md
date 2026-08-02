# Chi phí, cache và tốc độ

## Không chỉ đếm token

So sánh hợp lý phải dùng tổng chi phí có trọng số theo model:

```text
total_cost =
  root_input + root_cached_input + root_output
  + worker_input + worker_cached_input + worker_output
  + planner_advisor + retries + rework
```

Raw token ít hơn không nhất thiết rẻ hơn; model, loại token và service tier quyết
định đơn giá. Latency cũng phải tính thời gian đọc lại context, tool calls, queue,
review và sửa sai.

## Ví dụ Luna so với Sol

Theo bảng giá Codex được kiểm tra ngày 2026-08-02, chi phí credits trên một triệu
token là:

| Model | Input | Cached input | Output |
| --- | ---: | ---: | ---: |
| GPT-5.6 Sol | 125 | 12,5 | 750 |
| GPT-5.6 Terra | 50 | 5 | 300 |
| GPT-5.6 Luna | 5 | 0,5 | 30 |

Với cùng token mix, Luna bằng 4% Sol, tức khoảng 1/25; Terra bằng 40% Sol. Nếu
20% workload ở Sol và 80% ở Luna:

```text
0,20 × 1 + 0,80 × 0,04 = 0,232
```

Đó là khoảng 76,8% ít model-weighted credits hơn trước orchestration overhead.
Đây không phải cam kết tiết kiệm 76,8% trên workload thật.

Một chi tiết đáng chú ý: Luna input không cache là 5 credits/M, vẫn thấp hơn Sol
cached input 12,5 credits/M. Vì vậy cache miss khi đổi model không tự động làm
Luna đắt hơn. Tuy nhiên output, lượng context đọc lại và rework mới quyết định
kết quả cuối.

Nguồn giá: [OpenAI Learn — Pricing](https://learn.chatgpt.com/docs/pricing).

## Cache thực sự hoạt động ở đâu

Prompt caching phụ thuộc exact prefix và cache state của model. Không nên giả định
KV cache được chia sẻ giữa các model family. Subagent là một model invocation riêng;
nó nhận context theo cơ chế fork/handoff của host và tiêu thụ token riêng.

Trong plugin:

- `fork_turns=none` tránh copy toàn bộ transcript;
- packet ngắn làm giảm duplicated input;
- worker vẫn phải đọc file cần thiết;
- không có claim chuyển cache Sol → Luna/Terra.

Tham khảo: [OpenAI prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching)
và [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents).

## Khi nào chỉ giảm thinking level hợp lý hơn?

Giữ cùng model và hạ effort thường hợp lý khi task:

- rất ngắn hoặc context-heavy;
- cần giữ phong cách/phán đoán của Root;
- handoff packet gần dài bằng công việc;
- rủi ro rework cao hơn chênh lệch đơn giá.

Luna thường hợp lý khi implementation dài nhưng contract đã chốt. Terra hợp lý
khi lỗi có blast radius cao hoặc cần reasoning mạnh hơn. Plugin để task quá nhỏ ở
Root chính vì handoff không miễn phí.

## Cách benchmark cho repository thật

Chọn một tập task lặp lại và chạy tối thiểu ba chiến lược:

1. Sol cùng model, effort thấp hơn;
2. Sol Root + Luna cold handoff;
3. Sol Root + Terra cho hard/risky.

Ghi lại input/cached/output, wall time, tool calls, retry, test pass lần đầu và
thời gian sửa lại. Chỉ so task cùng acceptance criteria. Không dùng một demo thành
công để suy ra mọi workload.
