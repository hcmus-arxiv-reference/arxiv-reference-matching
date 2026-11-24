---
status: accepted
---

# Mỗi Version parse đúng một văn bản chính, chọn file gốc theo bằng chứng

Chốt ngày 24/11/2026.

## Bối cảnh

Đề M2 định nghĩa file gốc là file `.tex` có `\documentclass`. Trên 5 Range có 1.963 Version
(42% số Version lỗi) có nhiều file như vậy và bị đánh `ambiguous_root`, nên không có Element nào.
Thường gặp nhất là bài chính đi kèm supplement, rebuttal, thư trả lời phản biện, hoặc template của
hội nghị còn sót trong archive. arXiv đôi khi nối PDF của nhiều file gốc, nên "PDF cuối" có thể
chứa cả phần supplement. Tuy vậy, schema có đúng một nút `document` cho mỗi Version. Review tay
từng Version (`configs/m2-reviewed-roots.json`) không kịp với số lượng này.

## Quyết định

1. **Chỉ parse văn bản chính.** Supplement, rebuttal, thư trả lời và template không vào cây
   của Version.
2. **Chọn file gốc theo thứ tự bằng chứng**, trong `assemble_source` (`src/parse/source.py`):
   - Có root đã review cho Version: dùng file đó (ưu tiên cao nhất, như trước).
   - Đúng một ứng viên có `\title` trùng tiêu đề Publication trong metadata, so theo dãy từ
     (chữ thường, bỏ lệnh và dấu): chọn file đó, ghi `root_selected_by_title`.
   - Đúng một ứng viên có tên file không đánh dấu tài liệu kèm theo (`supp*`, `SI`, `appendix`,
     `rebuttal`, `response*`, `reply`, `cover*`): chọn file đó, ghi `root_selected_by_name`.
     Không loại từ `letter` đứng riêng, vì nhiều tạp chí gọi bài là Letter.
   - Không luật nào cho kết quả duy nhất: giữ `ambiguous_root`, không đoán.
3. Lựa chọn theo luật là issue mức `warning`, có trong `log/versions.jsonl`, nên kiểm tra lại
   được. `ASSEMBLER_VERSION = "6"`.

Trên 5 Range, luật giải được 1.373/1.963 Version (1.141 theo tiêu đề, 232 theo tên). Kiểm ngẫu
nhiên 30 Version (15 mỗi luật) đều chọn đúng bài chính. 590 Version còn `ambiguous_root`, ví dụ
`Manuscript1.tex` với `Manuscript2.tex`, hoặc hai `main.tex` ở hai thư mục.

## Considered Options

- **Parse mọi file gốc thành nhiều cây con** dưới một `document`: gần hơn với PDF ghép của arXiv,
  nhưng trộn supplement và thư phản biện vào nội dung bài, đổi nghĩa của `hierarchy` mà nhóm M3
  đang dùng.
- **Script gợi ý rồi review tay toàn bộ:** đúng nhất từng Version, nhưng không kịp hạn 27/11, và
  trái quy tắc "Parser sửa bằng code, không sửa tay từng dòng" của AGENTS.md.

## Consequences

- Đổi luật thì phải chạy lại M2 cả 5 Range, vì `element_id` và `hierarchy` của các Version này
  thay đổi.
- Tỉ lệ parse tăng nhưng phụ thuộc chất lượng metadata: Version mà tác giả đổi tiêu đề giữa các
  lần nộp chỉ được chọn nếu luật tên file áp dụng được.
