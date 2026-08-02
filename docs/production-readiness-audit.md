# Kiểm toán mức sẵn sàng phát hành

Tài liệu này giữ lại provenance của đợt kiểm toán ngày 2026-07-12 tại baseline
`a674a81` (0.4.0), đồng thời ghi rõ trạng thái hiện tại của 0.10.0. Các kết luận
runtime vẫn phải được xác nhận lại trên release candidate và CI hosted.

## Các vấn đề lịch sử đã xử lý

| Mức độ | Vấn đề | Cách xử lý |
| --- | --- | --- |
| Cao | README đi thẳng vào chi tiết nội bộ, chưa giải thích bài toán orchestration | Viết lại phần giới thiệu, workflow, ranh giới bằng chứng, cài đặt và ví dụ sử dụng. |
| Cao | Fable được phát triển tách rời nên không thể quảng bá Planner/Advisor một cách trung thực | Tích hợp bridge opt-in, read-only, kiểm tra login first-party và runtime model; fail closed khi output không hợp lệ. |
| Cao | Nhánh phân phối có thể thay đổi thiếu kiểm soát | Yêu cầu PR, protected checks, review, chặn force-push/delete và ghim action bằng SHA. |
| Cao | Same-provider routing dễ bị hiểu nhầm là engine-enforced | Phân biệt `configured`, `available`, `route accepted` và `used and confirmed`. |
| Trung bình | Restore có thể báo thành công khi rollback config chưa được chứng minh | Kiểm tra kết quả rollback và báo trạng thái không chắc chắn thay vì giả vờ thành công. |
| Trung bình | Nhiều validator state không đồng nhất | Dùng full-state validator chung với exact schema shape, snapshot, marker và route binding. |
| Trung bình | Runtime confirmation của Fable từng chấp nhận model phụ không biết | Chỉ cho phép primary và exact helper allowlist đã được review; model lạ làm seat unavailable. |
| Trung bình | Status từng luôn exit 0 dù policy xung đột hoặc thiếu | Thêm `--require-effective` và negative-path tests. |
| Trung bình | Hai transaction của custom role và native policy không atomic | Phát hiện orphan, cleanup có giới hạn và không xóa file không còn thuộc plugin. |
| Trung bình | Windows từng được tuyên bố rộng hơn bằng chứng | Thêm portability tests và mô tả rõ nhánh update/remove custom role phải fail closed. |
| Thấp | Thiếu security/release ownership và static-quality baseline | Thêm CodeQL, Dependabot, `SECURITY.md`, `CODEOWNERS`, `CONTRIBUTING.md`, release gate và Ruff. |

## Đánh giá lại cho 0.10.0

Phiên bản 0.10.0 giảm bề mặt vận hành theo ba hướng:

1. Chỉ còn một quyết định routing cho implementation: Luna Max hoặc Terra Max.
2. Planner/Advisor không tự chạy chỉ vì đã được cấu hình.
3. Xóa Kimi/OpenRouter, credential enrollment, paid Gate 0 và generic External
   Model lifecycle; giữ Fable/Opus sealed route và state compatibility cần thiết.

Các gate local bắt buộc:

```bash
python3 scripts/preflight.py quick
python3 scripts/preflight.py full
```

`full` phải kiểm tra compile, focused/full tests, release identity và lifecycle.
Ruff, Windows/Python matrix, CodeQL và repository protection là hosted evidence;
local pass vẫn chỉ là `PARTIAL`.

## Ranh giới có chủ đích

- Root luôn sở hữu intent, architecture, permission, integration, verification và
  final answer. Policy không biến child thành orchestrator thứ hai.
- Codex chưa có global engine field cố định một Executor. Managed hints vẫn là
  model-visible policy và root cung cấp route khi spawn.
- Direct model override dùng provider của Root. Cross-provider route cần custom
  agent có `model_provider` được người dùng tự cấu hình và xác thực.
- Fable/Opus là ngoại lệ subscription được bundle, chỉ dùng cho planning/review,
  không dùng làm implementation worker.
- MCP request hiện không mang caller identity. Quy tắc “chỉ Root gọi bridge” là
  instruction-enforced; no-tools, no-session, model/effort pinning và output
  validation được bridge cưỡng chế.
- Setup/status chỉ chứng minh config/state nhất quán. Cần một child call có metadata
  để chứng minh route được chấp nhận hoặc model thực tế đã chạy.

## Điều kiện phát hành

- Version trong manifest, package, fixture và tài liệu khớp nhau.
- Mỗi behavior fix có regression test chính xác.
- Thay đổi security/state có threat model, malformed/negative tests.
- Fresh final-tree review gắn với đúng head SHA; head đổi thì review hết hiệu lực.
- Hosted required checks xanh trước merge/release.
- Tag và GitHub release phải khớp SemVer đã phát hành.
