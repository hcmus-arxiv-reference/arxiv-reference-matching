# AGENTS.md: Kế hoạch cho agent (repo `arxiv-reference-matching`)

Tài liệu này dành cho agent lập trình (Codex) làm việc **thay mặt Nguyễn Thành Bảo**, nhóm trưởng kiêm phụ trách **Parser** của nhóm 5 người. Đọc hết file trước khi viết code. Nếu một mục chưa rõ, **hỏi người dùng** thay vì đoán.

## 1. Bối cảnh

Đồ án môn Nhập môn Khoa học Dữ liệu (HCMUS, nhóm 3 KHDL24): thu thập bài arXiv, parse mã nguồn LaTeX thành cây phân cấp, rồi ghép các BibTeX entry với reference của Semantic Scholar bằng pipeline học máy.

- Đề bài: <https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/> (có 3 trang con: `crawling/`, `parsing/`, `matching/`). **Nếu agent truy cập được web, đọc cả 3 trang con để đối chiếu schema. Nếu không, yêu cầu người dùng dán nội dung.**
- Trạng thái đã kiểm tra ngày 2026-10-16: bốn module hạ tầng của người dùng đã được đặt tại `src/common/{schema,config,hf_io,metrics}.py`, thống nhất import `src.common`. Có `.env.example`, `.gitignore`, `requirements.txt`. Đã chạy `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q`: **54 test đạt, 15 subtest** trên Python 3.14.3, PyArrow 23.0.1, pytest 9.1.1, huggingface_hub 0.36.2. Test Hugging Face dùng mock, chưa xác minh kết nối thật; chưa triển khai/kiểm thử pipeline. Chi tiết: `docs/infrastructure-review.md`, `docs/schema-review.md`. Kiểm tra lại file thực tế khi tiếp tục. Đừng tuyên bố một tính năng "đã chạy" nếu chưa chạy kiểm thử thật.

### Thông tin và quyết định đã xác nhận (2026-10-16)

- Người dùng cho phép cập nhật `AGENTS.md` để lưu thông tin cần thiết lâu dài; cập nhật quyết định đã chốt và trạng thái thật, không tự nới phạm vi hay bỏ tiêu chí hoàn thành.
- Checklist nhóm trưởng được lưu ở `docs/team-lead-checklist.md`; chỉ đánh dấu đã làm khi có bằng chứng. Người dùng đã yêu cầu commit/push code và tài liệu hiện có lên Git remote, không bao gồm `.env`, token hoặc dữ liệu.
- Range của Nguyễn Thành Bảo: tháng **2025-08**, số thứ tự **2872–7871**, tức **`2508.02872`–`2508.07871`**, bao gồm hai đầu (**5.000 ID được giao**, chưa xác minh số Publication tải được).
- Hiện người dùng chưa có file `.tex` mẫu. Agent cần chuẩn bị bộ mẫu trong range khi tới bước tải mẫu.
- Người dùng yêu cầu bắt đầu đối chiếu **Crawling trước**. Trang này đã đọc được; ghi nhận tên cột và kiểu tại `docs/crawling-requirements.md`. Chưa đối chiếu Parsing/Matching; chưa đóng băng schema toàn dự án.
- **Đã chốt:** `papers.authors`, `papers.revised_dates`, `references.ref_authors` dùng **list of strings** theo đề, tương ứng `pyarrow.list_(pyarrow.string())`. Không hỏi lại lựa chọn này.
- Hai bảng Crawling đã đối chiếu: `papers(arxiv_id, title, authors, submission_date, revised_dates, venue)` và `references(arxiv_id, ref_arxiv_id, ref_title, ref_authors, ref_submission_date, ref_s2_id)`.
- Đã thử một trang Semantic Scholar `/paper/ARXIV:1706.03762/references` với `fields=paperId,externalIds,title,authors,publicationDate`, `limit=5`: HTTP 200. Chi tiết hợp đồng/pagination ở `docs/semantic-scholar-check.md`. **Không tự ánh xạ `publicationDate` thành `ref_submission_date`**: đó là ngày xuất bản theo S2, không bảo đảm là ngày nộp arXiv; ngày nộp cần metadata arXiv xác minh hoặc giữ null. Chưa triển khai module S2.
- `CONTACT_EMAIL` đã có trong `.env` cục bộ (chỉ kiểm tra có giá trị, không ghi địa chỉ thật vào tài liệu). Đã bổ sung các tên biến thiếu từ `.env.example` mà không ghi đè cấu hình có sẵn; `MEMBER_NAME=bao` theo mẫu. Còn thiếu `HF_TOKEN`, `HF_REPO_ID` nên chưa thể chạy `ensure_repo` qua mạng. Đã có lệnh `.venv/bin/python -m scripts.check_hf`; khi đủ cấu hình, lệnh tạo hoặc xác minh dataset private, không upload dữ liệu. Không yêu cầu người dùng gửi token trong chat.
- Người dùng đã chốt cấu trúc Hugging Face: `raw/<member>/<publication key>/v<n>/` và `tables/<member>/<tên bảng>.parquet`. `upload_dir` chỉ cho ghi bên dưới `raw/<MEMBER_NAME>/...`; bảng dùng `upload_table`. Đây là kiểm tra của module, không bảo đảm cách ly các thao tác thủ công hoặc công cụ khác dùng cùng token.
- Nếu công cụ web không đọc được trang đề, thử tải URL trực tiếp bằng công cụ mạng được phép trước khi yêu cầu người dùng dán nội dung. Không vượt hạn chế truy cập.
- Có bất nhất chưa giải quyết: kế hoạch bên dưới nói **6 bảng**, README nói **7 bảng** với tên khác. Các tên bảng ngoài hai bảng Crawling chỉ là dự kiến cho tới khi đối chiếu đề Parsing/Matching và được người dùng xác nhận; không tự chọn một phía để triển khai.
- Hạ tầng có test đạt không đồng nghĩa đã đạt toàn bộ DoD giai đoạn 2: schema toàn dự án chưa đóng băng. Manifest theo Version vẫn là đề xuất chưa triển khai. `metrics.peak_rss_mb` chỉ đo đỉnh từ khi khởi động của tiến trình hiện tại, không đo RAM trung bình/tiến trình con; `dir_size_mb` là ảnh chụp dung lượng hiện tại, không phải disk đỉnh.

### Cập nhật kiểm tra ngày 2026-10-19

- Người dùng yêu cầu kiểm tra source crawl hiện có, cập nhật tài liệu và commit/push lên GitHub. Phạm vi lần này là lưu và review code được cung cấp; chưa sửa lỗi crawler hoặc thay schema.
- Đã có `src/crawl/{discovery,http_client,source,manifest,pipeline,semantic_scholar}.py`, CLI `scripts/crawl.py`, ba test crawl ban đầu và 9 ca tái hiện lỗi (`xfail(strict=True)`). Manifest không còn chỉ là đề xuất, nhưng resume chưa đạt yêu cầu.
- Đã cài requirements và chạy toàn bộ test offline: **57 test đạt, 9 xfail (lỗi còn mở), 15 subtest đạt** trên Python 3.14.7, PyArrow 26.0.0, pytest 9.1.1, huggingface_hub 2.2.0. Virtualenv đặt ngoài repo vì đường dẫn repo chứa dấu `:`. Chưa crawl thật, chưa kiểm thử kết nối Hugging Face thật trong lần này.
- Review tái hiện lỗi đếm Version từ Atom, mất prefix ID cũ, venue sai namespace, PDF/HTML thành TeX, `non_tex` đổi thành `success` khi resume, mất bản ghi sau dòng checkpoint bị cắt và HTTP 503 bị ghi `unavailable`. Chi tiết và giới hạn ở `docs/crawl-review.md`; không coi test xanh là crawler hoàn tất.
- Đã đọc được cả ba trang đề qua tải URL trực tiếp. Trang Matching hiện chỉ rõ **6 bảng**, nên danh sách 7 bảng trong README cũ không còn là nguồn triển khai. Các khác biệt kiểu/nullability trong schema vẫn cần người dùng xác nhận; chưa thay đổi `src/common/schema.py`, chưa đóng băng schema hay chuyển giai đoạn.

- Người dùng bổ sung yêu cầu kiểm tra tính đúng của crawler và kết nối dataset Hugging Face. Sau khi người dùng điền `.env`, `scripts.check_hf` đã gọi API thật thành công (exit code 0) ngày 2026-10-19: dataset đã được tạo hoặc xác minh là private. Chưa upload dữ liệu, chưa kiểm thử upload/download thật. Không ghi token hoặc giá trị cấu hình riêng vào tài liệu.

### Cập nhật sau bản sửa crawler và pipeline upload (2026-10-19)

- Người dùng yêu cầu rõ: **fix lỗi crawl và tạo pipeline Python API đẩy dữ liệu crawl lên Hugging Face**. Phạm vi sửa crawler/tích hợp S2/upload trong yêu cầu này đã được cho phép; không tự mở rộng sang Parser/Matching hoặc thay schema.
- Chín ca lỗi đã tái hiện nay đã sửa, bỏ marker xfail. Bộ test hiện đạt **100 test, 15 subtest**, không có xfail. Có test HTTP bị cắt, checksum/resume, per-Version errors, S2 pagination, merge Parquet và upload atomic với `parent_commit`.
- API `src.crawl.api.run_crawl`, CLI `scripts.crawl`: `--upload`, `--upload-only`, `--skip-references`, `--refresh`, `--batch-size`. Chỉ upload Publication đầy đủ theo chế độ đã chọn; giữ dữ liệu khác trên Hub. Không sửa schema chung.
- Đã chạy thật ba Publication: `2508.02872` đủ v1/v2 TeX, `2508.02874` v1 `non_tex`, `2508.02873` đủ v1/v2 nhưng v3 còn `IncompleteRead`. S2 thành công cả ba; chỉ hai Publication đầy đủ được upload lên dataset private. Cache thử ở `data/crawl-smoke/`, không commit dữ liệu/bí mật.
- Đọc lại Hugging Face đã validate 2 dòng `papers`, 35 dòng `references`, so checksum 12 file raw/metadata. Chạy lại hai Publication: 3 Version skipped, không lỗi, upload `unchanged`, không tạo commit mới. Đây là kiểm chứng mạng thật, không chỉ mock.
- Xem `docs/crawl-pipeline.md` để biết kiểm chứng upload/resume và giới hạn. Review ban đầu được giữ như lịch sử, không dùng số xfail/lỗi cũ để mô tả code hiện tại. Chưa chạy toàn Range, chưa hoàn thành benchmark hay đóng băng schema toàn dự án.

### Cập nhật vận hành Range ngày 2026-10-23

- Người dùng yêu cầu ưu tiên crawl về local toàn Range 5.000 ID trước và tiếp
  tục công việc. Đã khởi chạy `scripts.crawl_range` ngày 22/10/2026 trong
  `data/crawl-smoke/` để dùng lại cache đã xác minh; không upload lượt này.
- Trình chạy có tiến độ `manifests/range-run.json`, checkpoint từng tác vụ,
  tối đa ba lượt retry phần thiếu, nghỉ 30 phút giữa lượt; xuất bảng tổng hợp
  toàn Range ở cuối lượt/dừng có kiểm soát. Không đổi schema chung.
- Test sau bổ sung: **104 test và 15 subtest đạt**. Snapshot 17:12 ngày 23/10:
  222 Publication đủ dữ liệu, 361 Version đã xác minh, đang chạy lượt đầu.
  Không dùng snapshot này làm số liệu hiện tại; đọc manifest và kiểm tra PID.
- Cache `2508.02873` đã có v3 hợp lệ; thông tin thiếu v3 ngày 19/10 ở phần
  lịch sử không còn phản ánh cache hiện tại. Range vẫn chưa hoàn tất.
- Không khởi chạy crawler thứ hai khi worker còn sống. Hướng dẫn vận hành,
  retry/dừng và các giới hạn: `docs/full-range-crawl.md`.
- Người dùng yêu cầu thông báo khi xong: đã bật `scripts.watch_crawl` theo dõi
  mỗi 30 giây và thông báo macOS tại máy này, phân biệt đủ dữ liệu với còn
  thiếu/lỗi. macOS đã chấp nhận thông báo thử. Bộ test hiện đạt **106 test và
  15 subtest**. Sau reboot cần khởi động lại worker/watcher từ checkpoint.

### Cập nhật tích hợp crawler Liễu ngày 2026-10-24

- Người dùng yêu cầu merge `feat/Lieu-crawler` vào `main` và tiếp tục crawl
  từ source đó. Đã merge commit nguồn `0d19257`, giữ lịch sử đóng góp và
  giữ các file hạ tầng/test/tài liệu của main mà nhánh nguồn xóa.
- Entry point mới: `python -m src.milestone1_crawler --data-dir data/crawl-smoke`.
  Bản tích hợp giữ discovery theo lô và S2 song song với source của Liễu,
  dùng lại client HTTP, schema, checksum/receipt và S2 pagination của main.
  Không thay schema Parquet hoặc đổi đường dẫn cache. `range-run.json` có
  `engine: "lieu"`; không chạy thêm crawler khác khi worker này còn hoạt động.
- Worker cũ dừng có kiểm soát ở 788 Publication đủ dữ liệu; lưu snapshot
  manifest/1.318 receipt trước chuyển. Resume bốn Publication mẫu không tải
  lại; smoke mạng thật `2508.03870` và `2508.03871` đều hoàn chỉnh.
- **115 test và 15 subtest đạt**. Môi trường chạy mới là
  `/private/tmp/arxiv-lieu-venv`; môi trường review cũ mất `pyvenv.cfg`.
- Chi tiết phạm vi tích hợp và giới hạn công cụ thống kê gốc của Liễu:
  `docs/lieu-integration.md`. Chưa hoàn thành toàn Range hoặc upload lượt này.

## 2. Thuật ngữ (bắt buộc dùng đúng)

| Thuật ngữ | Nghĩa |
|---|---|
| **Publication** | Một bài arXiv, định danh bằng ID gốc (ví dụ `2310.12345`; ID cũ giữ nguyên dạng `hep-th/9901001`) |
| **Version** | Một phiên bản của Publication (`v1`, `v2`, ...) |
| **Reference** | Bản ghi Semantic Scholar của một bài được trích dẫn, có arXiv ID (một dòng bảng `references`) |
| **BibTeX entry** | Mục trích dẫn parse từ `\bibitem`, sau khử trùng lặp (một dòng bảng `bibtex`) |
| **Element** | Một nút của cây phân cấp (document, heading, sentence, block formula, figure, ...) |
| **Range** | Dải arXiv ID giao riêng cho một thành viên |

## 3. Phạm vi của agent

**Agent làm:** khung repo, schema chung, tiện ích Hugging Face, công cụ tải bộ mẫu để phát triển, **Parser** (bảng `elements`, `hierarchy`), công cụ kiểm tra chất lượng (QA), notebook thống kê cho báo cáo.

**Agent không làm thay (chỉ tạo stub hoặc mock khi cần để chạy thử):**
- Crawler hoàn chỉnh (thuộc thành viên Crawler).
- Lấy references từ Semantic Scholar (thành viên Semantic Scholar và metadata).
- Chuẩn hóa LaTeX và `\bibitem` sang BibTeX (thành viên Chuẩn hóa và BibTeX).
- Mô hình Matching (thành viên Matching).

## 4. Quy tắc bắt buộc

1. **Không commit dữ liệu.** `data/`, `*.parquet`, `*.tar.gz`, file `.tex` thô đều nằm trong `.gitignore`.
2. **Không commit bí mật.** Token Hugging Face và API key Semantic Scholar chỉ đọc từ biến môi trường hoặc `.env` (đã `.gitignore`). Chỉ commit `.env.example` không có giá trị thật.
3. **Tải từ arXiv phải lịch sự:** dùng `export.arxiv.org` (không dùng `arxiv.org`, sẽ bị 403), cách nhau **tối thiểu 3 giây** giữa các request, **một kết nối một lúc**, User-Agent mô tả rõ (có email liên hệ).
4. **Schema tường minh:** không object lồng nhau hoặc JSON blob trong cột Parquet. Ngoại lệ đã được người dùng chốt theo đề: `authors`, `revised_dates`, `ref_authors` ở các bảng Crawling dùng list of strings như mục 1; không chuyển các cột này thành chuỗi. Mọi thay đổi schema khác phải **hỏi người dùng trước**, vì cả nhóm phụ thuộc vào nó.
5. **Phiên bản không có TeX** (chỉ PDF, docx) vẫn phải có bản ghi rỗng, không được bỏ qua.
6. **Parser phải tái lập được:** sửa bằng code, không sửa tay từng dòng. Ngoại lệ phải ghi vào một file log.
7. **Commit nhỏ và thường xuyên**, thông điệp rõ ràng (ví dụ `feat(parse): resolve \input recursively`). Lịch sử commit là một phần điểm.
8. Mỗi module phải có **test** chạy được. Chỉ báo "đạt" sau khi đã chạy test thật.
9. Code có docstring và chú thích đủ rõ. Tài liệu online dùng để tham khảo phải ghi nguồn.
10. Không dùng LLM hay mô hình pretrained trong Parser. Phần Matching có quy tắc riêng, không thuộc phạm vi của agent.

## 5. Kế hoạch theo giai đoạn

Làm tuần tự từng giai đoạn. Mỗi giai đoạn có **tiêu chí hoàn thành** (DoD). Chưa đạt DoD thì không sang giai đoạn sau.

### Giai đoạn 0: Định hướng
- Đọc `README.md` và 3 trang đề. Ghi lại tên cột chính xác của 6 bảng.
- Range và tình trạng mẫu đã được người dùng cung cấp ở mục 1; không hỏi lại. Hoàn tất đối chiếu ba trang theo thứ tự bắt đầu từ Crawling mà người dùng yêu cầu.
- **DoD:** có một danh sách cột đã đối chiếu với đề, người dùng xác nhận.

### Giai đoạn 1: Khung repo
Tạo cấu trúc sau (thư mục theo chức năng, không chia theo milestone):

```
.
├── README.md             # cập nhật trạng thái thật, không hứa suông
├── AGENTS.md             # file này
├── CONTEXT.md            # glossary
├── requirements.txt
├── .gitignore            # .env, data/, *.parquet, __pycache__, ...
├── .env.example          # HF_TOKEN=  S2_API_KEY=  CONTACT_EMAIL=
├── pyproject.toml hoặc setup.cfg (tuỳ chọn, để import src gọn)
├── src/
│   ├── common/           # schema.py, config.py, hf_io.py, metrics.py
│   ├── crawl/            # stub; thành viên khác sở hữu
│   ├── metadata/         # stub
│   ├── parse/            # sở hữu của người dùng
│   ├── bibtex/           # stub
│   └── matching/         # stub
├── scripts/              # fetch_sample.py, run_parse.py, validate_tables.py
├── tests/
│   └── fixtures/         # vài file .tex nhỏ tự viết, KHÔNG phải dữ liệu tải về
└── notebooks/            # thống kê cho Jupyter Book (sinh hình bằng code)
```

**DoD:** `pip install -r requirements.txt` chạy được, `pytest` chạy được (dù chưa có test thật), `.gitignore` chặn được dữ liệu và bí mật.

### Giai đoạn 2: Schema chung và hạ tầng
- `src/common/schema.py`: định nghĩa 6 bảng (`papers`, `references`, `elements`, `hierarchy`, `bibtex`, `predictions`) bằng `pyarrow` (tên cột, kiểu). Bao gồm hàm `validate(table, name)`.
- Ghi vào docstring quyết định đã chốt: `papers.authors`, `papers.revised_dates`, `references.ref_authors` là list of strings; đường dẫn thô trên Hugging Face dùng `raw/<member>/<publication key>/v<n>/` và bảng dùng `tables/<member>/<tên bảng>.parquet`. Các quy ước còn cần chốt với người dùng: `arxiv_id` không kèm `v`, `element_id` dạng `<publication key>#<discriminant>`, đường dẫn lưu cục bộ ở giai đoạn 3.
- `src/common/config.py`: đọc `.env` và biến môi trường.
- `src/common/hf_io.py`: hai hàm tải và đẩy một Publication (hoặc một bảng Parquet) lên Hugging Face dataset **private**. Dùng `huggingface_hub`.
- `src/common/metrics.py`: bộ đo thời gian và RAM tối đa dùng chung, vì đề chấm hiệu năng.
- **DoD:** có test cho `validate` (bảng đúng thì qua, thiếu cột hoặc sai kiểu thì báo lỗi rõ). Người dùng xác nhận và **đóng băng schema**.

### Giai đoạn 3: Bộ dữ liệu mẫu để phát triển
- `scripts/fetch_sample.py`: nhận một danh sách arXiv ID, tải **mọi Version** từ `export.arxiv.org/src/{id}v{n}`, tuân thủ quy tắc ở mục 4.
- Xử lý cả `.tar.gz` lẫn một file `.gz` chứa đúng một `.tex`. Chỉ giữ `.tex` và `.bib`, bỏ ảnh (giữ lệnh `\includegraphics`/`figure` trong TeX). Version không có TeX thì ghi bản ghi rỗng.
- Có **checkpoint và resume** (bỏ qua những gì đã tải).
- Lưu vào `data/raw/<id>/v<n>/` (không commit).
- **DoD:** chạy được trên 3 đến 5 Publication mẫu của người dùng, chạy lại lần hai thì không tải lại.

### Giai đoạn 4: Parser (lõi của người dùng), làm từng lớp

Mỗi lớp: viết code, viết test với fixture nhỏ, chạy trên bộ mẫu, rồi mới sang lớp sau. Gợi ý dùng `pylatexenc` hoặc `TexSoup` cho cấu trúc, regex chỉ để bổ sung.

1. **Tìm file gốc và gom file:** chọn file `.tex` có `\documentclass`, đi theo `\input`/`\include` đệ quy. Lệnh nằm trong dòng comment coi như text thường. Chỉ gom file nằm trên đường biên dịch.
2. **Khung mục:** nhận diện `\section`, `\subsection`, `\paragraph` (kể cả bản có `*`). **Phải gồm** Acknowledgements và Appendices, **bỏ** phần References.
3. **Lá của cây:** Sentence (không tách ở toán, lệnh, `i.e.`, `et al.`, `Fig. 1`, URL, số thập phân), Block formula, Figure (Table tính là Figure). Mỗi `\item` là nút con của nút `itemize`.
4. **Chuẩn hóa:** bỏ lệnh định dạng vô nghĩa (`\centering`, `[htpb]`, `\midrule`, ...), thống nhất toán inline về `$...$` và toán khối về `\begin{equation}...\end{equation}`.
5. **Khử trùng lặp giữa các Version:** phần tử giống hệt sau khi làm sạch thì dùng chung một `element_id`. **So khớp làm sau chuẩn hóa.**
6. Xuất `elements` và `hierarchy` ra Parquet đúng schema. Một dòng `hierarchy` là một cạnh nút-cha của **một Version**.

- **DoD:** parse thành công bộ mẫu, `validate` qua cho cả hai bảng, mọi `parent_id` trong `hierarchy` trỏ tới `element_id` có thật, test của từng lớp xanh.

### Giai đoạn 5: Chạy hàng loạt và đo lường
- `scripts/run_parse.py`: nhận Range hoặc danh sách Publication, chạy parser, có **checkpoint và resume**, ghi log lỗi từng Version (không dừng cả lượt vì một bài hỏng).
- Ghi sẵn các số liệu cho báo cáo: tỉ lệ Version parse thành công, độ phủ Version, số phần tử trước và sau khử trùng lặp, thời gian end-to-end, trung bình mỗi bài, RAM tối đa, dung lượng đầu ra.
- **DoD:** chạy được trên toàn Range của người dùng, có file thống kê.

### Giai đoạn 6: Công cụ QA cho nhóm trưởng
`scripts/validate_tables.py` đọc các bảng (cục bộ hoặc từ Hugging Face) và báo cáo:
1. Tên cột và kiểu dữ liệu đúng schema ở cả 6 bảng.
2. Không có `element_id` trùng giữa các Range.
3. Mọi dòng `hierarchy` trỏ tới `element_id` có thật.
4. Không có BibTeX entry rỗng tiêu đề.
5. Tỉ lệ Version parse thành công và độ phủ Version của từng thành viên.
6. Lấy mẫu ngẫu nhiên vài entry mỗi thành viên để người dùng soi bằng mắt.
7. Kiểm tra mọi bản ghi chỉnh sửa tay đều có trong file log.

- **DoD:** chạy được trên dữ liệu mẫu, xuất báo cáo dễ đọc (Markdown hoặc bảng).

### Giai đoạn 7: Tích hợp với phần của người khác
- Chỉ khi các thành viên khác đã đẩy bảng của họ lên Hugging Face private: tải về, chạy QA, tổng hợp lỗi cho người dùng. **Không tự sửa dữ liệu của người khác.** Báo lỗi cụ thể (bảng nào, dòng nào, lỗi gì) để chủ sở hữu sửa.
- Hỗ trợ kiểm tra script gộp 6 bảng của thành viên phụ trách (chỉ đọc và đề xuất, không ghi đè).
- **DoD:** có báo cáo QA tổng hợp; mọi lỗi đã giao đúng người.

### Giai đoạn 8: Phục vụ báo cáo và đóng gói
- `notebooks/`: notebook thống kê cho phần Parser của Jupyter Book. **Hình và bảng phải sinh bằng code khi compile**, không dán ảnh chụp màn hình.
- Cập nhật `README.md`: trạng thái thật, cách chạy từng bước, schema, ví dụ lệnh.
- Chốt `requirements.txt` (ghim phiên bản).
- Dọn dẹp: không còn dữ liệu hay bí mật trong lịch sử commit.
- **DoD:** người ngoài clone repo, làm theo README, chạy được pipeline Parser trên bộ mẫu.

## 6. Khi nào phải dừng lại và hỏi người dùng

- Muốn đổi schema hay quy ước đặt tên.
- Một quyết định về Parser ảnh hưởng đến bảng của thành viên khác (ví dụ định dạng `element_id`).
- Không truy cập được trang đề hoặc dữ liệu.
- Phát hiện dữ liệu của người khác bị lỗi.
- Có thao tác không thể hoàn tác (xóa dữ liệu trên Hugging Face, đổi lịch sử git).
