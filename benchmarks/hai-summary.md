# Summary quá trình xây dựng và chạy crawler — Hải

## 1. Mục tiêu và phạm vi

Phần thu thập của Hải xử lý Range **2412.08848–2412.13847**, gồm 5.000 ID
tháng 12/2024, tính cả hai đầu. Mục tiêu là lấy metadata của từng Publication,
tải source của mọi Version, lấy references từ Semantic Scholar (S2), sau đó
xuất hai bảng `papers.parquet` và `references.parquet` theo schema chung.

Quá trình thực hiện gồm tích hợp crawler với output cũ, bổ sung công cụ chạy
Range có checkpoint, chuẩn bị hai notebook tách arXiv/S2 cho Kaggle, rồi chuyển
sang chạy tuần tự trên máy local. Cache được giữ và nhập lại giữa các lượt để
tiếp tục phần thiếu. Kết quả cuối trong tài liệu này được kiểm tra từ output
local ngày 05/11/2026; không cộng kết quả Kaggle chưa được lưu hoặc tải về.

## 2. Xây dựng các bước thu thập

Repo còn giữ notebook `src/arxiv_crawler.ipynb`, trong đó `get_id_list` đọc
danh sách ID, `get_source` tải source bằng stream/chunk và ghi xuống đĩa,
`crawl_sources` tổ chức lượt tải và ghi thông tin kết quả. Các hàm
`write_done_files`/`write_json` hỗ trợ xuất thông tin cho từng bài. Notebook
được giữ như một cách chạy riêng; không tự coi output của nó là cache đã
được xác minh theo manifest của pipeline tổng hợp.

Để giữ output tương thích, bản CLI tái sử dụng core `src/crawl/` từ commit
`63df237`, rồi tích hợp discovery theo lô và trình chạy Range. Đây là việc
tái sử dụng và điều chỉnh các thành phần có sẵn trong nhóm, không phải toàn bộ
module đều được viết mới từ đầu. Tại lượt đo mẫu, core được xác định bằng
commit `11bd1ebe74eb229482c4a23c8d6c691f082c2e78` trên nhánh `Hai_crawler`.

Ở bước discovery, `src/crawl/batched.py` bổ sung `BatchedDiscovery` cho
`src/crawl/discovery.py`. Mặc định truy vấn metadata theo lô tối đa 50 ID,
giúp giảm số lần gọi API so với truy vấn riêng từng ID. Khi lô không trả đủ
hoặc bị lỗi, crawler thử truy vấn riêng; không coi việc thiếu trong một lô là
bằng chứng Publication không tồn tại. Các lần tra cứu bổ sung lấy ngày sửa
đổi của từng Version khi cần.

Ở bước source, `src/crawl/source.py` tải mọi Version đã xác định, giải nén
source và chỉ giữ `.tex`/`.bib`. Nó xử lý cả archive nhiều file lẫn gzip chỉ
chứa một file TeX. Những Version chỉ có PDF/docx được ghi receipt `non_tex`,
vẫn được tính là đã xử lý nếu xác minh được định dạng. HTTP 404/410 được ghi
`unavailable`; dữ liệu tải lỗi hoặc hỏng không được tính thành công.

Ở bước S2, `src/crawl/semantic_scholar.py` gọi API theo ID gốc của Publication
và đọc hết các trang references, mặc định 100 bản ghi/trang. Cache JSON giữ
cả references không có arXiv ID để phục vụ thống kê. Khi xuất bảng, chỉ giữ
bản ghi có arXiv ID, bỏ hậu tố Version và khử trùng lặp theo cặp
`(arxiv_id, ref_arxiv_id)`. Danh sách rỗng từ một phản hồi hợp lệ được tính là
lấy S2 thành công; lỗi API được giữ thành trạng thái lỗi riêng.

`src/crawl/http_client.py` dùng chung cho các bước tải, có timeout và retry
hữu hạn cho lỗi mạng/429/5xx. Request arXiv dùng `export.arxiv.org`, cách nhau
ít nhất 3,1 giây trong cấu hình runner và chỉ một kết nối tại một thời điểm.
Client S2 có giãn cách riêng: 1,1 giây nếu có API key, 3,1 giây nếu không có.
Giãn cách này không bảo đảm hết 429, vì còn phụ thuộc quota thực tế của dịch vụ.

## 3. Tổ chức luồng chạy và những lần điều chỉnh

### 3.1. CLI chạy toàn Range

`scripts/crawl_range.py` cung cấp một lệnh nhận ID đầu/cuối. Runner kiểm tra
cache, prefetch metadata theo lô, rồi lần lượt xử lý các Publication còn thiếu.
Trong bản CLI này, phần tải source và lấy S2 được thực hiện lần lượt trong
quá trình xử lý Publication; discovery theo lô không có nghĩa là tải source
bằng 50 kết nối song song.

Runner ghi tiến độ, danh sách còn thiếu và xuất Parquet định kỳ. Mặc định bản
CLI này cho phép tối đa ba lượt, chờ 1.800 giây giữa các lượt retry. HTTP client
còn có retry/backoff riêng cho từng request. Hai mức chờ này có vai trò khác
nhau và đều có thể làm thời gian vận hành kéo dài.

### 3.2. Tách arXiv và S2 cho Kaggle

Sau khi lượt crawl dài còn nhiều phần thiếu, đã chuẩn bị
`notebooks/kaggle_arxiv.ipynb` và `notebooks/kaggle_s2.ipynb`, dùng các hàm
trong `src/crawl/split.py`. Notebook arXiv chỉ xử lý discovery/source;
notebook S2 lấy references từ danh sách ID có sẵn nên không phải chờ source
tải xong. Hai notebook có thể chạy đồng thời như hai công việc độc lập, mỗi
công việc ghi vào thư mục riêng. Đây không phải cách tăng số kết nối arXiv.

`scripts/prepare_kaggle.py` đóng gói code và cache đã xác minh để đưa vào
Dataset input; checkpoint của từng notebook được đóng gói riêng. Hai phiên
Kaggle không chia sẻ ổ đĩa đang ghi. Muốn resume ở phiên sau cần lưu Output,
gắn lại checkpoint làm Input; muốn chuyển về local cần tải checkpoint về máy.

Trong vận hành, việc dùng `Stop Session` khi chưa lưu Output đã làm phát sinh
khó khăn truy cập checkpoint. Vì vậy, số liệu tổng hợp chỉ dùng các file thực
sự còn trên máy; không suy ra rằng mọi dữ liệu từng chạy trên Kaggle đều đã
được nhập về. Thời lượng chạy thực tế của từng phiên Kaggle không có log đầy
đủ để đưa vào bảng so sánh hiệu năng.

### 3.3. Chuyển sang local: arXiv trước, S2 sau

Theo nhu cầu tiếp tục chạy trên VS Code, đã tạo `scripts/crawl_local.py` và
`notebooks/local_crawl.ipynb`. Hai entry point này đọc `.env`, nhập cache hợp
lệ từ các lượt cũ và chạy theo thứ tự:

1. Kiểm tra cache, bổ sung metadata/source arXiv còn thiếu.
2. Kết thúc lượt arXiv rồi mới chạy S2 cho các ID chưa có cache references hợp lệ.
3. Ghép kết quả hai dịch vụ và xuất hai Parquet cuối.

Mặc định local chạy một lượt mỗi dịch vụ, không có khoảng chờ 30 phút giữa
nhiều lượt. Nếu một lượt kết thúc vẫn còn bài lỗi, trạng thái là `incomplete`
và lần chạy sau tiếp tục thử phần thiếu. Nếu người dùng ngắt arXiv có kiểm
soát, runner lưu tiến độ và không tự khởi chạy tiếp S2.

Không đặt lại mốc bắt đầu cứng ở “bài thứ 2.500”, vì có thể còn lỗi nằm xen
giữa các ID đã đi qua. Thay vào đó, runner xét toàn bộ Range rồi bỏ qua từng
thành phần đã xác minh. Thư mục làm việc tách thành
`data/local-sequential/arxiv/`, `s2/` và `merged/` để hai dịch vụ có checkpoint
riêng. S2 trong bản này vẫn gọi tuần tự; không sử dụng nhiều S2 worker đồng thời.

## 4. Checkpoint, resume và xuất dữ liệu

`src/crawl/manifest.py` lưu trạng thái theo tác vụ discovery, từng Version
source và references. Metadata/reference có checksum; mỗi Version có
`source.json` ghi loại source, checksum và danh sách file. Resume kiểm tra
các bằng chứng này thay vì chỉ dựa vào việc thư mục đã tồn tại. Một Publication
đã đủ source nhưng thiếu S2 chỉ cần bổ sung phần references.

`src/crawl/split.py` hỗ trợ nhập cache từ các Range chồng nhau, chọn thành
phần hợp lệ và ghép offline. Việc này giúp dùng lại các lượt crawl trước khi
chuyển entry point hoặc môi trường chạy. File lock bảo vệ thư mục đang được
ghi; không khởi chạy nhiều writer trên cùng cache.

Bảng riêng của mỗi dịch vụ thể hiện tiến độ của dịch vụ đó. Hai bảng cuối
chỉ chứa Publication có metadata hợp lệ, đủ mọi Version và lấy S2 thành công.
`authors`, `revised_dates`, `ref_authors` vẫn là list of strings. Ngày xuất bản
của S2 không được tự dùng thay ngày nộp arXiv, nên `ref_submission_date` chưa
xác minh được vẫn để null.

## 5. Thời gian chạy và số đo hiệu năng

### 5.1. Lượt tích lũy toàn Range

Lượt 5.000 ID đã chạy qua nhiều lần dừng/resume và thay đổi cách tổ chức luồng.
Trong trao đổi vận hành, người chạy từng ghi nhận khoảng 20 giờ cho khoảng
2.500 bài. Đây là thông tin ước lượng được báo lại, không phải kết quả harness;
không xác định được nó bao gồm những lần dừng/chờ nào hoặc định nghĩa “được
một bài” ở thời điểm đó.

Vì không có log đo liên tục đầy đủ, không chốt tổng wall time, thời gian từng
Stage, RAM đỉnh/trung bình hoặc disk đỉnh cho toàn Range. Cấu hình chờ retry
1.800 giây cũng không được tự nhân lên thành thời gian cooldown đã xảy ra.

### 5.2. Lượt đo thật 10 ID đầu ngày 03/11/2026

Để có số đo trực tiếp từ code của Hải, `scripts/benchmark_sample.py` chạy
**2412.08848–2412.08857** trên cache trống, với các thiết lập HTTP của crawler
cũ. Wrapper ghi thời gian từng Stage, số request thực sự gửi đi và retry;
psutil lấy mẫu RSS toàn cây tiến trình cùng dung lượng output mỗi giây.

Kết quả đo trên Windows local CPU, Python 3.14.0:

- Discovery: **3,106 giây**, **2 request**, không retry.
- Tải và xử lý source: **223,221 giây**, **15 request**, không retry;
  đủ **15/15 Version**, gồm một non-TeX.
- S2: **50,110 giây**, **24 request**, **14 retry** và **15 phản hồi HTTP 429**;
  thành công 9/10 Publication. Bài `2412.08852` còn thiếu references.
- Export: **0,448 giây**, xuất 9 dòng papers và 101 dòng references.
- Tổng wall time: **278,020 giây**, khoảng **4 phút 38 giây**.
- RSS đỉnh **103,320 MiB**, trung bình mẫu **67,872 MiB**;
  disk output đỉnh/cuối **1,468 MiB**.

Tổng thời gian các Stage không bằng wall time vì runner, ghi checkpoint và
các thao tác ngoài lời gọi Stage còn có overhead. Bộ đo cũng thêm overhead
lấy mẫu và thống kê archive. Khoảng 130 giây đầu có một tiến trình thu thập
test offline chạy riêng rồi được dừng, nên đây là pilot local, chưa phải
đối chứng Colab trong môi trường cô lập. Không nhân thời gian mẫu lên để
ước lượng lượt 5.000 ID.

Bằng chứng đo nằm ở [ngochai06-sample10.json](ngochai06-sample10.json) và
`data/sample10-20261103-103748/samples.csv`. File [hai.json](hai.json) trình bày
cùng lượt mẫu theo cấu trúc benchmark tổng hợp; không dùng thay số liệu corpus.

## 6. Tổng hợp kết quả toàn Range

Các mục dưới theo cấu trúc [Kết quả thu thập của nhóm](https://hcmus-arxiv-reference.github.io/Jupyter-Notebook-report-for-mile1/ket-qua).
Số liệu lấy từ cache local, kiểm tra lại ngày 05/11/2026. File máy đọc được là
[hai-summary.json](hai-summary.json), snapshot `format: 1` cho toàn Range 5.000 ID.

### 6.1. Publication và Version

- Publication tìm thấy: **4.985/5.000 (99,70%)**.
- Publication hoàn chỉnh: **4.775/5.000 (95,50%)**. Hoàn chỉnh nghĩa là đủ mọi
  Version đã xác minh và lấy S2 thành công; còn 225 ID chưa đạt điều kiện này.
- Version kỳ vọng trên các Publication tìm thấy: **8.086**,
  trung bình **1,62 Version/Publication**.
- Source TeX: **7.396**; non-TeX: **504**; tổng hợp lệ: **7.900/8.086 (97,70%)**.
- Không tải được (404/410): **29**; lỗi tải/chưa hợp lệ: **157**; chưa thử: **0**.
  Số Version của 15 ID chưa có metadata hợp lệ chưa xác định, không coi là 0.
- Phân bố số Version của Publication nằm trong `versions_distribution` của JSON.

### 6.2. Kích thước source

- Tổng TeX/BibTeX giữ lại ở các Version hợp lệ: **3.816.242.614 byte**.
- Với **4.775 Publication hoàn chỉnh**, trung bình sau khi bỏ hình:
  **793.990,42 byte/bài (0,794 MB)**; trung vị **129.160 byte**;
  lớn nhất **192.700.276 byte**.
- Tổng dung lượng source giữ lại của các bài hoàn chỉnh: **3.791.304.238 byte**.
- Kích thước trước bỏ hình và tỷ lệ giảm của toàn Range **chưa được đo**.
  Không dùng số của lượt 10 bài để thay vào đây. Đơn vị MB trong phần này là
  1.000.000 byte, đúng cách trình bày trên trang báo cáo.

### 6.3. References

- Thành công: **4.917/4.985 (98,64%)** Publication đã có metadata hợp lệ;
  trong đó **1.121 bài** được S2 trả về danh sách rỗng hợp lệ.
- Có **172.954 Reference thô**, trung bình **35,17/bài thành công**;
  trung vị **32**, lớn nhất **428**.
- Bản ghi có arXiv ID trước dedup: **84.719/172.954 (48,98%)**;
  sau dedup cũng là **84.719** cặp, gồm **4.563** cặp có arXiv ID dạng cũ.
- Biểu đồ phân bố có thể dựng từ `references.histogram` trong JSON;
  đây là phân bố số Reference thô, không phải số dòng Parquet.
- Cache worker S2 có thêm 15 kết quả thành công ở các ID thiếu metadata.
  Chúng không được cộng vào tỷ lệ 4.917/4.985 theo hợp đồng snapshot của báo cáo.

### 6.4. Kiểm tra bảng xuất ra

- `papers.parquet`: **4.775 dòng**, đúng schema, **0 khóa trùng**, **0 ID ngoài Range**.
- `references.parquet`: **81.847 dòng**, đúng schema, **0 khóa trùng**, **0 ID ngoài Range**.
- Bảng cuối chỉ gồm Publication hoàn chỉnh nên số dòng references nhỏ hơn
  84.719 cặp của toàn bộ các Publication lấy S2 thành công.
- Đã kiểm tra lại checksum source, metadata, cache S2 và hai bảng được xuất
  từ dữ liệu có sẵn. Danh sách lỗi còn lại nằm trong `failures` của JSON.
- Output đầy đủ và hai Parquet ở `data/benchmark-ngochai06/`. Chỉ xuất summary
  và bảng từ cache; không gọi API crawl lại trong lần tổng hợp này.

## 7. Đánh giá và tài liệu đối chiếu

Checkpoint theo từng thành phần giúp dùng lại dữ liệu khi chuyển giữa CLI,
Kaggle và local; batch discovery giảm request metadata, còn tách arXiv/S2 giúp
lỗi hoặc quota của một dịch vụ không làm mất kết quả của dịch vụ kia. Tuy vậy,
Range vẫn chưa hoàn tất: còn 15 ID thiếu metadata hợp lệ, 186 Version đã biết
chưa có source hợp lệ và 68 Publication có metadata nhưng thiếu cache S2.
Các nhóm này có thể chồng nhau, không cộng trực tiếp thành số bài lỗi.

Lượt mẫu cho thấy chờ tải source và giới hạn S2 có thể chiếm phần lớn thời gian,
nhưng chưa đủ để kết luận về tốc độ của cả corpus hoặc so thắng/thua với crawler
khác. Phần đối chứng cần cùng tập ID, cùng môi trường Colab và cùng cách đo.
Sau lần khôi phục code cũ và bổ sung bộ đo, bộ test offline đã đạt **118 test và
28 subtest**; đây là bằng chứng kiểm thử code, tách với kiểm tra output thật.

Các file đối chiếu chính gồm [hướng dẫn CLI](../docs/run-current-crawler.md),
[luồng local](../docs/local-sequential-crawl.md),
[luồng Kaggle](../docs/kaggle-split-crawl.md),
[thống kê lịch sử 5.000 ID](ngochai06-historical5000.json), và
`data/benchmark-audit/validation-report.json`.

Để đưa vào repo báo cáo, chép `hai-summary.json` thành
`data/m1/snapshots/hai.json`. Không thay bằng `benchmarks/hai.json` vì file đó
là benchmark mẫu 10 ID, dùng cấu trúc và phạm vi khác. Không điền thời gian/RAM
của mẫu 10 bài vào benchmark toàn Range chưa được đo.
