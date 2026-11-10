# Issue #30: Source và golden — bàn giao ngày 10/11/2026

Phạm vi được người dùng chọn: **làm Source và golden trước**; chờ `types.py`
được merge vào main rồi mới triển khai Structure. Nhánh `feat/m2-structure`
tạo từ `origin/main` tại `12ffdd9`, không tạo từ nhánh crawler cũ.

## Các thay đổi

- Sửa `\iff` bị coi là điều kiện chưa đóng, khiến bỏ sót input phía sau.
- Giữ hook `\AtBeginDocument`/`\AtEndDocument` nguyên vẹn; không thực thi input
  trong hook sớm. Hook định dạng thông thường không gây cảnh báo nữa.
- Hạ lỗi input `.bbl` thực sự thiếu thành warning `missing_bbl`; giữ nguyên
  lệnh trong text và vẫn theo các input hợp lệ tiếp theo. Không hạ lỗi đường
  dẫn vượt thư mục hoặc file ngoài inventory.
- Trong nhiều ứng viên root, chọn duy nhất ứng viên có begin/end document
  đang hoạt động. Nếu nhiều bài hoàn chỉnh hoặc không rõ, giữ `ambiguous_root`
  và cho phép người chạy chọn `--root`.
  Đặc biệt không loại root có input/include vì thân bài có thể nằm ở file con.
- Thêm hồi quy cho `\newif` và `\ifmmode` trong macro: không diễn giải thân
  macro như lệnh đang chạy. Chưa thêm trình thực thi điều kiện TeX tùy biến.
- Tăng `assembler_version` từ 1 lên 2 để bên dùng checkpoint có thể nhận biết
  thay đổi hành vi.
- Bốn golden Source tự viết, so nội dung gộp, danh sách file, provenance và
  tính tất định. Kỳ vọng cây của từng case ghi ở README của bộ fixture.

Không đổi SourceBundle công khai, schema Parquet hay file của gói khác.

## Cách kiểm chứng

Windows hiện chặn DLL của PyArrow trong `.venv`, kể cả khi chạy đã cấp quyền.
Đã chuẩn bị môi trường Ubuntu WSL riêng `/var/tmp/arxiv-issue30-venv`, dùng
Python 3.12.3 và dependencies từ `requirements.txt`; không thay requirements.

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /var/tmp/arxiv-issue30-venv/bin/python -m pytest -q tests/test_parse_source.py tests/test_assemble_source_cli.py
```

Lượt đầu sau sửa lỗi: **43 passed**. Trước sửa, sáu trường hợp hồi quy thất bại
đúng lỗi cần sửa; bốn golden ban đầu cũng phát hiện kỳ vọng newline cuối sai,
đã chỉnh theo hợp đồng dừng tại end document, không đổi assembler cho trường hợp đó.

Toàn bộ thư mục test: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /var/tmp/arxiv-issue30-venv/bin/python -m pytest -q tests`
→ **266 passed, 15 subtests passed** trong 32,61 giây. Lệnh không chỉ định
`tests` đã dừng vì duyệt cả kho dữ liệu cục bộ lớn; kết quả trên bao gồm toàn
bộ test của repo. `git diff --check` không báo lỗi. Sau rà soát, bổ sung test
root có thân bài trong file con, `.bbl` có thật nhưng ngoài inventory, và hook
chứa `InputIfFileExists`/`import`/`catcode`; kết quả cuối ghi bên dưới.

**Kết quả cuối: 271 passed, 15 subtests passed trong 33,57 giây**, chạy toàn
bộ `tests` sau các sửa lỗi từ rà soát. Trong đó có 48 test Source/CLI.

## Còn lại để đóng issue

- Hợp đồng `types.py` được merge và review golden của Structure/BibSource.
- Triển khai `structure.py`, tách BibSource, gọi validator chung.
- Đo lại `ready` trên **Range Bảo**: chưa có corpus Range Bảo ở layout được
  chỉ định `data/crawl-smoke` trên máy này. Không dùng corpus `2410-*` để đại
  diện cho Range `2508.02872–2508.07871`.
- Gán nhãn/kiểm chéo 30 bài theo phân công; đo độ đúng heading ≥95%, không
  lọt References. Test tổng hợp không thay được bước gán nhãn này.
- Chạy mẫu 100 bài, ghi `metrics/structure.json`, so tokenizer với pylatexenc.
- Viết phần phương pháp Jupyter Book cùng số đo đã kiểm chứng.

Không đánh dấu issue đã hoàn thành hay tự merge. Mốc 75,9% là số liệu nền
được issue ghi lại, không phải kết quả đo trong lần sửa này.

Nguồn: [issue #30](https://github.com/hcmus-arxiv-reference/arxiv-reference-matching/issues/30),
[phân công](m2-cong-viec.md), [hợp đồng](m2-interfaces.md).
