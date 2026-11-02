# M1: thử 59 Publication bằng cấu trúc langtucod0n

> **Lưu trữ lịch sử.** Quyết định 25/10 bên dưới đã được thay bởi ADR 0001 (2026-11-01):
> `src/crawl/` là Engine duy nhất trên `main`. `src/lieu_standalone_crawler.py` và
> `scripts/trial_standalone.py` chỉ có trên nhánh `backup/local-2026-10-25`; bản gốc của
> Liễu ở tag `lieu-standalone-final`. Các lệnh `--engine` ở mục Vận hành không còn chạy trên `main`.

## Quyết định và kết quả thực tế — 25/10/2026

Nhóm chọn cấu trúc standalone của `langtucod0n` làm hướng phát triển M1.
CLI `python -m src.milestone1_crawler` mặc định gọi bản đó; giữ discovery theo
lô, requests Session/HTTP Range, một luồng S2 song song với source tuần tự,
và layout `meta.json`, `vN/status.json`, `references*.json`, `done.json`.
Các sửa đổi trong lượt này tập trung vào tính đúng của checkpoint/HTTP/S2.
Chưa chuyển toàn bộ cache 5.000 ID sang layout mới và chưa tuyên bố M1 hoàn tất.

Lượt thử bản gốc `e5be40e` chạy **21:31:44–21:43:47 giờ Việt Nam**, mất
**723,7 giây (12 phút 4 giây)**. Đã xử lý đủ **59/59 Publication** còn thiếu:

- 44 Publication thiếu tổng cộng 48 source Version: **47 Version kết thúc
  với HTTP 404**, **1 Version HTTP 429** sau retry (`2508.07292v2`).
- 15 Publication còn lại thiếu references: **15/15 trả HTTP 404** từ S2.
  Hai nhóm Publication này không chồng nhau trong danh sách đã kiểm tra.
- **0 source Version mới và 0 bộ references mới được tải thành công;
  0 Publication được phục hồi.** Không có response source thành công để
  chứng minh HTTP Range cứu được file trên tập 59 này.
- Bộ đếm của bản gốc ghi 90 request arXiv và 17 request S2, bao gồm retry;
  đây không phải số file hay số Publication tải được.
- Kiểm tra lại toàn cache bằng metadata, manifest và checksum sau lượt thử:
  **4.941/5.000 Publication hoàn chỉnh**, 7.763/7.811 Version được xác minh,
  trong đó 484 Version `non_tex`; references có ở 4.985 Publication.

404 chỉ mô tả kết quả tại thời điểm thử, không chứng minh nguồn thiếu vĩnh viễn.
Không đổi 404 thành `non_tex`, không cộng mẫu kiểm chứng đã có vào tiến độ Range.

## Cách thử để so sánh công bằng

`scripts.trial_standalone` lấy bản crawler **nguyên vẹn từ commit `e5be40e`**
bằng `git show`, lưu một snapshot bất biến ở thư mục dữ liệu rồi thực thi
`download_version` và `fetch_and_save_refs` của snapshot đó. Mã SHA-256:
`9efe0fbd10f5bab24bcc05a3b03fa75a5219a306b9f947cbde75d4b77491752c`.

Harness giữ cách chạy source tuần tự và một worker S2, dùng đúng requests/
HTTP Range/retry/encoding của upstream; không gọi HTTP client tích hợp để tải.
Metadata đã xác minh được dùng lại; không benchmark lại discovery hoặc tải lại
phần đã đủ. Harness chọn đúng tác vụ thiếu nên đây là **thử phục hồi phần thiếu**,
không phải benchmark end-to-end của crawler trên 59 Publication mới hoàn toàn.
Vòng cooldown giữa các Publication của `main()` không nằm trong harness;
retry/backoff bên trong từng request của upstream vẫn được thực thi nguyên vẹn.

Mỗi response tải thành công sẽ được kiểm tra độc lập bằng bộ giải nén có giới
hạn trước khi công nhận. Không ghi vào cache production hoặc upload Hugging Face.
Không chạy crawler thứ hai trong lượt thử. Có khóa cache cũ để ngăn writer cùng lúc.

Bằng chứng cục bộ, không commit vào Git:

- `data/m1-standalone-trial/20261025-e5be40e/plan.json`: danh sách 59 ID,
  từng Version thiếu, metadata đã kiểm tra và trạng thái trước lượt.
- `result.json`: kết quả từng tác vụ, HTTP error cuối cùng, thời gian và tiến độ.
- `upstream_crawler.py`: snapshot mã nguồn được chạy; `data/`: checkpoint
  nguyên gốc sinh trong thử nghiệm. **47 checkpoint `empty/not_found` ở đây
  là bằng chứng hành vi bản gốc, không phải dữ liệu `non_tex` hợp lệ.**
- `cache-audit-after.json`: kết quả kiểm tra toàn Range sau lượt thử.

Tái lập bằng một thư mục output mới:

```sh
python -m scripts.trial_standalone --cache data/crawl-smoke \
  --output data/m1-standalone-trial/new-run --upstream-ref e5be40e
```

## Các sửa đổi sau khi tái hiện lỗi

Tám ca kiểm thử ban đầu thất bại trên bản gốc, rồi đạt sau sửa. Các thay đổi
giữ nguyên cách tổ chức standalone, không thay schema Parquet của nhóm:

1. Source 404 ghi `unavailable`, tiếp tục được retry; HTML, nội dung không nhận
   dạng và archive hỏng không trở thành Version rỗng thành công.
2. `status.json` format 2 có SHA-256 cho payload và từng file; resume kiểm tra
   đúng danh sách file và checksum. File bị sửa/mất không được bỏ qua.
3. `done.json` chỉ ghi khi mọi Version và references đủ. Resume kiểm tra lại
   receipt; checkpoint `done` cũ không hợp lệ được giữ ở `done.invalid.json`.
   Lỗi một Version không bỏ qua các Version sau; lỗi nguồn/S2 lưu trong
   `incomplete.json`. CLI trả exit code 1 khi danh sách chưa hoàn chỉnh.
4. S2 lấy `/references` theo trang cho tới hết, ghi receipt/checksum sau khi
   đủ trang. Trường `date` vẫn là ngày xuất bản S2; không dùng làm ngày nộp arXiv.
5. Đóng response cả khi 404/429; giới hạn tải 128 MiB; kiểm tra Content-Range,
   validator và response 206 không được yêu cầu. Giữ cơ chế tải tiếp của Liễu;
   không nối byte khi không có validator phù hợp. Có test kết nối bị cắt,
   server hỗ trợ Range và server bỏ qua Range trả lại toàn bộ file.
6. Đọc `.env`, bắt buộc email khi chạy CLI; phiên requests của arxiv.py giữ
   User-Agent có contact, chỉ dùng `export.arxiv.org`, không tự theo redirect.
   Có `--data-dir`, `--log-dir`, khóa một writer và chặn nhầm cache tích hợp.

## Kiểm chứng bản sửa

Toàn bộ test đã chạy thật: **169 test và 15 subtest đạt**, không xfail,
trên Python 3.14.7 với arxiv 4.0.1 và requests 2.34.2. Lệnh kiểm tra:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /private/tmp/arxiv-lieu-venv/bin/python -m pytest -q
```

Cache riêng: `data/m1-standalone-smoke/20261025-fixed/`.

- `2508.02874`: tải PDF 936.068 byte, Version rỗng hợp lệ; 11 references S2,
  8 có arXiv ID; `done` hợp lệ.
- `2508.02961`: v1/v2 vẫn HTTP 404; S2 lấy 22 references, 11 có arXiv ID;
  kết quả **`incomplete`**, không có `done.json`.
- `2508.02872`: tải đủ source TeX v1/v2 qua CLI mới, `done` hợp lệ.
- Chạy lại `2508.02872` và `2508.02874`: cả hai `skipped`, **0 request arXiv**,
  cache references được dùng lại. Đây là mẫu đã có trong corpus, không phải
  thêm hai Publication vào số 4.941.

## Vận hành và các việc còn thiếu

```sh
# Hướng M1 mặc định của nhóm: cache standalone mới.
python -m src.milestone1_crawler --ids-file ids.txt --data-dir data/standalone

# Chỉ khi cần vận hành cache cũ đã xác minh:
python -m src.milestone1_crawler --engine integrated --data-dir data/crawl-smoke

# Benchmark phải quan sát đúng thư mục mà crawler ghi.
python -m src.benchmark --data-dir data/standalone --out stats/runs/run_01 -- \
  python -m src.milestone1_crawler --ids-file ids.txt --data-dir data/standalone
```

Đánh giá: cấu trúc của Liễu dùng được làm nền cho nhóm; batching, S2 song song,
HTTP Range và benchmark chia lượt là các phần có thể tiếp tục phát triển.
**Đổi kiến trúc không khắc phục được các response 404/429 quan sát trong lượt này.**
Lỗi báo hoàn tất khi dữ liệu chưa đủ là lỗi code riêng, đã có sửa và test tái hiện.

Chưa hoàn tất các phần sau, không coi bộ test xanh là đã đủ DoD M1:

- Di chuyển 5.000 Publication sang layout mới bằng công cụ có checksum và
  provenance; không dùng thao tác đổi tên thủ công rồi giả lập `done.json`.
- Metadata standalone vẫn cần bổ sung toàn bộ `revised_dates` cho mọi Version
  và bộ export sang hai bảng Parquet đã chốt; hiện mới lưu `published/updated`.
- Benchmark thật trên toàn Range/Colab và đánh giá RAM; lượt thử 59 chỉ đo
  phục hồi tác vụ thiếu. HTTP Range mới được kiểm chứng tình huống đứt mạng
  bằng test offline, chưa gặp một source thành công cần Range trong lượt thật này.
- Watcher cũ đọc `range-run.json`; chưa theo dõi tiến độ standalone mới.
- Với 59 Publication còn thiếu: giữ danh sách lỗi riêng, tôn trọng cooldown
  khi có 429; cần kiểm chứng nguồn/metadata tại lần retry sau thay vì retry dồn
  dập hoặc coi 404 là dữ liệu rỗng.

Nguồn đối chiếu yêu cầu: [đề M1](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/).
