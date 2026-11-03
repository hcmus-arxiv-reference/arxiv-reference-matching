# arXiv Reference Matching — Nhóm 3 KHDL24

Đồ án Nhập môn Khoa học Dữ liệu (HCMUS): thu thập bài arXiv, parse nguồn LaTeX
thành cây phân cấp, rồi ghép BibTeX entry với Reference của Semantic Scholar
bằng pipeline học máy.

- [Đề tổng quan](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/)
- [Milestone 1: Crawling](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/)
- [Milestone 2: Parsing](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/parsing/)
- [Milestone 3: Matching](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/matching/)

Nhóm trưởng: [NTBao-coder](https://github.com/NTBao-coder). Thành viên:
[ngochai06](https://github.com/ngochai06), [nhminh107](https://github.com/nhminh107),
[langtucod0n](https://github.com/langtucod0n).

## Trạng thái (2026-11-02)

- **M1 – Crawling:** `src/crawl/` là Engine duy nhất trên `main`
  ([ADR 0001](docs/adr/0001-src-crawl-la-khung-duy-nhat.md)). Discovery theo lô
  (`BatchedDiscovery`) và tải references song song với source là đóng góp của Liễu
  (`langtucod0n`), nay là cách cài đặt mặc định của `CrawlPipeline`; mọi lệnh crawl
  (`src.milestone1_crawler`, `scripts.crawl_range`, `scripts.crawl`) đều dùng chúng. Range của Bảo (`2508.02872`–`2508.07871`):
  lần kiểm tra 25/10 có 4.941/5.000 Publication hoàn chỉnh; 59 Publication còn
  thiếu, phần lớn do arXiv trả HTTP 404 ([lượt thử](docs/m1-standalone-trial.md)).
  Range của các thành viên khác chưa gộp.
- **M2 – Parsing:** mới có lớp gom source của một Version
  ([mô tả](docs/milestone2-source.md)) và kiểu cột M2 trong `src/common/schema.py`.
  Chưa có parser cây phân cấp hay BibTeX.
- **M3 – Matching:** chưa bắt đầu.
- Kế hoạch merge đang thực hiện và các việc còn mở:
  [handoff 2026-11-01](docs/handoff/2026-11-01-merge-lieu.md).

## Cài đặt và kiểm thử

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
```

Nếu đường dẫn repo chứa dấu `:` (như `HK1_26:27`), Python không tạo được
virtualenv tại đó. Tạo ở đường dẫn khác, ví dụ `python3 -m venv /tmp/arxiv-venv`,
rồi thay `.venv/bin/python` bằng `/tmp/arxiv-venv/bin/python`.

Copy `.env.example` thành `.env` và điền cấu hình cục bộ (`CONTACT_EMAIL` cho
arXiv; `HF_TOKEN`, `HF_REPO_ID`, `MEMBER_NAME` khi upload). Test không cần token.
Không commit `.env` hoặc dữ liệu.

## Crawl (M1)

```sh
# Chạy toàn Range theo lô, có checkpoint/resume và retry phần thiếu.
.venv/bin/python -m src.milestone1_crawler --data-dir data/crawl-smoke

# Một vài ID hoặc danh sách ID.
.venv/bin/python -m src.milestone1_crawler --id 2508.02872 --data-dir data/crawl-smoke
.venv/bin/python -m src.make_ids 2508.02872 2508.07871 -o ids.txt
.venv/bin/python -m src.milestone1_crawler --ids-file ids.txt --data-dir data/crawl-smoke

# Crawl một đoạn và upload lên dataset Hugging Face private.
.venv/bin/python -m scripts.check_hf
.venv/bin/python -m scripts.crawl --start 2872 --end 2874 --upload
.venv/bin/python -m scripts.crawl --start 2872 --end 2874 --upload-only
```

Chạy lại cùng lệnh để resume; Version đã xác minh checksum không tải lại. Không
chạy hai crawler cùng lúc trên một thư mục dữ liệu (có file lock). API Python:
`from src.crawl.api import run_crawl`. File thô lên
`raw/<member>/<publication-key>/v<n>/`, bảng lên `tables/<member>/<tên bảng>.parquet`.
Chi tiết: [pipeline crawl](docs/crawl-pipeline.md).

## Benchmark và kiểm tra chất lượng

```sh
.venv/bin/python -m src.benchmark --data-dir data/bench --out stats/runs/run_01 -- \
  .venv/bin/python -m src.milestone1_crawler --ids-file ids.txt --data-dir data/bench
.venv/bin/python -m scripts.validate_crawl --data-dir data/bench \
  --benchmark stats/runs/run_01/benchmark.json
```

Giới hạn hiện tại: `src/benchmark.py` đếm Publication xong qua `*/done.json`
(layout standalone), nên trường `done_papers_*` bằng 0 trên layout `src/crawl/`.
Thời gian, RAM và dung lượng vẫn đo đúng; số Publication hoàn chỉnh lấy từ
`scripts.validate_crawl`.

Định nghĩa trường và quy trình so sánh giữa các thành viên:
[docs/benchmark](docs/benchmark/README.md).

## Gom source cho M2

```sh
.venv/bin/python -m scripts.assemble_source \
  --source-dir data/crawl-smoke/raw/2508-02872/v1 --output out/2508-02872v1.json
```

## Tài liệu

- [`CONTEXT.md`](CONTEXT.md): thuật ngữ (Publication, Version, Range, Stage, Engine).
- [`docs/adr/`](docs/adr/): quyết định kiến trúc đã chốt.
- [`docs/handoff/`](docs/handoff/): biên bản các buổi chốt kiến trúc và kế hoạch merge.
- Nhánh thành viên (`Hai`, `feat/Minh-crawler`, `feat/nghiem-crawler`) và tag
  `lieu-standalone-final` giữ nguyên làm case study, không merge vào `main`.
