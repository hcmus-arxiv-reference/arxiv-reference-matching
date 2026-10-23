# Tích hợp nhánh Liễu vào main

Yêu cầu ngày 24/10/2026: merge `feat/Lieu-crawler` và tiếp tục Range của Bảo
bằng crawler từ nhánh này. Nhánh nguồn: `0d19257`. Merge giữ lịch sử commit
của Liễu và giữ lại hạ tầng, schema, test, tài liệu đang có trên `main`.
Các thao tác xóa những file chung ở nhánh nguồn không được áp dụng.

## Crawler sử dụng sau tích hợp

Entry point: `python -m src.milestone1_crawler`. Đây là **bản tích hợp** của
crawler Liễu, không phải chạy nguyên bản nhánh nguồn trên dữ liệu cũ.

- Giữ thiết kế discovery theo lô (mặc định 50 ID) và một worker S2 chạy
  đồng thời với luồng tải source arXiv của Liễu.
- Dùng client HTTP chung để mọi request arXiv, kể cả metadata/version/source,
  có cùng giới hạn ít nhất 3,1 giây và chỉ một kết nối arXiv tại một thời điểm.
- Metadata batch thiếu/hỏng thì hỏi lại từng ID; không coi thiếu trong batch
  là bằng chứng Publication không tồn tại. Đọc đủ ngày sửa các Version.
- Dùng bộ giải nén có giới hạn, checksum và receipt của main. Không chấp nhận
  source hỏng chỉ vì đã tồn tại file checkpoint. 404/410 vẫn là `unavailable`.
- Dùng S2 pagination đầy đủ; lỗi S2 giữ Publication chưa hoàn chỉnh. Không
  biến publicationDate thành ngày nộp arXiv.
- Manifest/cache chỉ được ghi ở luồng chính; worker phụ chỉ đọc cache hoặc
  lấy và kiểm tra response S2. Tiếp tục dùng runner Range và notifier hiện có.
- Contact/API key đọc từ cấu hình của người đang chạy; bỏ email mặc định
  của thành viên trong source gốc.

Không cần chuyển đổi/move dữ liệu. Source vẫn ở
`data/crawl-smoke/raw/<publication-key>/v<n>/`; metadata, references và manifest
giữ nguyên hợp đồng. Schema Parquet không thay đổi. Chỉ những phần cache
không còn hợp lệ hoặc chưa có mới cần tải lại.

## Lệnh chạy tiếp toàn Range

Chỉ chạy khi worker trước đã kết thúc và đã bỏ cờ `STOP_RANGE` do mình tạo:

```sh
ARXIV_RANGE_PREFIX=2508 ARXIV_RANGE_START=2872 ARXIV_RANGE_END=7871 \
  /private/tmp/arxiv-lieu-venv/bin/python -u -m src.milestone1_crawler \
  --data-dir data/crawl-smoke --discover-batch 50 --max-passes 3 --retry-delay 1800
```

`range-run.json` có `engine: "lieu"`. Số lượng và các trạng thái vẫn mang
cùng ý nghĩa như [hướng dẫn vận hành](full-range-crawl.md). Lệnh không upload
Hugging Face. Chạy lại notifier riêng sau khi chuyển worker; không dùng
snapshot của lượt smoke nhỏ để tuyên bố Range đã hoàn tất.

Môi trường mới: `/private/tmp/arxiv-lieu-venv`; môi trường review cũ mất
`pyvenv.cfg` khi kiểm tra ngày 24/10, nên không dùng nó để khởi động lại.
Cài runtime từ `requirements.txt`; `src/requirements.txt` tham chiếu runtime
và bổ sung thư viện notebook tùy chọn. Crawler tích hợp dùng Atom parser
chung, không còn cần thư viện `arxiv` riêng.

## Các công cụ khác từ nhánh Liễu

- `src.make_ids`: tạo danh sách ID; file sinh ra đặt trong `data/`.
- `src.benchmark`: đo tiến trình con; dùng thư mục đo mới, không xóa cache
  đang có. Benchmark resume phải ghi rõ là resume.
- `src.make_stats`: đọc **log định dạng nguyên bản Liễu**, không đọc trực tiếp
  `crawl.jsonl` của pipeline tích hợp. Không dùng nó để công bố thống kê Range
  hiện tại khi chưa có bước ánh xạ log phù hợp.
- `milestone1_technical_guide.md` được giữ làm tài liệu lịch sử từ nhánh nguồn;
  lệnh và hợp đồng tích hợp hiện hành được mô tả ở tài liệu này.

## Kiểm thử

**115 test và 15 subtest đạt**, có kiểm tra batch/revision dates, lỗi batch,
S2 chạy chồng thời gian với source và pagination, dùng lại cache main, cache
hỏng, S2 lỗi rồi retry, PDF so với 404 và exit code của benchmark.
Test benchmark cần quyền đọc tiến trình/RAM của hệ điều hành; sandbox hạn chế
quyền này nên lần kiểm chứng toàn bộ chạy ngoài sandbox, HTTP vẫn giả lập.
Kết quả offline không chứng minh tốc độ hoặc độ đầy đủ của toàn Range.
