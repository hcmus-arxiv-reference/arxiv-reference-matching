# Crawl toàn Range của Bảo

Range: `2508.02872`–`2508.07871`, bao gồm hai đầu, **5.000 ID được giao**.
Số ID được giao không đồng nghĩa số Publication đã tải đủ.

## Quy trình đang dùng

`scripts.crawl_range` dùng lại pipeline hiện có để tải metadata arXiv, mọi
Version và references Semantic Scholar. Chạy tuần tự, arXiv cách ít nhất
3,1 giây giữa các request; API key/email chỉ đọc từ cấu hình cục bộ.
Lệnh này không upload Hugging Face.

Dùng `data/crawl-smoke/` để giữ và tiếp tục cache đã xác minh trước đó.
Tên thư mục được giữ nguyên dù phạm vi chạy nay là toàn Range.

- `raw/<publication-key>/v<n>/`: TeX/BibTeX và receipt/checksum.
- `metadata/`, `references/`: cache được kiểm tra checksum trước khi dùng lại.
- `manifests/crawl.jsonl`: checkpoint từng tác vụ discovery/source/references.
- `manifests/range-run.json`: tiến độ gần nhất, PID, lượt chạy và ID còn thiếu.
- `manifests/range-process.log`: log của tiến trình chạy nền.
- `tables/papers.parquet`, `tables/references.parquet`: tổng hợp các Publication
  đủ dữ liệu, được xây lại **cuối mỗi lượt hoặc khi dừng có kiểm soát**.
  Trong khi lượt đầu chưa xong, các bảng có thể vẫn là đầu ra cũ.

Một Publication chỉ được tính hoàn chỉnh khi metadata hợp lệ, đủ receipt
và checksum cho mọi Version dự kiến, và references được lấy thành công.
Version `non_tex` có receipt rỗng hợp lệ vẫn được tính đã xử lý.
Source 404/410 được giữ là `unavailable`; lỗi HTTP/network không bị đổi thành
`non_tex`. Các trường hợp chưa đủ vẫn nằm trong danh sách cần xử lý.

Mỗi lần chạy tối đa ba lượt. Lượt sau chỉ xử lý Publication chưa đủ, dùng lại
các phần đã xác minh, nghỉ 30 phút giữa các lượt. Hết ba lượt mà còn thiếu thì
trạng thái là `incomplete`, không tuyên bố hoàn thành. Dừng khi ổ đĩa còn dưới
5 GiB; đây là ngưỡng vận hành, không phải ước lượng dung lượng corpus.

## Tiếp tục sau khi tiến trình đã kết thúc

Không khởi chạy thêm khi tiến trình cũ còn hoạt động. `.pipeline.lock` ngăn
hai writer dùng cùng thư mục; vẫn phải tránh crawler khác ở thư mục/máy khác
cùng tải arXiv. Kiểm tra PID trong `range-run.json` bằng `ps` khi cần.

```sh
ARXIV_RANGE_PREFIX=2508 ARXIV_RANGE_START=2872 ARXIV_RANGE_END=7871 \
  /private/tmp/arxiv-reference-review-venv/bin/python -u -m scripts.crawl_range \
  --data-dir data/crawl-smoke --max-passes 3 --retry-delay 1800
```

Đường dẫn Python trên là môi trường đã kiểm thử của máy này; nếu môi trường
tạm không còn, tạo virtualenv tại đường dẫn không chứa dấu `:` và cài
`requirements.txt` trước khi chạy lại.

Theo dõi log:

```sh
tail -f data/crawl-smoke/manifests/range-process.log
```

Dừng có kiểm soát sau Publication hiện tại:

```sh
touch data/crawl-smoke/STOP_RANGE
```

Chờ trạng thái `stopped` và tiến trình kết thúc. Trước khi tiếp tục, bỏ đúng
file cờ `STOP_RANGE` đã tạo; không xóa manifest, receipt hoặc dữ liệu source.
Ctrl+C/SIGTERM cũng được xử lý để giữ checkpoint và xuất phần đã hoàn chỉnh.

`caffeinate -i -w <PID>` đã được dùng cho lượt chạy nền để ngăn idle sleep.
Nó không bảo đảm tiến trình tiếp tục khi đóng nắp/tắt máy hoặc mất mạng.

## Bằng chứng và giới hạn

- Ngày 22/10/2026: kiểm tra arXiv và S2 thật thành công; khởi chạy toàn Range
  lúc 18:31 giờ Việt Nam. Ban đầu có bốn Publication đủ dữ liệu trong cache.
- Bộ test sau khi thêm trình chạy Range: **104 test, 15 subtest đạt**.
  Test mới kiểm tra retry chỉ phần thiếu, resume, cache hỏng, `non_tex`,
  tổng hợp nhiều Publication và dừng an toàn. Không phải benchmark mạng thật.
- Snapshot lúc 17:12 ngày 23/10/2026: **222 Publication đủ dữ liệu**, metadata
  của 255 Publication, 361 Version đã xác minh (33 `non_tex`), references
  của 250 Publication. Đây là snapshot giữa lượt; xem manifest để lấy số mới.
- Lỗi còn ghi nhận: HTTP 429, `IncompleteRead`, `URLError` và source
  `unavailable`. Log có khoảng dài không tiến triển; chưa kết luận nguyên nhân.
- Chưa hoàn thành 5.000 ID, chưa benchmark toàn Range, chưa upload kết quả
  lượt này. Không thay schema Parser/Matching.
