# Tích hợp nhánh Liễu vào main

## Sửa lỗi entry point sau cập nhật main ngày 25/10/2026

Commit `b27440f` thay `src/milestone1_crawler.py` tích hợp bằng bản standalone.
Tái hiện: test không import được vì thiếu `arxiv`; kiểm tra AST xác nhận
`BatchedDiscovery`/`LieuPipeline` và các cờ `--data-dir`, `--max-passes`,
`--retry-delay` cũng không còn. Chỉ cài dependency không sửa được hợp đồng
resume. Bản standalone dùng `meta.json`, `status.json`, `done.json` và
`logs/run_log.jsonl`, không dùng cache/receipt hiện có của Range Bảo.

Đã tách rõ hai implementation:

- `src/milestone1_crawler.py` là CLI ổn định, chuyển tiếp tới
  `src/crawl/lieu_pipeline.py`; giữ API công khai và cache đã kiểm chứng.
- `src/lieu_standalone_crawler.py` giữ nguyên từng byte của crawler trong
  `b27440f`. Không chạy bản này để resume `data/crawl-smoke/`. Dependencies
  riêng `arxiv`/`requests` được khai báo trong `src/requirements.txt`;
  runtime tích hợp vẫn chỉ cần `requirements.txt` ở root.
- `src/analyze_errors.py`, `src/diagnose_download.py` mới vẫn được giữ.
  Các script này dùng layout/log standalone; không dùng chúng để kết luận
  tiến độ cache tích hợp. Không chạy script tải chẩn đoán song song worker.
- Log tiến độ Range nay có `issues`: loại tác vụ, Version, trạng thái,
  HTTP status và loại exception. Không ghi response body, header hoặc token.

**150 test và 15 subtest đạt**, bao gồm regression chạy CLI thực, import API,
resume cache không mạng, 404 không thành `non_tex`, S2 lỗi vẫn pending,
pagination và log lỗi không chứa nội dung exception riêng tư. Chưa kiểm thử
runtime standalone; kết quả test này thuộc pipeline tích hợp.

Trước restart đã xác minh 7.763 receipt (7.279 có TeX, 484 `non_tex`) và
sao lưu manifest tại `data/crawl-smoke/manifests/restart-20261025-170531/`.
Lượt trước kết thúc với 4.941/5.000 Publication đủ dữ liệu: 48 source Version
HTTP 404 và 15 Publication S2 HTTP 404, hợp thành 59 Publication còn thiếu.
Probe mạng ngày 25/10: source `2508.02961v1` trả 404 với cả mặc định và
`Accept-Encoding: identity`; S2 `2508.03220` trả 429. Đây là mẫu chẩn đoán,
không chứng minh mọi 404 là vĩnh viễn hoặc mọi lỗi đều cùng nguyên nhân.
Không đổi các lỗi tải thành bản ghi rỗng hoặc đánh dấu hoàn tất.

Đã khởi động lại lúc 17:07 ngày 25/10 bằng commit `0068a74`, Range 5.000 ID,
cùng `data/crawl-smoke/`, `max-passes=3`, nghỉ 1.800 giây giữa lượt. Checkpoint
ban đầu xác nhận vẫn 4.941 Publication đủ, chỉ 59 cần xử lý. Worker, caffeinate
và watcher macOS mới đã được kiểm tra đang chạy. Đọc manifest để lấy tiến độ
mới nhất; không xem snapshot restart này là kết quả cuối.
Kiểm tra lúc 17:09: đã thử 23/59 Publication, vẫn 4.941 đủ; toàn bộ 7.763
receipt cũ giữ nguyên hash và file nguồn tiếp tục qua kiểm tra checksum.
Các lỗi còn ghi nhận lúc đó vẫn là 48 source 404 và 15 S2 404. Báo cáo
local có từng tác vụ ở `manifests/restart-20261025-170531/live-check.json`.

Các phần ngày 24/10 dưới đây là lịch sử lần tích hợp ban đầu; lệnh resume
vẫn dùng CLI ổn định phía trên.

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

## Kiểm chứng chuyển worker ngày 24/10/2026

- Worker cũ đã dừng có kiểm soát và xuất **788 Publication hoàn chỉnh**.
- Lưu snapshot manifest và danh sách **1.318 receipt hợp lệ** dưới
  `data/crawl-smoke/manifests/handover-lieu-20261024/` (ngoài Git).
- Chạy bản Liễu trên bốn Publication mẫu cũ: đủ dữ liệu, không có Publication
  nào cần xử lý lại (`visited_this_pass=0`), giữ bảy Version hợp lệ.
- Chạy mạng thật hai ID mới `2508.03870`, `2508.03871`: cả hai đủ metadata,
  source/receipt và S2; hai Version gồm một TeX và một `non_tex`.
- Đối chiếu lại toàn bộ 1.318 receipt/checksum cũ sau smoke: nguyên vẹn.
  Export lại toàn Range được 790 dòng `papers`, 14.174 dòng `references`.
  Đây là snapshot trước khi khởi chạy lại, không phải số lượng cuối cùng.
- Không dùng tốc độ của hai ID smoke để cam kết ETA toàn Range. Lỗi HTTP,
  source không có hoặc response bị cắt vẫn có thể cần retry.
