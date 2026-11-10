# Golden của Source + bản thiết kế kiểm thử Structure

Các chuỗi LaTeX ở đây do người viết test tạo, không lấy từ corpus.
Mỗi `source.json` chứa `files` (đường dẫn → nội dung fixture) và `expected`
(các trường SourceBundle cần so chính xác). File này là **định nghĩa test**,
không phải receipt crawler. Test dựng file trong thư mục tạm rồi gọi assembler.

Chạy `python -m pytest -q tests/test_parse_source.py -k source_golden`.
Test còn kiểm output tất định và ánh xạ mọi đoạn về nội dung file gốc.
Assembler dừng ngay sau `\end{document}`; newline sau lệnh này không thuộc output.

## Kỳ vọng Structure để review trước khi triển khai

| Case | Khung cây mong đợi | Nội dung cần kiểm |
|---|---|---|
| `multi-file-input` | document → section Intro → text | `Nested body.`; không có `UNUSED` |
| `comments-and-verbatim` | document → các block literal; section Real → text | Không có heading Fake; không mở include trong comment, verb hoặc verbatim |
| `levels-skip` | document → subsection First → paragraph Detail; document → subsection Second | Không tạo section giả; Second có `starred=true` |
| `appendix-ack-refs` | document → section Intro; section Acknowledgements; section Proof | Bỏ References và thebibliography khỏi cây, giữ Proof sau appendix |

Ở case cuối, BibSource mong đợi có `cite_keys_used=["one"]`, không có file
`.bib`, và một bibitem: `\bibitem{one} A. Author. Title. 2020.` (giữ newline
gốc khi chuyển thành artifact đầy đủ). Các case khác không có trích dẫn.

**Trạng thái 10/11/2026:** bốn golden chạy được cho lớp **Source**. Kỳ vọng
Structure trên bảng là bản bàn giao để review, chưa phải `B.v1.json`/`B'.v1.json`
đã qua validator. `types.py` chưa có trên main tại commit `12ffdd9`; người dùng
chọn làm Source và golden trước, chờ hợp đồng chung được merge rồi mới làm
Structure. Không coi test Source xanh là đã đạt golden của cả gói M2.2.

Nguồn yêu cầu: [m2-interfaces](../../../docs/m2-interfaces.md),
[issue #30](https://github.com/hcmus-arxiv-reference/arxiv-reference-matching/issues/30).
