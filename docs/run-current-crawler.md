# Crawl Range bằng một lệnh trên Windows

Cập nhật 26/10/2026, nhánh Hai_crawler. CLI tích hợp discovery theo lô, tải mọi
Version, references Semantic Scholar, checkpoint có checksum và xuất Parquet.
Không cần chuẩn bị file ID hoặc chạy notebook trước.

## Lệnh chạy

Tại thư mục `D:\hk1\KHDL\arxiv-reference-matching`, chạy PowerShell:

```powershell
.\.venv\Scripts\python.exe -X utf8 -u -m scripts.crawl_range --start 2412.08848 --end 2412.13847
```

Hai đầu đều tính: 5.000 ID. Tham số CLI ghi đè Range trong .env. CONTACT_EMAIL
bắt buộc; S2_API_KEY đọc từ .env, không có key vẫn có thể gọi nhưng dễ gặp 429.
Môi trường .venv tại máy này đã có dependency; máy mới cần tạo .venv rồi cài
`python -m pip install -r requirements.txt`. Không cần token HF cho lệnh local.

Mặc định dữ liệu ở `data/crawl-2412-08848-13847/`. Muốn chỉ định vị trí khác,
thêm `--data-dir <thư-mục>`. Không trỏ hai Range khác nhau vào cùng thư mục;
runner sẽ từ chối khi checkpoint ghi nhận Range khác để tránh ghi đè bảng.

## Output tương thích pipeline cũ

```text
data/crawl-2412-08848-13847/
  raw/<publication-key>/v<n>/
    *.tex, *.bib                       # giữ nguyên bytes source văn bản
    source.json                       # receipt + SHA-256 từng file
  metadata/<publication-key>.json
  references/<publication-key>.json
  manifests/crawl.jsonl                # trạng thái discovery/source/S2
  manifests/range-run.json             # tiến độ, PID, pending_ids
  tables/papers.parquet
  tables/references.parquet
```

Publication key ví dụ `2412-08848`. GZIP chỉ chứa một file TeX được lưu thành
`single.tex`, giống pipeline cũ. Không giữ archive gốc như notebook riêng.
PDF/docx không có TeX vẫn có receipt `non_tex` và thư mục Version rỗng source.
404/410 là unavailable, không bị coi là một Version đã tải thành công.

Schema chung không thay đổi:

- papers: arxiv_id, title, authors, submission_date, revised_dates, venue.
- references: arxiv_id, ref_arxiv_id, ref_title, ref_authors,
  ref_submission_date, ref_s2_id.

Ba cột authors/revised_dates/ref_authors giữ list<string>. S2 được đọc hết các
trang; JSON cache giữ cả references không có arXiv ID, Parquet chỉ xuất ứng
viên có arXiv ID, khử trùng lặp theo Publication/ref_arxiv_id. Không gán ngày
xuất bản S2 thành ngày nộp arXiv; ref_submission_date chưa xác minh giữ null.

Parquet chỉ chứa Publication đủ metadata, mọi Version hợp lệ và S2 thành công.
Hai bảng được ghi qua file tạm/replace, sau mỗi 50 Publication đã xử lý, cuối
mỗi lượt và khi dừng có kiểm soát. Có thể đổi bằng `--export-every N`.
Nếu mất điện hoặc kill cưỡng bức, bảng có thể chậm hơn checkpoint; chạy lại
sẽ tái tạo từ dữ liệu hợp lệ. Hai file Parquet không phải một giao dịch chung,
chỉ đọc kết quả ổn định khi lượt export đã hoàn tất.

## Resume, dừng và retry

Chạy lại **đúng lệnh và thư mục dữ liệu**: kiểm tra checksum, bỏ qua phần đã
hợp lệ, chỉ tải phần thiếu/hỏng. Không cần cờ --resume. Discovery đã cache
không tự cập nhật Version mới xuất hiện sau lần crawl đầu.

- Ctrl+C: giữ checkpoint và xuất phần đã đủ dữ liệu; có thể cần đợi request
  đang chạy/timeout. Không nhấn liên tục hoặc đóng cưỡng bức nếu muốn export.
- Cách dừng sau Publication hiện tại từ terminal thứ hai:

```powershell
New-Item data/crawl-2412-08848-13847/STOP_RANGE -ItemType File -Force
```

Đợi trạng thái stopped rồi xóa riêng cờ STOP_RANGE trước lần chạy tiếp.
Không xóa manifest, receipt hoặc source để resume.

Mặc định tối đa 3 lượt; lượt sau chỉ thử phần chưa hoàn chỉnh, nghỉ 1.800 giây
ở giữa. HTTP 429/5xx/timeout có retry hữu hạn. Khi Retry-After quá dài, client
báo lỗi để lượt sau thử lại; nếu server yêu cầu lâu hơn thời gian nghỉ đã cấu
hình, cần đợi đủ trước khi thử lại. Có thể tăng `--retry-delay`.

- complete, exit 0: toàn Range đủ và đã export.
- incomplete, exit 1: còn thiếu sau các lượt, xem pending_ids/manifest.
- stopped, exit 1: dừng có kiểm soát.
- failed hoặc lỗi khởi động, exit 1: cần xem thông báo terminal.

ArXiv dùng export.arxiv.org, một kết nối tại một thời điểm và cách request ít
nhất 3,1 giây. Mặc định discovery 50 ID/lô. Không chạy crawler khác đồng thời,
kể cả notebook hoặc ở thư mục/máy khác. Khóa file chỉ chặn writer cùng thư mục.
Runner dừng nếu ổ đĩa còn dưới 5 GiB; đây không phải ước lượng dung lượng cần.
Lệnh không upload Hugging Face.

Xem tiến độ ở terminal khác:

```powershell
Get-Content data/crawl-2412-08848-13847/manifests/range-run.json -Raw |
    ConvertFrom-Json | Select-Object status,current_id,pass,counts
```

## Nguồn tích hợp và kiểm chứng

Các module src/crawl và runner Range được tái sử dụng từ commit 63df237 để
khôi phục đúng hợp đồng output, không chuyển toàn nhánh về code cũ. Discovery
batch được tách thành src/crawl/batched.py; CLI mới nhận trực tiếp hai ID,
tự chọn thư mục, bảo vệ Range và export định kỳ. Giữ notebook và SQLite riêng;
CLI không tự nhập cache notebook/SQLite vì chúng chưa có receipt xác minh.
Không có thay đổi schema Parser/Matching.

Mẫu mạng thật 2412.08849 ngày 26/10/2026 hoàn tất: 1 Version TeX, 1 dòng papers,
0 dòng references theo schema. Resume cache mẫu với transport bị chặn vẫn
hoàn tất, không gọi mạng. Test offline bao phủ S2 có references nhiều trang,
nhiều Version, non_tex, cache hỏng, checkpoint bị cắt, lỗi HTTP, Range CLI và
schema/giá trị Parquet. Chưa chạy toàn 5.000 ID, chưa benchmark, chưa upload HF.

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = "1"
.\.venv\Scripts\python.exe -X utf8 -m pytest -q -p no:cacheprovider
```

Cache smoke nằm ở data/cli-smoke-2412, tách khỏi Range thật. Cache cũ
`data/crawl-2412` đã được xóa theo xác nhận trước đó; .env và .venv được giữ.
