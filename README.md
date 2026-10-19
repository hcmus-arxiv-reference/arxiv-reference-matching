# arXiv Reference Matching — Nhóm 3 KHDL24

Đồ án Nhập môn Khoa học Dữ liệu: thu thập bài báo arXiv, phân tích nguồn LaTeX thành cấu trúc phân cấp, rồi ghép các trích dẫn BibTeX với metadata tham khảo bằng một pipeline học máy.

> **Trạng thái (2026-10-19):** đã có source crawler Python và CLI trong `src/crawl/`, `scripts/crawl.py`. Kết quả test: **57 đạt, 9 xfail (lỗi còn mở), 15 subtest đạt**; đây là test offline, chưa xác minh crawl thật hoặc độ phủ mọi Version. Review đã tái hiện lỗi discovery, nhận diện source và resume; **chưa đủ điều kiện chạy toàn Range hoặc đánh dấu hoàn thành Milestone 1**. Xem [review crawler](docs/crawl-review.md). Hạ tầng `src/common/` đã có; Parser chưa triển khai và schema toàn dự án chưa đóng băng.

Kiểm tra các module hiện có từ root repo (lần review mới dùng Python 3.14.7):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
```

Nếu đường dẫn repo chứa dấu `:` (như `HK1_26:27`), Python từ chối tạo
virtualenv tại đó. Tạo ở đường dẫn không chứa `:`, ví dụ
`python3 -m venv /tmp/arxiv-reference-venv`, rồi thay `.venv/bin/python`
trong các lệnh bằng `/tmp/arxiv-reference-venv/bin/python`.

Tắt tự nạp plugin để tránh plugin pytest cài ngoài dự án ảnh hưởng bộ test.
Copy `.env.example` thành `.env` và điền cấu hình cục bộ khi chạy tác vụ thật;
test dùng cấu hình tổng hợp, không cần token. Không commit `.env` hoặc dữ liệu.

Sau khi điền `HF_TOKEN`, `HF_REPO_ID`, `MEMBER_NAME`, tạo/xác minh dataset
private bằng lệnh sau (gọi mạng thật, không upload dữ liệu):

```sh
.venv/bin/python -m scripts.check_hf
```

## Crawl theo range ID

Crawler đã được tách thành các module trong `src/crawl/`:

- `http_client.py`: User-Agent, tuần tự trong một client, khoảng nghỉ mặc định 3 giây và retry lỗi tạm thời; chưa chặn cấu hình thấp hơn 3 giây.
- `discovery.py`: đọc metadata Atom; hiện chưa xác định đúng số Version từ hậu tố ID và chưa bảo đảm đủ ngày sửa đổi.
- `source.py`: tải source và giữ `.tex`/`.bib` trong tar; còn lỗi phân loại PDF/HTML và trạng thái `non_tex`.
- `manifest.py`: checkpoint JSONL; bỏ qua bản ghi `success`, nhưng chưa kiểm tra lại file/checksum và còn lỗi dòng cuối bị cắt.
- `semantic_scholar.py`: client độc lập, phân trang tối đa 1.000 bản ghi mặc định; chưa nối vào pipeline/CLI.
- `pipeline.py`: điều phối discovery và source download, lỗi một bài không dừng cả range.

Các lệnh dưới đây mô tả CLI hiện có. Cần sửa các lỗi trong review trước khi
thu thập corpus chính thức; chưa chạy thử tải thật trong lần cập nhật này.

Chạy thử vài ID:

```sh
.venv/bin/python -m scripts.crawl \
  --id 2508.02872 --id 2508.02873 --min-interval 3
```

Chạy range đã cấu hình trong `.env` (`2508.02872`–`2508.07871`):

```sh
.venv/bin/python -m scripts.crawl
```

Hoặc giới hạn một đoạn để kiểm tra:

```sh
.venv/bin/python -m scripts.crawl --start 2872 --end 2876
```

Kết quả nằm trong `data/metadata/`, `data/raw/<publication-key>/v<n>/` và
checkpoint ở `data/manifests/crawl.jsonl`. Chạy lại đúng lệnh sẽ resume; không
đặt `--min-interval` thấp hơn 3 giây khi gọi arXiv.

Nhóm trưởng: [NTBao-coder](https://github.com/NTBao-coder). Thành viên: [ngochai06](https://github.com/ngochai06), [nhminh107](https://github.com/nhminh107), [langtucod0n](https://github.com/langtucod0n).

[Checklist dành cho nhóm trưởng](docs/team-lead-checklist.md) theo dõi việc đã
xác minh, các quyết định còn mở và bằng chứng cần có trước khi chạy hàng loạt/nộp bài.

- [Đề tổng quan](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/)
- [Milestone 1: Crawling](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/)
- [Milestone 2: Parsing](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/parsing/)
- [Milestone 3: Matching](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/matching/)

## 1. Bài toán và sản phẩm cuối

Luồng xử lý chính:

```text
Khoảng ID được giao
    → danh sách bài + tất cả phiên bản
    → source LaTeX + metadata + reference metadata
    → hierarchy + BibTeX chuẩn hóa
    → nhãn + đặc trưng + mô hình ghép trích dẫn
    → top 5 ứng viên + MRR
    → dataset Parquet, Jupyter Book và poster
```

Ví dụ: một entry BibTeX chứa tiêu đề, tác giả và năm xuất bản cần được ghép với arXiv ID đúng trong danh sách references của chính bài đang xét. Đây là bài toán đối sánh thực thể, không phải tìm bài tương tự trên toàn bộ arXiv.

Sản phẩm theo đề:

- **Một repo code public** dùng xuyên suốt cả ba milestone, giữ lịch sử phát triển.
- **Một repo Jupyter Book riêng**, host trên GitHub Pages, chứa báo cáo Milestone 1 và 2. Bảng và biểu đồ được sinh bằng code khi build.
- **Dataset cuối trên Hugging Face**, dạng Parquet phân mảnh, theo schema Milestone 3.
- **Poster một slide PPTX, A2 dọc**, trình bày kết quả nổi bật và đánh giá.

Theo thông báo Moodle nhóm đã cung cấp, mỗi sinh viên tự upload phần dữ liệu được giao lên tài khoản Hugging Face cá nhân và nộp link; đại diện nhóm nộp Jupyter Book và poster. Vì vậy cần giữ ánh xạ giữa bài báo và khoảng ID cá nhân ngay từ đầu. Khi thông báo Moodle và đề tổng quát khác mức chi tiết, đối chiếu hướng dẫn của giảng viên phụ trách.

## 2. Chiến lược giải bài

**Làm một pipeline nhỏ chạy xuyên suốt trước, rồi mới tăng quy mô.**

1. Chọn một bài trong khoảng ID được giao; thử từ tải source đến trích bibliography và xếp hạng ứng viên.
2. Mở rộng lên 10–20 bài đa dạng: một/nhiều file, một/nhiều phiên bản, `.bib`/`\bibitem`, có phụ lục, công thức, bảng và trường hợp thiếu source.
3. Kiểm tra dữ liệu trung gian bằng tay, sửa giả định sai và viết kiểm thử cho những lỗi đã gặp.
4. Chạy toàn bộ khoảng ID; đo độ đầy đủ, lỗi, thời gian và dung lượng.
5. Cải thiện chất lượng dựa trên phân tích lỗi; cập nhật báo cáo từ cùng dữ liệu đầu ra.

Không cần bắt đầu bằng mô hình phức tạp. Crawl đủ, parser đúng, nhãn đáng tin và đánh giá không rò rỉ dữ liệu tạo nền tảng cho kết quả tốt.

## 3. Cây thư mục chính đề xuất

Đây là **cấu trúc mục tiêu**, chưa phải danh sách file đã tồn tại. Chỉ tạo module khi bắt đầu triển khai chức năng tương ứng.

```text
arxiv-reference-matching/
├── Readme.md
├── .gitignore
├── requirements.txt                 # Điểm cài đặt chung; có thể -r src/requirements.txt
├── configs/
│   ├── crawl.yaml                   # ID, endpoint, nhịp request, đường dẫn
│   ├── parse.yaml                   # Quy tắc chuẩn hóa và parsing
│   └── matching.yaml                # Seed, feature, mô hình, split
├── src/
│   ├── __init__.py
│   ├── requirements.txt             # Dependency theo cấu trúc nộp trong đề
│   ├── common/
│   │   ├── __init__.py
│   │   ├── identifiers.py           # ID bài, phiên bản, mã thư mục
│   │   ├── schemas.py               # Kiểu dữ liệu, trường bắt buộc
│   │   └── io.py                    # Đọc/ghi, checkpoint, logging
│   ├── crawl/
│   │   ├── __init__.py
│   │   ├── discovery.py             # Metadata → bài và phiên bản
│   │   ├── http_client.py           # Session, timeout, rate limit, retry
│   │   ├── sources.py               # Tải và đọc source an toàn
│   │   ├── references.py            # Semantic Scholar + phân trang
│   │   └── pipeline.py              # Điều phối crawl, tiếp tục sau lỗi
│   ├── parse/
│   │   ├── __init__.py
│   │   ├── source_graph.py          # File gốc, input/include, thứ tự nội dung
│   │   ├── hierarchy.py             # Cây tài liệu và loại phần tử
│   │   ├── normalize.py             # Văn bản và công thức
│   │   ├── bibliography.py          # BibTeX/bibitem, hợp nhất citation key
│   │   └── deduplicate.py           # Khử trùng lặp qua các phiên bản
│   ├── matching/
│   │   ├── __init__.py
│   │   ├── labels.py                # Nhãn tay, nhãn tự động, nguồn nhãn
│   │   ├── split.py                 # Chia tập theo bài báo
│   │   ├── features.py              # Đặc trưng của cặp entry–reference
│   │   ├── model.py                 # Huấn luyện, chấm điểm, xếp hạng
│   │   └── evaluate.py              # MRR top 5 và phân tích lỗi
│   └── export/
│       ├── __init__.py
│       └── parquet.py               # Bảy bảng + kiểm tra schema
├── scripts/                         # Entry point mỏng, gọi code trong src/
├── notebooks/                       # Khám phá và thử nghiệm; không chứa logic duy nhất
├── tests/                           # Ví dụ nhỏ tự tạo, kết quả mong đợi
├── docs/                            # Schema, quy tắc nhãn, quyết định kỹ thuật
├── data/                            # Cục bộ, gitignore toàn bộ trừ README
│   ├── README.md
│   ├── manifests/                   # Trạng thái bài/phiên bản, khoảng ID cá nhân
│   ├── raw/                         # Metadata và source văn bản theo phiên bản
│   ├── processed/                   # hierarchy.json, refs.bib
│   ├── labels/                      # Nhãn và nguồn gốc nhãn
│   └── export/                      # Parquet theo từng cá nhân
├── outputs/                         # Metrics, log, model: không commit mặc định
└── .github/
    ├── CODEOWNERS
    ├── pull_request_template.md
    └── workflows/ci.yml
```

Dùng một danh sách dependency làm nguồn chính; nếu giữ cả hai `requirements.txt`, file gốc chỉ tham chiếu file trong `src/` để tránh lệch phiên bản. Cấu trúc trong đề đặt dependency dưới `src/`; cấu trúc hạ tầng ban đầu của nhóm đặt ở root, nên cần thống nhất khi triển khai.

Repo báo cáo riêng dự kiến:

```text
arxiv-reference-matching-report/
├── README.md
├── requirements.txt                 # Jupyter Book 1.x theo lựa chọn ban đầu
├── _config.yml
├── _toc.yml
├── intro.md
├── milestone1.ipynb                 # Số liệu crawl, phân tích corpus
├── milestone2.ipynb                 # Parsing, dedup, benchmark
└── .github/workflows/deploy.yml
```

Notebook báo cáo đọc đầu ra có phiên bản xác định và tạo hình/bảng lúc build. Không crawl lại toàn bộ Internet trong mỗi lần build báo cáo; cần thiết kế bước lấy dữ liệu đầu vào tái lập được, phù hợp quyền truy cập và giới hạn tài nguyên.

## 4. Kiến thức cần học và bài tập nhỏ tương ứng

### 4.1. Python và HTTP — học trước

- Python: hàm, module, dict/list/set, exception, generator, `pathlib`, JSON và logging.
- HTTP: URL, query parameters, headers, status code, timeout và response body.
- Phân biệt JSON, XML/Atom, HTML và nội dung nhị phân.
- Dùng Session để tái sử dụng kết nối; hiểu rate limit và retry có giới hạn.

**Bài tập:** gọi API cho một ID, lưu metadata ra JSON, xử lý được trường thiếu và lỗi request. Đọc [Requests Quickstart](https://requests.readthedocs.io/en/latest/user/quickstart/): parse được JSON không có nghĩa request đã thành công; vẫn phải kiểm tra HTTP status.

### 4.2. Xử lý file và dữ liệu lớn

- Đọc JSON Lines theo dòng; không nạp toàn bộ snapshot lớn vào RAM.
- Nhận diện tar/gzip/plain text bằng nội dung, không chỉ phần mở rộng.
- Ghi file tạm rồi đổi tên sau khi hoàn tất; checksum và checkpoint.
- Khi giải nén, ngăn đường dẫn thoát ra ngoài thư mục đích và liên kết nguy hiểm.

**Bài tập:** lọc một tập ID từ metadata lớn và tải được source của một phiên bản; chạy lại không làm lại phần đã hoàn tất.

### 4.3. LaTeX và cấu trúc dữ liệu

- Học `\documentclass`, `\begin{document}`, `\section`, `\input`, `\include`, môi trường toán, `\cite`, `\bibitem` và `.bib`.
- Học tree, stack, DFS, phát hiện vòng lặp và hashing.
- Regex dùng cho mẫu cục bộ; cấu trúc lồng nhau cần parser/trạng thái.

**Bài tập:** tạo tài liệu giả có hai file, hai section, một công thức và bibliography; viết ra hierarchy mong đợi trước khi code.

### 4.4. Thống kê và ML

- pandas, thống kê thiếu dữ liệu, phân phối số phiên bản/reference/element.
- TF–IDF, cosine similarity, độ trùng token, đối sánh tên tác giả.
- Nhãn đúng/sai/chưa biết; train/validation/test; phân loại và xếp hạng.
- Data leakage, mất cân bằng lớp, MRR và phân tích lỗi.

**Bài tập:** chấm điểm các ứng viên cho một entry bằng độ giống tiêu đề, rồi tính reciprocal rank bằng tay để đối chiếu code.

## 5. Cách crawl đề xuất

### 5.1. Tách ba nguồn dữ liệu

1. **arXiv API hoặc snapshot metadata:** khám phá bài, metadata, thông tin phiên bản.
2. **Source arXiv:** tải LaTeX của từng phiên bản cụ thể.
3. **Semantic Scholar:** lấy danh sách reference và external IDs cho từng publication.

Một nguồn không thay thế được tất cả các nguồn khác. Metadata/abstract không phải source LaTeX; danh sách reference từ Semantic Scholar không phải nội dung bibliography gốc trong bài.

### 5.2. Bước 1 — Chốt danh sách và phiên bản

- Nhận đúng khoảng ID được giao; không chọn theo chủ đề tùy ý.
- Giữ ID như chuỗi, tách base ID và version. Không ép ID thành số thực.
- Giữ ID cũ dạng `hep-th/9901001`; dùng mã thư mục an toàn riêng, có ánh xạ ngược.
- Với tập nhỏ, thử arXiv API. Với nhiều bài, cân nhắc lọc snapshot Kaggle theo dòng.
- Lấy version history từ metadata có trường phiên bản; nếu chỉ biết version mới nhất, xác minh đầy đủ danh sách dự kiến thay vì chỉ tải bản mới nhất.
- Lưu thời điểm/snapshot discovery; kiểm tra lại bài thiếu hoặc lịch sử không khớp.

Thư viện [arxiv.py](https://github.com/lukasschwab/arxiv.py) hỗ trợ truy vấn bằng `Client.results(search)`. Ví dụ cũ dùng `Search.results()` hoặc `Result.download_source()` không phù hợp với bản 4.x; xem [release notes](https://github.com/lukasschwab/arxiv.py/releases). Chốt và ghi phiên bản dependency khi triển khai.

### 5.3. Bước 2 — Lập manifest và hàng đợi

Mỗi tác vụ tải source gắn với một cặp `(arxiv_id, version)`. Manifest nội bộ nên có:

```text
arxiv_id, version, assigned_owner, source_url,
status, attempts, http_status, fetched_at,
local_path, checksum, error_reason
```

Các trạng thái nên phân biệt: `pending`, `success`, `retryable_error`, `unavailable`, `non_tex`. Một lỗi 429 hoặc timeout không được tự biến thành kết luận “bài không có source”. Trạng thái lấy references được quản lý riêng ở cấp publication.

### 5.4. Bước 3 — Tải source từng phiên bản

Endpoint được đề bài hướng dẫn:

```text
https://export.arxiv.org/src/{arxiv_id}v{version}
```

- Dùng User-Agent mô tả dự án và địa chỉ liên hệ đã cấu hình.
- Kiểm tra status, kiểu nội dung và nội dung thực tế trước khi lưu thành công. Có thể nhận trang HTML báo lỗi thay vì archive.
- Giữ `.tex`, `.bib`, `.bbl`, `.sty`, `.cls` và file văn bản liên quan; bỏ ảnh nhị phân sau khi xác định loại file.
- Giữ nguyên lệnh hình/bảng trong LaTeX.
- Bài không có TeX vẫn giữ metadata và trạng thái rõ ràng.
- Giữ source văn bản theo phiên bản để xuất bảng `sources` ở cuối dự án.

Theo [quy định API arXiv](https://info.arxiv.org/help/api/tou.html), legacy API dùng tối đa một request mỗi ba giây và một kết nối tại một thời điểm; giới hạn áp dụng tổng thể các máy do mình điều khiển. Thiết kế bộ điều tiết dùng chung; với source download, áp dụng nhịp thận trọng theo đề và kiểm tra chính sách endpoint. Chuyển sang nhiều notebook không làm tăng hạn mức được phép.

### 5.5. Bước 4 — Lấy references

Tra cứu publication qua định danh `ARXIV:{id}`, rồi lấy references với các trường cần dùng: title, authors, externalIds, publicationDate/year và Semantic Scholar paperId. Nếu dùng endpoint có phân trang, phải lấy hết các trang. Đối chiếu tên trường với [Academic Graph API](https://api.semanticscholar.org/api-docs/graph).

- `references.json` phục vụ matching chỉ chứa ứng viên có arXiv ID theo yêu cầu đề.
- Ghi thống kê references không có arXiv ID để giải thích mức bao phủ.
- Ngày thiếu giữ null/trạng thái thiếu; không tự dựng ngày `01-01` từ một năm.
- Cache ở cấp publication, tránh gọi lại chỉ vì cùng bài có nhiều phiên bản.
- Không mặc định metadata tham khảo cấp bài là ground truth riêng cho từng phiên bản.
- Rate limit Semantic Scholar cấu hình riêng và tuân theo hạn mức thực tế; không dùng mặc định hạn mức arXiv cho dịch vụ này.

### 5.6. Bước 5 — Xử lý lỗi và chạy tiếp

- **429:** tôn trọng `Retry-After` nếu có; chờ tăng dần kèm jitter.
- **Timeout/5xx:** retry có giới hạn, lưu lỗi để chạy lại sau.
- **403:** kiểm tra endpoint, yêu cầu xác thực và chính sách truy cập; không retry dồn dập.
- **404:** kiểm tra ID, version và nguồn trả lỗi; phân biệt với lỗi không có source.
- Cache kết quả đã xác minh; không chạy lại toàn bộ khi chỉ một số bài lỗi.

Không lấy xoay proxy, đổi IP hoặc vượt CAPTCHA làm hướng chính. Nếu đường truy cập tự động không được hỗ trợ, dùng API/bulk access chính thức hoặc hỏi giảng viên về phương án thay thế.

### 5.7. Điều kiện hoàn thành Milestone 1

- Đối chiếu số bài và phiên bản dự kiến với số đã thu được.
- Có nguyên nhân cho phần thiếu và có thể chạy tiếp phần lỗi.
- Source đọc được; metadata/reference metadata đáp ứng schema hoặc ghi thiếu rõ ràng.
- Báo cáo có phân tích corpus, mức bao phủ và lỗi, được tạo từ dữ liệu thật.
- Kiểm tra thủ công mẫu có cả trường hợp bình thường và ngoại lệ.

## 6. Kaggle và Colab: dùng vào đâu?

### Kaggle làm nguồn metadata

[Cornell arXiv Dataset](https://www.kaggle.com/datasets/Cornell-University/arxiv) cung cấp snapshot metadata, có lịch sử phiên bản. Theo mô tả dataset và phần discovery trong đề, đây là đường tiếp cận hợp lệ để lập danh sách bài. Nó không thay thế bước tải đủ source LaTeX từng phiên bản và lấy reference metadata.

Phương án:

```text
Kaggle metadata snapshot
    → lọc khoảng ID theo dòng
    → danh sách bài + phiên bản + mốc snapshot
    → bổ sung metadata thiếu qua arXiv
    → tải source từng phiên bản
    → lấy references qua Semantic Scholar
```

Có thể dùng [kagglehub](https://github.com/Kaggle/kagglehub) để lấy dataset. Trong Kaggle Notebook, tài nguyên được gắn vào notebook; bên ngoài, thư viện tải về cache cục bộ. Xem schema và độ mới của snapshot trước khi chọn. Với vài bài thử nghiệm, API trực tiếp có thể gọn hơn tải cả snapshot.

Nếu dùng dataset LaTeX do bên thứ ba xử lý sẵn, phải kiểm tra đủ mọi phiên bản, độ nguyên vẹn và tính phù hợp với yêu cầu tự xây crawler; không mặc định tải dataset đó là đã hoàn thành Milestone 1.

### Colab làm môi trường chạy

Colab phù hợp để học, thử pipeline, phân tích dữ liệu và **benchmark parser CPU theo đề Milestone 2**. Nó không phải nguồn dữ liệu và không phải proxy tránh giới hạn truy cập.

Theo [Colab FAQ](https://research.google.com/colaboratory/faq.html), runtime có vòng đời giới hạn và có thể bị xóa khi idle. Thiết kế cần:

- Chia công việc thành batch và lưu manifest/checkpoint ra nơi bền vững.
- Không coi `/content` là nơi lưu trữ lâu dài.
- Lưu dữ liệu cần giữ vào Drive hoặc bộ lưu trữ phù hợp, rồi xác minh đã ghi xong.
- Tách logic vào `src/`; notebook chỉ gọi pipeline và trình bày kết quả.
- Khi benchmark, ghi CPU/RAM, dữ liệu thử và tách thời gian tải mạng khỏi thời gian parse.

**Lựa chọn khởi đầu:** phát triển và crawl thử trên máy cá nhân; dùng Kaggle metadata nếu có lợi về quy mô; chạy parser và benchmark trên Colab CPU. Kaggle Notebook cũng có thể dùng để xử lý metadata, nhưng phải kiểm tra Internet/quota/lưu output của phiên hiện tại.

## 7. Có cần HTML, JavaScript và website động không?

**Cần hiểu HTML/HTTP cơ bản; chưa cần học JavaScript chuyên sâu để bắt đầu đồ án.** Đường thu thập chính là API và tải file, nên Python, JSON/XML và LaTeX phục vụ trực tiếp hơn.

- **HTML cơ bản:** biết thẻ, thuộc tính `href`, `class`, `id`, cây DOM và CSS selector. Hữu ích khi kiểm tra trang hoặc cần đọc thông tin không có trong API.
- **JSON/XML:** ưu tiên cao vì đây là định dạng response API cần xử lý.
- **JavaScript cơ bản:** hiểu browser có thể tải thêm dữ liệu sau khi nhận HTML ban đầu.
- **Website động:** biết dùng DevTools → Network để nhận diện request Fetch/XHR; chỉ sử dụng endpoint khi được phép truy cập.
- **Playwright/Selenium:** chỉ cân nhắc khi dữ liệu cần thiết thực sự phải render qua browser và không có đường API/download phù hợp. Không thêm vào pipeline mặc định.
- **Chặn crawl:** cần học status code, pacing, cache và backoff. Đây là kỹ năng vận hành crawler, không đồng nghĩa phải học cách vượt cơ chế chống bot.

Cách phân biệt nhanh: mở “View source” và so sánh với DOM trong DevTools. Nội dung không có trong HTML ban đầu có thể do JavaScript bổ sung; còn một API trả JSON/XML không cần render giao diện.

## 8. Milestone 2 — Parsing và chuẩn hóa

Theo [yêu cầu Milestone 2](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/parsing/), thực hiện theo các lớp:

1. Tìm file gốc; duyệt `\input`/`\include` đúng thứ tự, xử lý vòng lặp và file thiếu. Không ghép mọi file trong thư mục.
2. Nhận diện document, section/subsection, paragraph, itemize và các môi trường.
3. Tạo lá cho câu, công thức khối, hình/bảng. Tách câu phải tránh cắt nhầm dấu chấm trong số, tên viết tắt và lệnh LaTeX.
4. Giữ acknowledgements và appendix, kể cả section không đánh số; loại bibliography khỏi hierarchy.
5. Chuẩn hóa whitespace, lệnh trình bày và ký hiệu toán mà không phá nội dung/ngữ nghĩa.
6. Đọc BibTeX và chuyển `\bibitem`; giữ thông tin gốc để kiểm tra trường hợp trích xuất không chắc chắn.
7. Hợp nhất references trùng: chọn citation key chuẩn, hợp nhất trường, cập nhật mọi `\cite` liên quan. Xung đột trường cần quy tắc rõ ràng.
8. Deduplicate nội dung sau cleanup, tái sử dụng element ID qua phiên bản; giữ quan hệ cha–con riêng theo version.

Lưu cả `kind` và nguồn gốc phần tử để xuất dataset. Không hash rồi xóa vị trí xuất hiện một cách mù quáng: cùng nội dung có thể xuất hiện dưới nhiều parent. Trường hợp biểu diễn parent map không đủ phải kiểm thử và đối chiếu với giảng viên; định dạng trung gian được phép điều chỉnh.

Đầu ra làm việc: `hierarchy.json`, `refs.bib` và thống kê. Đánh giá độ đúng bằng ví dụ nhỏ có kết quả mong đợi; đo thời gian, RAM và dung lượng trên Colab CPU. Source văn bản gốc vẫn giữ để phục vụ xuất dữ liệu cuối.

## 9. Milestone 3 — Matching và đánh giá

### Định nghĩa và nhãn

Với một publication có `m` BibTeX entries và `n` references, xét `m × n` cặp. Mô hình dự đoán mức phù hợp của từng cặp; sắp xếp điểm để lấy tối đa năm ứng viên cho mỗi entry.

Theo [Milestone 3](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/matching/): gán nhãn tay tối thiểu 5 publications và tổng tối thiểu 20 liên kết đúng; tạo nhãn tự động cho ít nhất 10% phần non-manual còn lại. Trước khi chốt dữ liệu, xác nhận với giảng viên đơn vị tính của 10% và ghi rõ mẫu số trong báo cáo.

Lưu nguồn nhãn, bằng chứng và trạng thái chưa chắc chắn. Chỉ sinh nhãn âm khi đã xác minh hoặc có chính sách nhãn rõ ràng; không coi mọi liên kết chưa biết là âm. Với publication đã được xác minh đầy đủ, một mapping đúng cho phép suy ra các cặp không khớp tương ứng.

### Chia tập và baseline

- Test: 1 publication manual + 1 publication automatic.
- Validation: 1 publication manual + 1 publication automatic khác test.
- Train: các publications có nhãn còn lại dùng cho matching.
- Khóa danh sách ID và seed; các phiên bản cùng bài luôn cùng partition.

Bắt đầu bằng baseline chuỗi/định danh, rồi thử phân loại nhị phân bằng logistic regression. Feature đề xuất: độ giống tiêu đề, trùng tác giả, lệch năm, DOI/ID trùng và cờ thiếu dữ liệu. Phân tích đóng góp từng feature trước khi tăng độ phức tạp.

Chỉ fit vectorizer/scaler và chọn tham số trên train/validation; không dùng test để điều chỉnh. Xem [scikit-learn: common pitfalls](https://scikit-learn.org/stable/common_pitfalls.html). Không đưa nhãn đích hoặc thông tin suy ra từ ground truth vào feature.

### Đánh giá

MRR top 5: đúng hạng 1 được 1, hạng 2 được 1/2, ngoài top 5 được 0; lấy trung bình trên các query được đánh giá. Nếu có dưới năm ứng viên, các vị trí còn thiếu xuất null.

Báo cáo MRR chung theo đề, đồng thời tách kết quả manual/automatic để thấy ảnh hưởng chất lượng nhãn. Công bố cách xử lý entry không có match xác minh được; không âm thầm loại ca khó khỏi mẫu số. Kiểm tra bias khi heuristic vừa tạo nhãn vừa là baseline.

Chỉ cân nhắc mô hình pretrained/LLM sau baseline; đề nêu nhóm dùng kiến thức ngoài như vậy được đánh giá riêng.

## 10. Dataset cuối và báo cáo

**Lưu ý đối chiếu 2026-10-19:** đề Matching hiện liệt kê sáu bảng
`papers`, `references`, `elements`, `hierarchy`, `bibtex`, `predictions`.
Danh sách bảy bảng bên dưới là thiết kế cũ, không dùng làm hợp đồng triển khai.
Schema Python chưa được thay đổi hoặc đóng băng; xem [review mới](docs/crawl-review.md).

Danh sách cũ để đối chiếu:

- `papers`: metadata bài báo.
- `elements`: nội dung phần tử đã deduplicate, gồm loại phần tử.
- `element_parents`: quan hệ cha–con theo phiên bản.
- `bibtex_entries`: các trường bibliography đã chuẩn hóa.
- `paper_references`: quan hệ bài trích dẫn–bài được trích dẫn.
- `predictions`: partition, citation key, ground truth và năm ứng viên; chỉ cho bài thực sự dùng trong matching.
- `sources`: nội dung file source văn bản theo phiên bản.

Xuất Parquet phân mảnh với schema tường minh, không dùng object lồng nhau hay chuỗi JSON để né schema. Kiểm tra kiểu dữ liệu, null, khóa, liên kết giữa bảng và phạm vi ID trước khi upload. Lưu split ML trong `predictions.partition`; không nhầm với tên split của từng config trên Hugging Face.

Jupyter Book cần có độ bao phủ crawl, logic parser, số liệu trước/sau dedup, thời gian/RAM và phân tích lỗi. Poster chọn kết quả có bằng chứng, không chỉ sơ đồ công nghệ. Không điền kết quả khi chưa chạy thực nghiệm.

## 11. Tài liệu học có thứ tự

### Bắt đầu ngay

1. [Requests Quickstart](https://requests.readthedocs.io/en/latest/user/quickstart/) — học GET, params, JSON, status, timeout; áp dụng vào một request nhỏ.
2. [YouTube — Corey Schafer: Python Requests Tutorial](https://www.youtube.com/watch?v=tb8gHvYlCFs) — nhập môn request/response và đọc JSON.
3. [arXiv API User Manual](https://github.com/arXiv/arxiv-docs/blob/develop/source/help/api/user-manual.md) — truy vấn ID, phân trang và Atom XML.
4. [GitHub — arxiv.py](https://github.com/lukasschwab/arxiv.py) — ví dụ client Python; đọc cùng release notes để tránh API cũ.
5. [Semantic Scholar Graph API](https://api.semanticscholar.org/api-docs/graph) — lookup paper, fields và references.

### Khi cần Kaggle/Colab hoặc HTML

6. [Cornell arXiv Dataset trên Kaggle](https://www.kaggle.com/datasets/Cornell-University/arxiv) và [GitHub kagglehub](https://github.com/Kaggle/kagglehub) — metadata trung gian và cách truy cập dataset.
7. [Google Colab FAQ](https://research.google.com/colaboratory/faq.html) — hiểu runtime, tài nguyên và lưu trữ trước khi chạy dài.
8. [YouTube — Corey Schafer: Web Scraping with BeautifulSoup and Requests](https://www.youtube.com/watch?v=ng2o98k983k) — HTML, tìm thẻ, lấy thuộc tính; học bổ sung, không dùng để thay pipeline API.

### Khi chuyển sang parsing và ML

9. [GitHub — pylatexenc](https://github.com/phfaist/pylatexenc) — tham khảo xử lý cú pháp LaTeX; không tự giải quyết toàn bộ hierarchy của đề.
10. [GitHub — python-bibtexparser](https://github.com/sciunto-org/python-bibtexparser) — đọc/ghi BibTeX; chuyển bibitem, dedup và sửa citation vẫn cần logic riêng.
11. [scikit-learn: Common pitfalls](https://scikit-learn.org/stable/common_pitfalls.html) — preprocessing, leakage và pipeline.

Video giúp hiểu nền tảng; tài liệu chính thức quyết định endpoint, hạn mức và API hiện hành. Ghi nguồn khi sử dụng ý tưởng hoặc code tham khảo.

## 12. Trình tự bắt đầu và các thông tin còn thiếu

- [ ] Xác nhận khoảng ID từng cá nhân và hạn nộp.
- [ ] Chọn một bài mẫu có TeX; đọc bằng tay metadata, version history và bibliography.
- [ ] Làm discovery → tải source → references cho bài đó.
- [ ] Tạo manifest và chứng minh chạy tiếp được sau lỗi.
- [ ] Parse cấu trúc nhỏ, chuẩn hóa một nhóm references.
- [ ] Tạo vài nhãn đã xác minh; chạy baseline và đối chiếu MRR bằng tay.
- [ ] Mở rộng bộ mẫu đa dạng 10–20 bài, bổ sung kiểm thử ca lỗi.
- [ ] Chốt schema trước khi chạy toàn bộ khoảng ID.
- [ ] Xuất thử bảy bảng, kiểm tra khả năng tách dataset theo cá nhân.
- [ ] Build thử Jupyter Book với bảng/biểu đồ sinh tự động.

Cần bổ sung: khoảng ID, deadline, dung lượng corpus thực tế và các hướng dẫn riêng của lớp về nhãn/đánh giá/nộp dữ liệu. Các lựa chọn kỹ thuật trong README là đề xuất để bắt đầu, sẽ được cập nhật theo thực nghiệm.
