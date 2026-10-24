# Milestone 2 — lớp gom source

Ngày 24/10/2026. Đây là bước 1 của kế hoạch M2 (bản cũ: `git show 062ba29:leader.md`), không phải
pipeline M2 hoàn chỉnh. Crawler đang hoạt động độc lập; công cụ này không
gọi mạng, không sửa raw source hoặc checkpoint crawl và không upload.

## Phạm vi đã triển khai

`src.parse.assemble_source(directory, root_file=None, require_receipt=False)`
trả về `SourceBundle`. CLI luôn yêu cầu `source.json` hợp lệ; chế độ API
không có receipt phục vụ fixture tự viết. Có receipt nhưng không hợp lệ
thì API cũng từ chối, không tự hạ mức kiểm tra.

- Tìm `documentclass` ngoài comment, verbatim, thân định nghĩa macro và
  nhánh điều kiện vô hiệu. Nhiều root phải chọn `--root`; không tự lấy file
  đầu tiên. Không có root là lỗi, không suy ra đó là Version `non_tex`.
- Theo `input`/`include` literal đệ quy, có hoặc không có đuôi `.tex`.
  `input` chấp nhận tên không ngoặc; tên có khoảng trắng dùng ngoặc nhọn.
  Ưu tiên đường dẫn tương đối thư mục root (working directory của TeX).
  Nếu chỉ có đường dẫn tương đối file gọi thì dùng fallback và ghi thông
  tin `relative_to_includer`. Không chạy TeX hoặc truy cập hệ thống TeX.
- Bỏ include nằm trong comment/verbatim khỏi đường duyệt. Comment vẫn
  giữ trong văn bản gộp để bảo toàn vị trí nguồn; lớp dựng cây sau phải
  xử lý comment như nội dung không được biên dịch, không sinh Sentence.
- Hỗ trợ `iftrue`/`iffalse`, `includeonly` literal, dừng ở `end{document}`
  và `endinput` không có token theo sau trên cùng dòng. Các cấu trúc
  chưa hỗ trợ có diagnostic, không được tự xem là đã parse thành công.
- Phát hiện thiếu file, vòng lặp theo stack đang mở, đường dẫn thoát
  thư mục Version, symlink, root lồng, lỗi ngoặc, giới hạn độ sâu và độ
  dài đầu ra. Include lặp hợp lệ vẫn xuất hiện nhiều lần trong văn bản.
- Giữ danh sách file dùng/không dùng, SHA-256, từng lần include và vị trí
  từng đoạn. Với receipt, kiểm tra lại nguồn sau khi gom để phát hiện đổi
  file trong lúc xử lý. Không mở network hoặc thực thi macro.

## Cách chạy

Từ root repo, dùng môi trường đã cài `requirements.txt`:

```sh
/private/tmp/arxiv-lieu-venv/bin/python -m scripts.assemble_source \
  --source-dir data/milestone2-samples/20261024-29ljsh77/raw/2508-02873/v3 \
  --output data/milestone2-source/2508-02873-v3.json
```

`--root main.tex` chọn root khi có nhiều ứng viên. Output phải nằm ngoài
thư mục Version đầu vào, được ghi bằng file tạm rồi thay nguyên tử.
Đường dẫn mẫu trên chỉ có ở local này; người clone cần dùng Version đã
crawl của mình, không có corpus được commit vào Git.

JSON là artifact làm việc, không phải cột JSON trong Parquet. Các trường:

- `status`, `root`, `assembler_version`;
- `text`: nội dung nguồn gộp, chưa chuẩn hóa, chưa đổi citation key;
- `files`, `unused_tex_files`, `checksums`: inventory liên quan;
- `spans`: khoảng ký tự nửa mở `[start, end)` trong output và file nguồn
  đã decode, cùng dòng gốc tính từ 1; không phải byte offsets;
- `includes`: từng lần gọi, file đích và trạng thái;
- `issues`: mã, mức độ, file/dòng và mô tả.

Trạng thái chỉ thuộc lớp gom source:

- `ready`: lớp gom không phát hiện lỗi/cảnh báo; chưa có nghĩa parse M2 xong.
- `needs_review`: có cấu trúc chưa hỗ trợ hoặc encoding fallback.
- `error`: thiếu/hỏng đầu vào hoặc không gom đáng tin cậy; output nếu có
  chỉ dùng chẩn đoán, không đưa vào bước sau như kết quả hợp lệ.
- `empty_non_tex`: receipt crawler đã xác minh không có TeX; không sinh nút.

CLI exit 0 với `ready`/`empty_non_tex`, exit 2 với cảnh báo/lỗi. I/O hoặc
tham số CLI lỗi cũng exit 2; xem stderr nếu không tạo được artifact.

## Kiểm chứng đã chạy

Toàn bộ test offline, gồm schema M2, source assembly và CLI:

**146 test và 15 subtest đạt** trên môi trường Python 3.14.7 hiện có.

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /private/tmp/arxiv-lieu-venv/bin/python -m pytest -q
```

Fixture tự viết trong Python và tạo file tạm; không cần mở ngoại lệ
`.gitignore` cho source tải về. Có kiểm thử provenance, comment, verbatim,
include lồng/lặp, working directory, root mơ hồ, macro/điều kiện chưa hỗ
trợ, vòng lặp, đường dẫn, receipt hỏng, Version rỗng và CLI chạy lại.

Chạy thật trên snapshot `data/milestone2-samples/20261024-29ljsh77/`:

- `2508.02872`: v2 `ready`; v1 `needs_review` vì `AtBeginDocument` ở dòng 59.
  Đã đọc đoạn source: hook này đặt footer. Hiện giữ cảnh báo chung cho
  hook trì hoãn, không viết ngoại lệ theo ID để cho kết quả đẹp hơn.
- `2508.02873`: v1/v2/v3 `ready`, mỗi Version dùng đúng 8 file TeX.
  Include bị comment như `secIntro2025`, `design` không bị mở nhầm.
- `2508.02876`: v1 `ready`, root `sample631.tex` và hai file bảng được gom.
- `2508.02874v1`, `2508.03870v1`: `empty_non_tex`.

Tổng: 5 `ready`, 1 `needs_review`, 2 `empty_non_tex`. Hai lượt CLI cho
artifact giống byte; toàn bộ 52 checksum input giữ nguyên. Bằng chứng
local: `data/milestone2-source/20261024/validation.json`. Không lấy các
số liệu này làm tỷ lệ parse toàn Range hoặc benchmark Colab.

## Giới hạn và bước tiếp theo

Chưa diễn giải macro, package, điều kiện tùy ý, `import`/`subimport`, hook
trì hoãn hoặc thay đổi catcode. File UTF-8 được ưu tiên; fallback Latin-1
được đánh dấu cần kiểm tra. Không có tuyên bố tương đương mọi phép biên
dịch LaTeX; các kết quả cần review chưa đạt nghiệm thu pipeline mẫu G2.

Bước tiếp theo theo leader là dựng cây, tách Sentence/Formula/Figure và
itemize, giữ Appendix/Acknowledgements và loại References. Chuẩn hóa,
BibTeX/citation key, dedup, xuất ba bảng, runner toàn Range và benchmark
chưa triển khai. Trước khi xuất bảng phải chốt phần G0 còn mở: Element ID,
lần xuất hiện lặp, categorical/nullability còn lại và hợp đồng citation
key. Ba thay đổi schema được duyệt không đồng nghĩa đóng băng toàn G0.

Nguồn: [đề Parsing](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/parsing/),
[đề Matching và sáu bảng](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/matching/).
