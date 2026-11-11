# Bộ mẫu phát triển M2 — mốc 12/11

Task của Minh trong issue [#33](https://github.com/hcmus-arxiv-reference/arxiv-reference-matching/issues/33):
plan 100 Publication lấy ngẫu nhiên có seed từ Range Bảo, kèm lệnh tải từ Hugging Face.
Script: `scripts/m2_sample.py`. Đây là công cụ chuẩn bị đầu vào, chưa chạy pipeline Parser M2.

## Trạng thái và bộ mock

**Task 12/11 chưa hoàn chỉnh.** Hiện chỉ có bộ mẫu mock và kiểm thử offline;
chưa tạo plan từ corpus Bảo thật hoặc xác minh tải 100 Publication từ HF.

Theo yêu cầu của người dùng, bước này dùng **dữ liệu mock** vì máy chưa có corpus Bảo và
cấu hình HF. Plan được lưu ở `configs/m2-sample-100.mock.json`, có `data_origin = "mock"`.
Các ID thuộc Range thật nhưng nội dung, metadata và receipt đều tự sinh; không phải dữ liệu
đã crawl hay số liệu chất lượng Parser. Không dùng các hash trong plan mock để tải HF.

Dùng môi trường Python có sẵn của dự án; nếu không có thì dùng `DL_Env`.
Các lệnh dưới đây viết `python` với ý nghĩa Python của môi trường đã chọn. Không cần tạo
môi trường mới. Máy hiện tại dùng `/home/nhminh/miniconda3/envs/DL_Env/bin/python`.

Tạo lại mock vào một thư mục **chưa tồn tại hoặc rỗng** để giữ nguyên dữ liệu cũ:

```sh
python -m scripts.m2_sample mock \
  --data-dir data/m2-sample-mock \
  --output configs/m2-sample-100.mock.json
python -m scripts.m2_sample verify \
  --plan configs/m2-sample-100.mock.json \
  --data-dir data/m2-sample-mock
```

Seed mặc định là `20261112`. Bộ mock mặc định có 100 Publication, 199 Version, trong đó
20 Version `non_tex`. Đây là số lượng fixture tự sinh. Cùng seed cho cùng plan từng byte
khi tạo lại vào một thư mục mới. `download` từ chối plan mock trước khi gọi HF.

## Tạo plan từ corpus thật sau này

Corpus nguồn cần layout M1 chuẩn: `metadata/<key>.json`, `raw/<key>/v<n>/source.json` và
source `.tex/.bib` được receipt liệt kê. Ví dụ khi corpus đã có tại `data/crawl-smoke`:

```sh
python -m scripts.m2_sample make-plan \
  --corpus data/crawl-smoke \
  --output configs/m2-sample-100.json \
  --hf-member bao --size 100 --seed 20261112
```

`--hf-member` là **tên thư mục chứa dữ liệu Bảo trên HF**, có thể khác `MEMBER_NAME` của
người tải. Thay `bao` nếu tên thư mục đã upload khác. Không đổi Range nguồn: luôn là
`2508.02872`–`2508.07871`, gồm hai đầu, đọc từ `configs/ranges.toml`.

Quy tắc chọn:

1. Duyệt Range theo thứ tự ID, chỉ giữ Publication có metadata hợp lệ và đủ mọi Version
   từ `v1` tới số Version theo metadata. Dùng `verified_source()` để kiểm inventory và
   checksum; không đọc Manifest.
2. Giữ Version `non_tex`; không lọc theo trạng thái parser `ready`, số heading hay độ dễ
   của source. Không yêu cầu references S2 vì đó không phải đầu vào Parser M2.
3. Lấy ngẫu nhiên đều, không hoàn lại, bằng `random.Random(seed).sample()`; sắp xếp kết quả
   theo ID. Thiếu 100 Publication đủ điều kiện thì báo lỗi, không tự giảm cỡ mẫu.
4. Ghi seed, số lượng và SHA-256 danh sách ID đủ điều kiện, số Publication bị loại theo
   nguyên nhân, đường dẫn từng Version trên HF, hash metadata và receipt. Plan không
   chứa nội dung source, thời gian chạy, đường dẫn máy cá nhân hay token.

100 Publication có thể có hơn 100 Version. Bộ 30 bài gán nhãn tay là đầu việc riêng;
script này không tạo nhãn hoặc cam kết bộ 100 chứa toàn bộ 30 bài đó.

Plan thật có `data_origin = "corpus"`. Phải tạo từ corpus thật; không sửa cờ của plan mock
để biến nó thành plan thật. Tạo lại plan với cùng corpus/seed cho cùng byte; nếu tập đủ
điều kiện hoặc input thay đổi, kiểm tra lại thay đổi plan trước khi chia sẻ cho nhóm.

## Tải bộ mẫu thật từ HF

Người tải cần quyền đọc dataset private của nhóm. Đặt `HF_TOKEN`, `HF_REPO_ID`, `MEMBER_NAME`
trong `.env` hoặc biến môi trường. Không gửi token trong chat, đưa token vào lệnh hay commit
`.env`. Lệnh chỉ đọc HF; không tạo repo, upload hay thay đổi dữ liệu trên HF.

```sh
python -m scripts.m2_sample download \
  --plan configs/m2-sample-100.json \
  --data-dir data/m2-sample
```

Có thể thêm `--revision <commit-hoặc-tag-HF>`. Script phân giải thành một commit SHA duy
nhất cho lượt tải và truyền vào helper `download_dir()` của dự án. Không truyền revision
thì phân giải HEAD một lần. Mỗi Publication được tải vào thư mục tạm, kiểm metadata và
receipt với plan, kiểm lại source bằng `verified_source()`, rồi mới chuyển vào bộ mẫu.
Đường dẫn HF thiếu hoặc checksum khác plan là lỗi; không thay Publication bằng bài khác.

Kết quả có layout local M1:

```text
data/m2-sample/
  metadata/<key>.json
  raw/<key>/v1/source.json
  raw/<key>/v1/metadata.json
  raw/<key>/v1/<source .tex/.bib>
  raw/<key>/v2/...
  sample-report.json
```

`metadata/<key>.json` được chép nguyên byte từ metadata của v1; metadata lặp ở mọi Version
đều phải khớp plan. Có thể đọc bằng `FileCorpus("data/m2-sample")` hoặc truyền từng thư mục
Version vào `assemble_source`. Bộ mẫu này phục vụ source M2, chưa phải corpus đầy đủ cho M3.

Chạy lại cùng lệnh để tiếp tục: Publication đã có được xác minh rồi dùng lại. Nếu tất cả
đã đủ thì không gọi mạng, không cần cấu hình HF. Source hiện có sai hoặc metadata khác
plan thì dừng; dùng một thư mục đích mới để tải lại, không ghi đè raw cũ. Không chạy hai
lượt tải cùng lúc vào cùng thư mục. Nếu mạng lỗi giữa chừng, các Publication đã xác minh
được giữ lại; thư mục tạm của Publication lỗi được dọn và thử lại ở lượt sau.

## Kiểm tra offline và bàn giao

```sh
python -m scripts.m2_sample verify \
  --plan configs/m2-sample-100.json \
  --data-dir data/m2-sample
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/test_m2_sample.py tests/test_hf_io.py tests/test_file_corpus.py
```

`verify` kiểm mọi Publication/Version theo plan, không gọi mạng, ghi `sample-report.json`
gồm số lượng kỳ vọng, số Publication đã xác minh, số Version `non_tex` và kết quả từng
Publication. Exit 0 khi đủ tất cả; exit 2 khi thiếu/hỏng hoặc cấu hình/plan không hợp lệ.
Đây là kiểm tra đầu vào, không phải tỉ lệ parse thành công. Mọi raw và report nằm dưới
`data/` đã được Git bỏ qua; chỉ bàn giao code, test, tài liệu và plan chứa ID/hash qua PR.

Trước khi nghiệm thu dữ liệu thật: tạo plan 100 bài từ corpus Bảo thật, tải thành công từ
HF theo plan, và chạy `verify` đạt 100/100. Những kiểm chứng HF thật này còn chờ dữ liệu
và cấu hình; kiểm thử hiện tại dùng mock, không cần token hay mạng.

Nguồn: [thẻ Integration](m2-cong-viec.md#44-minh-integration-m25-chạy-batch-số-liệu-báo-cáo),
[hợp đồng H1](data-contract.md#3-h1-corpus-m1--m2),
[HF: tải theo revision và lọc file](https://huggingface.co/docs/huggingface_hub/en/guides/download).
