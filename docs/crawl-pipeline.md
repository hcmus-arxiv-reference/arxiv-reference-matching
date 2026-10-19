# Crawler Python và upload Hugging Face

## Phạm vi và đường dẫn

API Python: `src.crawl.api.run_crawl`. CLI: `python -m scripts.crawl`.
Các bước: discovery → source theo Version → references S2 → validate → Parquet
→ upload vào dataset private. Schema `src/common/schema.py` giữ nguyên.

Cấu hình `.env`: `CONTACT_EMAIL`, `HF_TOKEN`, `HF_REPO_ID`, `MEMBER_NAME`,
`DATA_DIR`, `ARXIV_RANGE_*`; `S2_API_KEY` tùy chọn. Không ghi token vào code.
Kết nối dataset trước bằng `python -m scripts.check_hf`. Pipeline upload
không tự đổi visibility hoặc xóa file trên Hub.

Cục bộ (bên dưới `DATA_DIR`, mặc định `data/`, không commit Git):

- `metadata/<publication-key>.json`: metadata và số Version đã xác minh.
- `references/<publication-key>.json`: toàn bộ bản ghi S2 thô, kể cả không có arXiv ID.
- `raw/<publication-key>/v<n>/`: `.tex`, `.bib` và `source.json` chứa trạng thái,
  checksum archive và checksum từng file. Version PDF/docx giữ receipt `non_tex`.
- `manifests/crawl.jsonl`: trạng thái, số lần thử và loại lỗi theo task/Version.
- `manifests/last-run.json`, `last-upload.json`: kết quả lượt chạy/upload gần nhất.
- `tables/papers.parquet`, `references.parquet`: bảng của **batch gần nhất**
  đã xuất, không phải bản tổng hợp toàn bộ cache cục bộ.

Trên Hugging Face:

```text
raw/<member>/<publication-key>/v<n>/
    <các file .tex/.bib giữ đường dẫn tương đối>
    source.json
    metadata.json
    references.json  # khi lấy references
tables/<member>/papers.parquet
tables/<member>/references.parquet
```

Các file JSON là receipt/metadata thô phục vụ vận hành, không phải JSON blob
trong cột Parquet. References S2 là snapshot ở cấp Publication, được lưu cùng
mỗi Version; không tuyên bố S2 phân biệt được references của từng Version.

## Chạy CLI

Từ root repo, dùng Python trong virtualenv đã cài `requirements.txt`.
Nếu đường dẫn repo chứa `:`, đặt virtualenv ở đường dẫn khác không chứa `:`.
Ví dụ máy hiện tại dùng `/private/tmp/arxiv-reference-review-venv/bin/python`;
đường dẫn tạm có thể bị hệ điều hành dọn, nên tạo lại môi trường khi cần.

```sh
# Crawl một Publication, xuất batch Parquet cục bộ; chưa upload.
python -m scripts.crawl --id 2508.02872

# Crawl, validate và upload theo batch (mặc định 5 Publication).
python -m scripts.crawl --start 2872 --end 2874 --batch-size 3 --upload

# Chỉ upload lại cache đã xác minh, không gọi arXiv/S2.
python -m scripts.crawl --start 2872 --end 2874 --upload-only

# Chỉ source và metadata; không cập nhật bảng references trên Hub.
python -m scripts.crawl --id 2508.02872 --skip-references --upload

# Xác minh lại danh sách Version/ngày sửa đổi và refresh references.
python -m scripts.crawl --id 2508.02872 --refresh

# Toàn Range cấu hình; chỉ chạy sau khi đã kiểm tra mẫu.
python -m scripts.crawl --upload
```

Chạy lại cùng lệnh để resume. Exit code 0: tất cả mục yêu cầu sẵn sàng và
không có lỗi upload; 1: có lỗi/Publication chưa đủ dữ liệu; 2: đầu vào hoặc
cấu hình không hợp lệ. Xem `last-run.json` và `crawl.jsonl` để biết bước lỗi.
Lỗi upload không mất cache; chạy lại `--upload-only` sau khi xử lý nguyên nhân.
Nếu repo đổi trong lúc chuẩn bị commit, pipeline từ chối ghi và cần chạy lại
để đọc snapshot mới. Lỗi được lưu bằng loại exception/HTTP status, không ghi
response body hoặc header có thể chứa token.

## Gọi bằng Python

```python
from src.common.config import get_settings
from src.crawl.api import run_crawl

result = run_crawl(
    ["2508.02872", "2508.02873"],
    settings=get_settings(),
    upload=True,
    references=True,
    batch_size=2,
)
print(result)
```

Không truyền `ids` thì dùng Range cấu hình. `upload=False` mặc định;
`upload_only=True` yêu cầu `upload=True`. `refresh=True` cập nhật discovery/S2,
source đã xác minh vẫn được dùng lại. Đây là API thư viện Python, không mở
HTTP server hoặc endpoint nhận token.

## Các kiểm tra được thực hiện

- Base ID được validate trước khi dùng làm URL/đường dẫn, giữ ID cũ có archive prefix.
- Đếm Version từ hậu tố ID, lấy `updated` của từng bản sửa đổi; không suy ra
  số Version từ số ngày đã có. Thiếu ngày cần thiết thì discovery báo lỗi.
- arXiv dùng `export.arxiv.org`, khoảng nghỉ ít nhất 3 giây, một request tại
  một thời điểm trong tiến trình. Không tự đi theo redirect arXiv; CLI từ chối
  khoảng nghỉ thấp hơn 3 giây. Chạy **một crawler process** cho một tác vụ;
  không chạy song song trên nhiều máy để tăng hạn mức.
- HTTP kiểm tra số byte thực nhận với `Content-Length`, đọc theo từng phần,
  giới hạn response 128 MiB và retry timeout/response bị cắt/429/5xx có giới hạn.
  `Retry-After` hơn 60 giây trả lỗi để chạy lại sau, không bỏ qua chỉ dẫn máy chủ.
- Giải nén giới hạn 256 MiB và 10.000 thành viên; chỉ ghi `.tex`/`.bib`, bỏ
  symlink/hardlink/path traversal, từ chối đường dẫn trùng hoặc source không rõ loại.
  HTML/JSON lỗi không được ghi thành TeX. Không sửa bytes của source.
- Resume kiểm tra receipt, danh sách file và checksum. Marker cũ `source.ok`
  không đủ làm bằng chứng thành công. Discovery/S2 cache cũng có checksum.
- Task discovery, từng Version và references được ghi riêng; lỗi một Version
  không ngăn thử các Version còn lại. 404/410 là `unavailable`; lỗi mạng là
  `error`. Publication có Version thiếu hoặc lỗi chưa được upload.
- S2 theo `next` đến hết, không cắt ở 1.000 reference; cache toàn bộ response.
  Chỉ xuất ứng viên có arXiv ID và khử trùng lặp theo cặp ID. Không ánh xạ
  `publicationDate` sang `ref_submission_date`; trường ngày nộp chưa xác minh
  giữ null. Chưa triển khai enrichment ngày nộp của references.
- Upload chỉ lấy danh sách file đã xác minh. Dataset phải private; chỉ ghi
  trong `raw/<MEMBER_NAME>/...` và `tables/<MEMBER_NAME>/...`.
- Bảng trên Hub được đọc ở commit cố định, validate rồi merge: chỉ thay các
  dòng của Publication hoàn chỉnh trong batch, giữ các Publication khác.
  Chế độ bỏ references giữ nguyên bảng references trên Hub.
- Một commit gồm cả source, metadata và bảng; `parent_commit` ngăn ghi đè
  cập nhật đồng thời. Version nguồn đã có mà khác receipt sẽ bị từ chối,
  không tự xóa dữ liệu để hòa giải. Rerun không thay dữ liệu thì không tạo commit.

## Kiểm thử và giới hạn

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q
```

Các test offline bao gồm lỗi đã tìm thấy, đọc thiếu byte HTTP, hỏng cache,
phân trang S2, source rỗng, tiếp tục sau lỗi Version, merge Parquet, upload
thất bại rồi retry, repo public, xung đột source và cập nhật đồng thời.
Test Hub dùng fake API nhưng đọc/ghi Parquet thật. Kết quả chạy mạng thật
được ghi riêng bên dưới; test mock không chứng minh vận hành toàn Range.

Khóa file ngăn hai writer dùng cùng thư mục dữ liệu; không phải khóa phân tán.
Mỗi lần upload đọc/ghi lại bảng của thành viên, nên batch nhỏ có chi phí
mạng; chưa benchmark toàn Range. Chưa bổ sung đầy đủ phép đo hiệu năng theo
Milestone 1, chưa đóng băng schema Parser/Matching hay hoàn tất báo cáo.

Nguồn: [arXiv API](https://info.arxiv.org/help/api/user-manual.html),
[Semantic Scholar OpenAPI](https://api.semanticscholar.org/graph/v1/swagger.json),
[Hugging Face commit API](https://huggingface.co/docs/huggingface_hub/en/package_reference/hf_api#create_commit).

## Kết quả kiểm chứng ngày 2026-10-19

- **100 test và 15 subtest đạt, không có xfail**, trên Python 3.14.7,
  PyArrow 26.0.0, pytest 9.1.1, huggingface_hub 2.2.0.
- Đã chạy mạng thật trên `2508.02872`, `2508.02873`, `2508.02874`, cache
  ở `data/crawl-smoke/`. S2 thành công cả ba. `2508.02872` đủ hai Version
  TeX; `2508.02874` có một Version không TeX và được giữ bằng receipt rỗng.
- `2508.02873` tải được v1/v2 nhưng v3 trả response thiếu byte sau retry,
  được ghi `IncompleteRead`. Publication này chưa được upload; không coi
  số ngày/bản ghi metadata là bằng chứng đã tải đủ source.
- Đã upload hai Publication hoàn chỉnh lên dataset private cấu hình trong
  `.env`. Đọc lại và validate được **2 dòng papers, 35 dòng references**;
  so checksum thành công **12 file raw/metadata**.
- Chạy lại hai Publication đã upload: **3 Version skipped**, không lỗi;
  publisher trả `unchanged`, không tạo commit mới. Đã kiểm chứng cả upload,
  download đọc lại và resume thật cho hai Publication này.

Lệnh retry bài còn thiếu, dùng lại đúng cache thử nghiệm:

```sh
DATA_DIR=data/crawl-smoke python -m scripts.crawl --id 2508.02873 --upload
```

Không tự sửa file đã tải hoặc đánh dấu Version lỗi thành công. Chưa đạt
mốc 3–5 Publication hoàn chỉnh, chưa chạy toàn Range/benchmark Colab.
