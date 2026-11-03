# Hai notebook Kaggle: arXiv và S2 độc lập

Range: **2412.08848–2412.13847**, 5.000 ID. Dùng toàn Range để không bỏ sót
các Publication lỗi nằm xen giữa; checkpoint quyết định phần nào phải tải.
Không tự coi 2.500 ID cuối là toàn bộ phần thiếu.

## 1. Bộ đầu vào đã chuẩn bị trên máy

`scripts.prepare_kaggle` gom cache hợp lệ từ các thư mục `data/crawl-*`, bao gồm
các lượt chồng Range. Kiểm tra SHA-256 metadata, references và từng file source.
Nếu một bản mới hỏng, thử bản cũ hợp lệ. Các thư mục gốc không bị xóa/chỉnh sửa;
script giữ khóa để từ chối đóng gói trong khi crawler đang ghi cùng cache.
Manifest đầu vào có dòng cuối bị cắt được đọc mà không sửa file gốc.

Chạy lại khi có thêm cache local mới, nên chọn thư mục output mới để có một
snapshot mới thay vì giữ các thành phần đã hợp lệ từ snapshot trước:

```powershell
.\.venv\Scripts\python.exe -X utf8 -u -m scripts.prepare_kaggle --output data/kaggle-bundle-new
```

Bộ ban đầu nằm ở `data/kaggle-bundle`. Tạo một **Kaggle Dataset private** và
upload **chỉ bốn file** sau (không upload staging, .env hoặc toàn repo):

- `crawler-code.zip`: code tối thiểu; không chứa script có credential proxy cũ.
- `arxiv-seed.zip`: discovery và từng Version source đã xác minh.
- `s2-seed.zip`: references đã xác minh, kể cả của Publication còn thiếu source.
- `bundle-info.json`: danh sách 5.000 ID và số lượng đã đủ/còn thiếu từng dịch vụ.

Snapshot thực tế đã đóng gói ngày 29/10/2026: arXiv đủ **2.512** Publication,
còn **2.488**; S2 đủ **2.483**, còn **2.517**. ZIP arXiv 539.852.323 byte,
ZIP S2 23.810.470 byte. Thành phần hợp lệ của bài chưa đủ vẫn được giữ để
chỉ tải phần thiếu. Đã thử import code trực tiếp từ ZIP trong tiến trình độc lập.

Notebook nhận diện bundle bằng `bundle-info.json`, hỗ trợ cả ZIP giữ nguyên
và thư mục đã được Kaggle giải nén. Không gắn hai phiên bản bundle cùng lúc.

## 2. Notebook arXiv

Upload `notebooks/kaggle_arxiv.ipynb` thành một notebook Kaggle.

1. Add Input: Dataset private vừa tạo, đúng một bản bundle.
2. Bật Internet, chọn CPU (không cần GPU).
3. Trong Secrets, tạo/bật quyền truy cập `CONTACT_EMAIL`.
4. Save Version → Save & Run All.

Notebook tự chọn Range từ bundle, import source/metadata hợp lệ rồi chỉ tải
Version thiếu/hỏng. Không gọi Semantic Scholar. Tối thiểu 3,1 giây giữa request
arXiv, một kết nối tại một thời điểm. Dừng crawler arXiv local trước khi chạy;
không khởi chạy notebook arXiv thứ hai cùng lúc.

Output quan trọng:

- `/kaggle/working/arxiv-checkpoint.zip`
- `/kaggle/working/arxiv-job/tables/papers.parquet`
- `/kaggle/working/arxiv-job/manifests/arxiv-run.json`

## 3. Notebook S2 — chạy cùng lúc

Upload `notebooks/kaggle_s2.ipynb` thành notebook Kaggle thứ hai, Add Input cùng
Dataset private. Bật Internet, CPU, hai Secrets `CONTACT_EMAIL`, `S2_API_KEY`.
Save Version → Save & Run All. Một key là đủ cho luồng này; không cần xin thêm
key để chạy đồng thời với arXiv.

S2 đọc **ID gốc** từ bundle, không chờ source tải xong và không gọi arXiv.
References thành công được cache kể cả khi danh sách trả về rỗng. Lỗi S2 không
biến thành kết quả rỗng thành công. Có phân trang, retry/backoff của client chung.

Output quan trọng:

- `/kaggle/working/s2-checkpoint.zip`
- `/kaggle/working/s2-job/tables/references.parquet`
- `/kaggle/working/s2-job/manifests/s2-run.json`

Hai phiên không dùng chung filesystem đang chạy. Không trỏ cả hai vào cùng
thư mục ghi trên một máy. Chúng dùng cùng snapshot ban đầu và checkpoint riêng.

## 4. Resume qua phiên Kaggle

Mặc định thời gian chạy mỗi job là 9 giờ (`MAX_SECONDS`), tối đa 3 lượt, chờ
1.800 giây giữa lượt. Khi tới ngân sách hoặc Ctrl+C, lưu tiến độ, xuất bảng và
đóng gói checkpoint. Thời gian một request đang chạy và thời gian đóng gói có
thể kéo dài thêm; không chờ tới sát giới hạn phiên mới lưu output.

**File trong /kaggle/working chưa được Save Version không phải bản sao bền vững.**
Notebook không tự upload checkpoint sang Dataset và không bảo đảm giữ dữ liệu
khi máy chủ kill cưỡng bức trước khi output được lưu. Save & Run All và kiểm tra
ZIP checkpoint xuất hiện trong Output của phiên đã lưu. Nếu dừng thủ công,
hãy lưu/tải output trước khi xóa phiên.

Để tiếp tục phiên mới:

1. Giữ bundle Input ban đầu.
2. Add Input thêm **output đã lưu của chính notebook đó** ở phiên trước.
3. Chạy lại notebook. Nó tự tìm `arxiv-checkpoint.zip` hoặc `s2-checkpoint.zip`,
   kiểm tra checksum và import phần hợp lệ. Không cần đổi Range.

Trong cùng phiên, chạy lại cell cũng dùng cache tại thư mục job. Có thể tạo
`STOP_RANGE` trong thư mục job để dừng sau công việc hiện tại; bỏ cờ đó trước
khi resume. Chỉ `status=complete` mới nghĩa là đủ toàn bộ ID cho dịch vụ đó.
`stopped`/`incomplete` vẫn có thể còn nhiều ID cần thử lại.

## 5. Ghép và xuất hai bảng cuối giống pipeline cũ

Các Parquet của từng notebook là **kết quả riêng từng dịch vụ**: bảng S2 có thể
chứa bài chưa tải đủ source. Không dùng chúng để tuyên bố toàn pipeline hoàn tất.

Sau khi cả hai phiên đã lưu Output, tải hai ZIP checkpoint về máy, ví dụ vào
`data/kaggle-downloads`, rồi chạy:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m scripts.merge_split --arxiv data/kaggle-downloads/arxiv-checkpoint.zip --s2 data/kaggle-downloads/s2-checkpoint.zip
```

Bước này không gọi mạng. Kết quả ở `data/kaggle-merged/`:

- `raw/<publication-key>/v<n>/`, `metadata/`, `references/`, `manifests/` giống cũ.
- `tables/papers.parquet`, `tables/references.parquet`: chỉ Publication đủ
  metadata, mọi Version hợp lệ (kể cả non_tex) **và** S2 thành công.
- `manifests/merge-report.json`: số Publication đủ và danh sách còn thiếu.

Schema không thay đổi. Authors/revised_dates/ref_authors vẫn list<string>;
ngày xuất bản S2 không bị gán thành ngày nộp arXiv. Metadata raw và source đã
đủ từng phần vẫn giữ trong cache để lần sau bổ sung phần thiếu. Merge exit 1
nếu còn pending, không có nghĩa những dòng Parquet đã xuất bị hỏng.

## Kiểm chứng và giới hạn

Test offline kiểm tra hai dịch vụ độc lập, resume không gọi mạng, import từ
cache chồng Range/bị cắt, ZIP checkpoint, budget dừng và Parquet cuối bằng
pipeline cũ trên cùng fixture. Không đổi schema chung hay dữ liệu gốc.
Ngày 29/10/2026: **113 test và 28 subtest đạt** trên môi trường Windows hiện tại.
Chưa thực thi trong tài khoản Kaggle; cần kiểm tra quyền Internet, Secrets,
quota dung lượng và Output đã lưu ở giao diện Kaggle khi chạy.
