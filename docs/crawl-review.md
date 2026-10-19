# Review source crawler — 2026-10-19

Đã có source Python, nhưng chưa đủ bằng chứng để kết luận hoàn thành Crawling.
Lần này kiểm tra và lưu bản code hiện có; chưa sửa các lỗi bên dưới, chưa chạy
crawl thật, chưa upload dữ liệu và chưa thay schema chung.

## Kiểm tra đã chạy

- Cài thành công `requirements.txt` trong virtualenv riêng: Python 3.14.7,
  PyArrow 26.0.0, pytest 9.1.1, huggingface_hub 2.2.0, python-dotenv 1.2.4.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /private/tmp/arxiv-reference-review-venv/bin/python -m pytest -q`:
  **57 passed, 9 xfailed, 15 subtests passed** sau khi bổ sung kiểm tra lỗi.
  `tests/test_crawl_known_issues.py` chứa 9 ca tái hiện với `xfail(strict=True)`: đây là
  lỗi còn mở, không phải test chứng minh crawler đúng. Chạy riêng với `--runxfail`
  cho **9 failed**, xác nhận tất cả lỗi còn tái hiện. Ba test crawl ban đầu dùng dữ liệu tổng hợp:
  Atom có thẻ version, tar lọc file/đường dẫn và retry HTTP 503.
- `python -m scripts.crawl --help` chạy được. Chưa chạy CLI tải dữ liệu thật.
- Các probe offline bằng Python gọi trực tiếp hàm thực tế đã tái hiện các lỗi
  dưới đây. Probe không gọi arXiv/S2 và dùng thư mục tạm tự xóa.
- `.gitignore` chặn `.env`, `data/`, Parquet, TeX và virtualenv; không đưa dữ
  liệu hoặc cấu hình bí mật vào commit này.

Đường dẫn repo chứa dấu `:`, nên `python3 -m venv .venv` bị Python từ chối.
Dùng một đường dẫn virtualenv bên ngoài không chứa dấu này. Requirements
hiện dùng giới hạn dưới, chưa phải môi trường được khóa phiên bản.

## Lỗi đã tái hiện, chưa sửa

1. **Cao — thiếu Version (`src/crawl/discovery.py:parse_feed`).** Feed có ID
   `http://arxiv.org/abs/2508.02872v4`, không có thẻ `arxiv:version`, trả về
   `versions=1`. Pipeline vì vậy chỉ yêu cầu v1. Test hiện tại dùng các thẻ
   version tổng hợp nên không bắt lỗi này. Cần đọc hậu tố Version và xác minh
   nguồn metadata cho đủ ngày sửa đổi; không suy ra đủ lịch sử từ ngày hiện có.
2. **Cao — nhận nhầm source (`src/crawl/source.py:extract_source`).** Gọi với
   `b'%PDF-1.7\n'` hoặc `b'<html>Service unavailable</html>'` đều trả
   `(['single.tex'], [])`. Nhánh không phải tar tự đặt tên `single.tex` mà
   không kiểm tra nội dung. Cần phân biệt TeX, PDF/docx và trang báo lỗi.
3. **Cao — resume đổi trạng thái (`ArxivSourceDownloader.download`).** Mock
   HTTP 200 trả tar rỗng: lần đầu `non_tex`, lần thứ hai `success`, vì
   `source.ok` tồn tại. Cần giữ trạng thái rỗng ổn định qua lần chạy lại.
4. **Cao — checkpoint mất bản ghi (`src/crawl/manifest.py`).** Tạo file chỉ
   chứa `{"arxiv_id":`, khởi tạo Manifest rồi upsert một TaskRecord hợp lệ;
   sau khi đọc lại, `get` trả `None`. Append nối bản ghi mới vào dòng bị cắt,
   khiến cả dòng bị bỏ qua. Cần phục hồi đuôi file trước khi append.
5. **Cao — trạng thái lỗi mạng (`ArxivSourceDownloader.download`).** Mock
   HTTP 503 sau khi hết retry trả `unavailable`. Cần giữ lỗi tạm thời riêng
   để không diễn giải là source không tồn tại.
6. **Vừa — metadata sai (`parse_feed`).** ID `hep-th/9901001v4` thành
   `9901001`, mất archive prefix. Thẻ `arxiv:journal_ref` có nội dung nhưng
   `venue=None` vì tra namespace Atom. Cần giữ nguyên base ID cũ và dùng
   namespace arXiv cho journal reference.
7. **Cao — nhịp request chưa cưỡng chế (`HttpClient`, CLI).**
   `HttpClient('test', min_interval=0).min_interval` bằng `0.0`; CLI chuyển
   trực tiếp `--min-interval` vào client. Mặc định 3 giây chưa bảo đảm người
   chạy không vô tình hạ giới hạn. Lock hiện chỉ áp dụng trong một instance.

## Giới hạn thấy khi đọc code

- Pipeline chưa gọi client Semantic Scholar, chưa xuất `papers`/`references`
  Parquet, chưa đo đủ hiệu năng. Client S2 mặc định dừng ở 1.000 reference,
  chưa theo trường `next`, chưa nhận API key; không thể coi đã lấy đủ references.
- Exception khi tải source được ghi vào task `discovery` cấp Publication;
  Version lỗi không có bản ghi lỗi riêng và các Version còn lại của bài đó
  không được thử trong lượt hiện tại. `attempts` thường bị đặt lại thành 1,
  `http_status` chưa được ghi từ kết quả tải.
- Resume tin manifest/marker, chưa xác minh file và checksum; metadata
  discovery thành công được cache mà chưa có cơ chế refresh Version mới.
- Extractor giải nén mọi file thường an toàn về đường dẫn trước khi lọc
  `.tex`/`.bib`; chưa có giới hạn dung lượng giải nén. Kiểm tra tar hiện có
  không đủ để khẳng định xử lý mọi archive an toàn.
- CLI dùng `args.start or ...`, nên `--start 0` bị thay bằng mặc định thay
  vì đi qua kiểm tra Range. Chưa kiểm tra định dạng `--id` trước khi ghép URL
  và đường dẫn. Không dùng đầu vào ID không tin cậy cho phiên bản hiện tại.
- Đã bổ sung test tái hiện lỗi pipeline, manifest và downloader; các ca này
  hiện xfail, chưa có bộ test thành công đầy đủ cho từng module hoặc test
  Semantic Scholar riêng. Test HTTP ban đầu kiểm tra backoff, chưa chứng minh
  khoảng nghỉ 3 giây.

Các lỗi này thuộc phần Crawler/Semantic Scholar. Bản cập nhật lưu source
được cung cấp và kết quả review; chưa triển khai thay phần việc của chủ sở hữu.
Cần sửa, thêm test hồi quy, chạy 3–5 Publication trong Range và chạy lại để
chứng minh resume trước khi thu thập toàn Range.

## Đối chiếu đề và schema

Đã đọc cả ba trang chính thức ngày 2026-10-19 bằng tải URL trực tiếp:
[Crawling](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/),
[Parsing](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/parsing/),
[Matching](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/matching/).

Crawling yêu cầu đủ Version, giữ bản ghi cho Version không có TeX và giữ
references thô cục bộ; chỉ lọc reference có arXiv ID khi xuất bảng. Hậu tố
Version của ID từ lookup base ID được dùng để xác định số phiên bản.

Matching hiện liệt kê sáu bảng `papers`, `references`, `elements`, `hierarchy`,
`bibtex`, `predictions`. Danh sách bảy bảng trong README cũ đã được đánh dấu
lỗi thời. Tên cột ở code hiện có khớp các danh sách này, nhưng hợp đồng kiểu,
nullability và khóa chưa được đóng băng. Những khác biệt cần chốt riêng:

- Parsing quy định `bibtex.authors` là list of strings, `year` là integer
  nullable; bản schema dự thảo hiện lưu cả hai bằng string.
- Đề ghi `hierarchy.parent_id` non-null; schema hiện cho null để biểu diễn root.
- `kind`, `entry_type`, `partition` được đề ghi dạng dictionary; schema đang
  dùng string. Các ràng buộc không-null của `content`, `kind`, `version` và
  `entry_type` trong code cũng cần đối chiếu với hợp đồng nhóm.

Không sửa `src/common/schema.py` trong lần này. Việc đọc đủ trang đề không
thay thế xác nhận của người dùng hoặc tiêu chí hoàn thành giai đoạn 0/2.

## Kết nối Hugging Face

Yêu cầu bổ sung của người dùng: kiểm tra tính đúng của crawler và kết nối
dataset Hugging Face. Đã chạy `python -m scripts.check_hf`: exit code 2 vì
thiếu `HF_TOKEN`, `HF_REPO_ID` trong cấu hình hiện tại. `MEMBER_NAME` đã có.
Chưa gọi API Hugging Face, chưa tạo repo và chưa upload dữ liệu trong lượt này.

Người dùng cần điền cấu hình vào `.env` cục bộ, không gửi token trong chat:

```dotenv
HF_TOKEN=
HF_REPO_ID=
```

`HF_REPO_ID` có dạng `owner/dataset-name`. Sau khi cấu hình đủ, chạy
`python -m scripts.check_hf` bằng virtualenv đã cài requirements. Lệnh sẽ
tạo hoặc xác minh dataset private, từ chối dataset public và không thay
visibility. Kết nối thành công chưa xác nhận quyền upload từng file hoặc
chất lượng corpus. Pipeline hiện chưa gọi upload của `src.common.hf_io`.
