# Review hạ tầng chung

Ngày 2026-10-16. Phạm vi: tích hợp bốn module của người dùng và kiểm tra
cục bộ trước khi tải mẫu, không tạo repo hoặc upload dữ liệu thật.

## Những điểm đã xác minh và sửa

- File ban đầu nằm ở root, trong khi test mới import `src.common` và
  `hf_io.py` dùng relative import. Chuyển bốn module vào `src/common`, thêm
  package `__init__.py`, cập nhật import test schema; không giữ hai bản code.
- Workspace chưa có `.env.example`; đã thêm mẫu chỉ có tên biến, Range và
  tên thành viên minh họa, không có token hay email thật.
- Sau sửa cấu trúc, bộ test ban đầu thực tế gồm **32 test**: 14 schema và
  18 hạ tầng. Không tái hiện được 17 test schema hoặc tổng 35 trong workspace.
- `upload_dir` trước đó chấp nhận `raw/bao/../nghiem` khi chỉ so đoạn thứ hai.
  Nay kiểm tra đường dẫn canonical, tên thành viên, loại thư mục, glob và
  đoạn rỗng/dot trước khi gọi mạng. Helper raw kiểm tra ID và Version dương.
- `ensure_repo(private=True, exist_ok=True)` chưa xác minh visibility của
  repo có sẵn. Nay đọc `repo_info` và từ chối repo public; kiểm tra tương tự
  trước upload thư mục/bảng. Không tự thay visibility repo của người dùng.
- `upload_table` nay kiểm tra Parquet/schema cục bộ trước khi upload.
- `repr(Settings)` trước đó chứa token/API key; đã đặt `repr=False` cho hai
  trường này. Không ghi token thật trong log hoặc tài liệu khi kiểm tra.

Tài liệu SDK tham khảo:
https://huggingface.co/docs/huggingface_hub/guides/repository
và https://huggingface.co/docs/huggingface_hub/package_reference/hf_api
(create_repo, repo_info, upload_folder, upload_file).

## Kết quả kiểm thử

Đã cài `requirements.txt` trong `.venv` cục bộ có kế thừa system site-packages.
Phiên bản thực chạy: Python 3.14.3, PyArrow 23.0.1, python-dotenv 1.2.2,
huggingface_hub 0.36.2, pytest 9.1.1.

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
```

**54 test đạt, kèm 15 subtest**, gồm 22 ca regression mới so với bộ 32 test
có sẵn (17 ca lần review đầu, 5 ca bổ sung cho giới hạn upload raw và CLI).
Phải tắt plugin
tự nạp trên máy hiện tại vì plugin LangSmith ngoài dự án lỗi khi import
`cgi` trên Python 3.14; đây không phải lỗi của bốn module dự án.

Test HF chỉ dùng mock để kiểm tra từ chối repo public/đường dẫn sai và
tham số upload/download. Chưa thử xác thực token, quyền repo hoặc truyền
dữ liệu thật. Private check và upload là hai request riêng, không bảo đảm
visibility không bị người khác đổi giữa hai thao tác.

## Giới hạn cần ghi đúng khi báo cáo

- `peak_rss_mb()` đo RAM đỉnh của tiến trình hiện tại từ khi khởi động,
  không riêng một Publication và không cộng tiến trình con. Đơn vị chia
  theo 1024 nên thực tế là MiB dù tên hàm dùng MB.
- `measure()` đo wall time của khối và lấy RAM đỉnh nêu trên, kể cả lúc lỗi.
- `dir_size_mb()` đo dung lượng logic hiện tại của các file. Đây không phải
  dung lượng đĩa đỉnh hoặc dung lượng block thực được filesystem cấp phát.
- Chưa có lấy mẫu RAM trung bình, tổng RAM cây tiến trình hoặc disk đỉnh.
  Cần bổ sung khi benchmark toàn hệ thống trên Colab CPU.
- JSONL hiện là log append cho một writer; không phải checkpoint có khóa
  giao dịch cho nhiều process và chưa phải manifest theo Version.
- Requirements hiện là khoảng phiên bản, chưa phải lockfile tái lập toàn
  môi trường; ghim phiên bản sau khi chốt môi trường benchmark/đóng gói.

Chưa đánh dấu toàn bộ giai đoạn 2 hoàn thành vì schema ngoài Crawling chưa
được đối chiếu và người dùng chưa đóng băng schema toàn dự án.

## Chuẩn bị kiểm tra Hugging Face thật

Đã đối chiếu chữ ký phương thức SDK 0.36.2 đang cài: các tham số dùng trong
create_repo/repo_info/upload_folder/upload_file khớp. Đây chưa chứng minh
token có quyền hoặc dịch vụ mạng hoạt động.

`CONTACT_EMAIL` đã có trong `.env`. Các tên biến còn thiếu đã được bổ sung
từ mẫu, không ghi đè giá trị cũ; `MEMBER_NAME=bao`. Hiện còn thiếu `HF_TOKEN`
và `HF_REPO_ID`, nên chưa tạo/xác minh repo thật. Lệnh đã chạy:

```sh
.venv/bin/python -m scripts.check_hf
```

Kết quả hiện tại: exit code 2, báo thiếu hai biến này trước khi gọi mạng.
Sau khi người dùng điền cấu hình cục bộ, chạy lại cùng lệnh để gọi
`ensure_repo` đúng một lần. Lệnh không upload dữ liệu hoặc in token.

Quyết định mới của người dùng đã áp dụng: `upload_dir` chỉ ghi bên dưới
`raw/<MEMBER_NAME>/...`, còn bảng dùng `upload_table`. Kiểm tra thư mục chỉ
bảo vệ thao tác qua module này, không kiểm soát thao tác thủ công/công cụ khác.
