# Chạy M1 trên Kaggle với SQLite

## Chạy local trên VS Code

Notebook tự nhận biết local, tìm repo từ thư mục hiện tại hoặc thư mục cha,
đọc `.env` tại repo; không cần code ZIP hoặc `kaggle_secrets`. Sau khi cập nhật
file, Restart Kernel và chạy các cell theo thứ tự. Mặc định LIMIT=3; đổi 5000
trong cell cấu hình và chạy lại cell đó để dựng lại IDS.

Terminal từ thư mục gốc repo:

```powershell
python -m scripts.crawl_m1 --limit 5000 --dry-run
python -m scripts.crawl_m1 --limit 5000
```

Lệnh mới chạy cả arXiv và Semantic Scholar, lưu SQLite vào `data/crawl_hai`.
Ctrl+C để dừng; chạy lại cùng lệnh để resume. Không chạy notebook và CLI cùng
lúc. Không dùng `scripts.crawl_arxiv` nếu muốn cả references vì đó là CLI arXiv cũ.

Sau khi kiểm tra lỗi và coverage, xuất Parquet và ZIP (cần PyArrow hoạt động):

```powershell
python -m scripts.crawl_m1 --limit 5000 --export-only
```

Python 3.14 của máy hiện tại từng lỗi NumPy/PyArrow; dùng kernel Python 3.12
với dependencies phù hợp cho export. Crawl không import PyArrow.

Đã kiểm tra local ngày 2026-10-22: 28 test đạt; 3 Publication có 4 Version
source cache được nhập vào SQLite và xác minh checksum. Gọi S2 thật trả tổng
86 references, 35 có arXiv ID; xuất 3 dòng papers và 35 dòng references qua
validator schema. Lượt chạy lại 0 request cả hai dịch vụ. Snapshot ZIP đã tạo
thành công. Notebook đã kiểm tra cú pháp cell, chưa chạy trong tài khoản Kaggle.

1. Chạy `python -m scripts.build_kaggle_bundle` khi code thay đổi.
2. Upload `outputs/arxiv_crawler_code.zip` thành Kaggle Dataset private.
3. Import `notebooks/crawl_kaggle.ipynb` vào Kaggle, Add Input dataset code.
4. Bật Internet, chọn CPU. Tạo Secrets `CONTACT_EMAIL`, `S2_API_KEY` và cho
   notebook quyền đọc. Không ghi key vào cell hay output.
5. Chạy mặc định 3 Publication. Xem trạng thái Version, reference jobs và lỗi.
6. Chạy lại để xác minh 0 request. Sau đó thử 50 bài; chỉ tăng LIMIT lên 5000
   khi chất lượng và cách lưu snapshot đã được kiểm tra.

## Dữ liệu và phục hồi

Notebook ghi `/kaggle/working/arxiv_hai/crawl.sqlite`, source theo
`<arxiv_id>/v<n>/source/`, và hai bảng Parquet trong `exports/`.
SQLite giữ metadata, authors theo thứ tự, Version, file/checksum, reference jobs,
references, reference authors và lịch sử chạy. SQL là nguồn checkpoint chính.
JSON cũ chỉ được nhập nếu SQL chưa có, không ghi ngược JSON làm nguồn thứ hai.

Notebook tạo `/kaggle/working/arxiv_hai_snapshot.zip` sau mỗi batch và khi dừng
bằng interrupt có thể xử lý. Tải/lưu ZIP này ra nơi bền vững trước khi phiên mất;
file còn trên đĩa runtime không bảo đảm tồn tại sau khi runtime bị xóa. Dừng ở
ranh giới batch để snapshot nhất quán; không snapshot khi một tiến trình khác ghi.
Để phục hồi, gắn ZIP snapshot làm Input và điền RESTORE_ZIP trong cell phục hồi.
Chỉ phục hồi vào thư mục rỗng. Notebook không tự upload lên Kaggle/Hugging Face.

Metadata SQL cache là snapshot, chưa tự discovery Version mới phát sinh.
Phiên bản lỗi sẽ được thử lại; completed source được kiểm tra checksum.
References được checkpoint từng trang trong một transaction, chỉ hoàn tất khi
API không có trang tiếp theo. Empty từ API không chứng minh bài không có trích
dẫn ngoài đời; có thể Semantic Scholar chưa có độ phủ. 404/429 không phải empty.

## Xuất Parquet

Giữ schema chung `papers` và `references` hiện có. Chỉ xuất references của job
đã hoàn tất và có arXiv ID. Mọi reference, kể cả không có arXiv ID hoặc trùng,
vẫn ở SQL. Xuất một dòng mỗi cặp citing/ref arXiv ID, giữ dòng đầu theo thứ tự
API khi trùng. `ref_submission_date` giữ null, không lấy publicationDate thay thế.
Cell export chỉ xuất các ID đang chọn trong IDS; thay đổi LIMIT sẽ thay phạm vi
hai file export (database vẫn giữ tất cả). Nếu có Publication thiếu metadata
Version, export báo lỗi để sửa thay vì âm thầm bỏ Publication.

Xuất thành công không đồng nghĩa M1 hoàn tất. Cần kiểm tra đầy đủ 5.000 ID,
mọi Version, các lỗi/chưa có metadata, tỷ lệ source và reference coverage;
đo RAM/disk/time trên CPU Colab và viết báo cáo Jupyter Book theo đề.
Runner hiện ghi thời gian/request counts; chưa có benchmark RAM/disk đầy đủ.

Nguồn: https://api.semanticscholar.org/api-docs/graph và
https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/
