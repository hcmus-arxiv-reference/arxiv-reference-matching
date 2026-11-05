# SUMMARY

File Summary về quá trình crawl dữ liệu trên máy local của Hải, nhánh
`Hai_crawler`. Range **2412.08848–2412.13847**, gồm **5.000 ID**, tính cả hai đầu.

Quy trình: **crawl metadata/source arXiv → dùng danh sách ID gốc (index) để
chạy S2 → ghép cache và xuất Parquet**. Chạy bằng `notebooks/local_crawl.ipynb`
trong VS Code hoặc `scripts/crawl_local.py`.

## Crawl ARXIV LaTeX Source

### 1. Lấy ID theo Range

1. Cấu hình Range trong notebook local bằng
   `parse_range('2412.08848', '2412.13847')`, hoặc truyền `--start`, `--end`
   khi chạy CLI. Range nằm trong cùng tháng 12/2024.
2. Tạo danh sách `IDS` gồm 5.000 ID gốc, không kèm Version. Đây là danh sách
   index đầu vào được giữ để dùng tiếp ở bước S2.
3. `src/crawl/batched.py` gọi arXiv API theo batch tối đa 50 ID để lấy metadata,
   xác định mỗi Publication có bao nhiêu Version và tải từ `v1` đến `vN`.
   Các ngày sửa đổi của Version được tra cứu bổ sung khi cần.
4. Nếu batch lỗi hoặc thiếu ID, crawler thử truy vấn riêng từng ID. Thiếu trong
   một batch chưa đủ để kết luận Publication không tồn tại.
5. Metadata được lưu vào `metadata/<publication-key>.json`; trạng thái được ghi
   trong `manifests/crawl.jsonl`, danh sách ID của job trong `manifests/job.json`.
   Chạy lại sẽ kiểm tra cache để tiếp tục phần chưa đủ.

### 2. Chạy notebook local để tải source

- Mở `notebooks/local_crawl.ipynb` trong VS Code, chọn Python của `.venv`.
  `CONTACT_EMAIL`, `S2_API_KEY` được đọc từ `.env`, không viết key trong notebook.
- Chạy bước arXiv trước. `src/crawl/source.py` tải source từng Version từ
  `export.arxiv.org/src/{id}v{n}`, giải nén và chỉ giữ `.tex`, `.bib` trong
  `raw/<publication-key>/v<n>/`.
- Hỗ trợ archive nhiều file và gzip chỉ có một file TeX. PDF/docx không có
  TeX được ghi `non_tex`, vẫn giữ receipt để không bỏ mất Version.
- Mỗi Version có `source.json` ghi trạng thái, checksum archive và các file
  giữ lại. HTTP 404/410 ghi `unavailable`; lỗi tải/giải nén không được tính
  thành công.
- Tải source tuần tự, một kết nối arXiv tại một thời điểm, cách request ít
  nhất 3,1 giây. Batch metadata giúp giảm request, không tạo nhiều luồng tải
  source đồng thời.
- Kết quả bước này ở `data/local-sequential/arxiv/`. Checkpoint ghi theo từng
  tác vụ, bảng riêng của arXiv được xuất định kỳ sau mỗi 100 Publication được
  xử lý và ở cuối lượt.

### 3. Cơ chế retry và resume

- HTTP client mặc định timeout 60 giây, tối đa 4 lần retry sau lần gửi đầu.
  HTTP 429/5xx và một số lỗi mạng được thử lại hữu hạn, có giãn cách/backoff.
  Nếu `Retry-After` quá dài, client ghi lỗi để lượt sau thử lại.
- Luồng local mặc định chạy một lượt mỗi dịch vụ. Kết thúc lượt arXiv, dù
  còn bài source lỗi, runner vẫn có thể chuyển sang S2 để lấy phần dữ liệu
  độc lập. Có thể tăng `--max-passes`; `--retry-delay` cấu hình chờ giữa lượt.
- Resume kiểm tra manifest và checksum. Phần đã hợp lệ được bỏ qua; phần
  thiếu/hỏng mới tải lại. Vẫn xét cả Range để không bỏ sót lỗi trước mốc
  “bài thứ 2.500”.
- Dừng bằng Ctrl+C hoặc Interrupt cell để lưu tiến độ. Nếu dừng ở bước arXiv,
  runner không tự chạy tiếp S2. Chạy lại cùng thư mục output để resume.

## Crawl references bằng Semantic Scholar

Phần này lấy **references của Publication** để đối chiếu với BibTeX entry;
không trực tiếp parse `\bibitem` từ LaTeX.

1. Sau khi kết thúc lượt arXiv, runner dùng lại danh sách ID gốc `IDS` để
   chạy S2. Trong code hiện tại, index là danh sách ID trong bộ nhớ và
   được ghi lại trong `manifests/job.json`; runner chuyển cùng danh sách này
   sang bước S2.
2. S2 dùng toàn bộ ID trong Range, không yêu cầu bài đã tải đủ source. Vì vậy,
   bài thiếu một Version vẫn có thể có cache references để dùng tiếp sau này.
3. `src/crawl/semantic_scholar.py` dùng `S2_API_KEY` từ `.env`, xử lý tuần tự
   các ID chưa có references hợp lệ. Bản local này không dùng nhiều S2 worker
   bất đồng bộ. Client giãn cách 1,1 giây khi có key, 3,1 giây khi không có.
4. Gọi `/paper/ARXIV:{id}/references`, lấy `paperId`, `externalIds`, tiêu đề,
   tác giả và `publicationDate`. Theo trường `next` để lấy hết các trang;
   mặc định 100 references/trang.
5. Áp dụng retry hữu hạn cho lỗi có thể thử lại. Nếu vẫn lỗi, manifest ghi
   `error` và runner tiếp tục ID kế tiếp. Danh sách rỗng từ phản hồi thành công
   là kết quả hợp lệ; lỗi API không được ghi thành danh sách rỗng thành công.
6. Lưu JSON thô vào `references/<publication-key>.json`, giữ cả references
   không có arXiv ID. Checkpoint riêng ở `data/local-sequential/s2/`; chạy lại
   bỏ qua các cache đã xác minh và chỉ bổ sung phần thiếu.
7. Sau hai bước, ghép cache và xuất `papers.parquet`, `references.parquet`.
   Bảng cuối chỉ gồm Publication có metadata, đủ source mọi Version và S2
   thành công. References xuất ra phải có arXiv ID, được khử trùng lặp theo
   `(arxiv_id, ref_arxiv_id)`. Không lấy ngày xuất bản S2 thay ngày nộp arXiv;
   `ref_submission_date` chưa xác minh vẫn để null.

Lệnh local tự chạy lần lượt arXiv, S2 rồi ghép:

```powershell
.\.venv\Scripts\python.exe -X utf8 -u -m scripts.crawl_local
```

Các thư mục `data/local-sequential/arxiv/`, `s2/`, `merged/` lưu checkpoint
và output riêng. File lock ngăn hai writer dùng chung thư mục. Bảng riêng
của từng dịch vụ thể hiện tiến độ dịch vụ đó; chỉ bảng ghép cuối dùng để
đếm Publication hoàn chỉnh.

## Số liệu

### 1. Kết quả crawl arXiv trên local — toàn Range

Kiểm tra lại cache local ngày **05/11/2026**, không chạy lại crawl mạng trong
lần tổng hợp. Nguồn số liệu: [hai-summary.json](hai-summary.json).

- Đầu vào **5.000 ID**; metadata hợp lệ của **4.985 Publication (99,70%)**.
  Chưa xác định số Version kỳ vọng của 15 ID thiếu metadata hợp lệ.
- Tổng Version kỳ vọng trên các bài tìm thấy: **8.086**.
- Version có TeX: **7.396**; non-TeX hợp lệ: **504**.
- Tổng source hợp lệ: **7.900/8.086 Version (97,70%)**.
- Còn **29 Version unavailable (404/410)** và **157 Version lỗi/chưa hợp lệ**.
- Tổng TeX/BibTeX giữ lại: **3.816.242.614 byte**. Với các Publication hoàn chỉnh,
  trung bình source sau lọc **793.990,42 byte/bài**, trung vị **129.160 byte**.
- Kích thước trước bỏ hình của toàn Range chưa được ghi nhận đầy đủ. Không dùng
  số đo một mẫu nhỏ thay cho toàn bộ corpus.

### 2. Kết quả lấy references và xuất bảng — toàn Range

- Trong **4.985 Publication có metadata hợp lệ**, **4.917 bài** lấy S2 thành
  công (**98,64%**), gồm **1.121 bài** nhận danh sách rỗng hợp lệ; còn 68 bài
  thiếu cache S2 hợp lệ.
- Có **172.954 Reference thô**, trung bình **35,17 Reference/bài lấy S2 thành công**;
  trong đó **84.719 bản ghi có arXiv ID** trước dedup.
- Worker S2 còn có 15 cache thành công ở các ID thiếu metadata. Tổng worker
  ghi nhận **4.932/5.000 ID thành công**, nhưng thống kê theo cấu trúc báo cáo
  chỉ dùng 4.917 bài đã có metadata hợp lệ như trên.
- Đủ cả metadata, source mọi Version và S2: **4.775/5.000 Publication (95,50%)**.
- Bảng cuối: **4.775 dòng papers**, **81.847 dòng references**; cả hai đọc đúng
  schema, không có khóa trùng hoặc ID của bài trích dẫn nằm ngoài Range.
- Bảng cuối có ít references hơn 84.719 vì chỉ xuất các Publication hoàn chỉnh.
  Cache S2 của bài còn thiếu source vẫn giữ lại để resume.

Hai bảng đã xác minh dùng cho summary ở `data/benchmark-ngochai06/tables/`,
được xuất từ snapshot cache đã gom của hai bước local. Còn 225 ID chưa đạt
điều kiện hoàn chỉnh; các nhóm thiếu metadata, thiếu Version và thiếu S2 có
thể chồng nhau, không cộng trực tiếp.

### 3. Thời gian đo trên local — mẫu 10 ID

Lượt đo riêng ngày **03/11/2026** chạy `2412.08848–2412.08857` trên cache trống,
bằng `scripts/benchmark_sample.py`. Đây là số đo mẫu 10 bài, không phải thời
gian của toàn Range.

- Lấy ID/metadata: **3,106 giây**, **2 request**, không retry.
- Tải và xử lý source: **223,221 giây**, **15 request**, không retry;
  đủ 15/15 Version, gồm một non-TeX.
- S2: **50,110 giây**, **24 request**, **14 retry**, có **15 phản hồi HTTP 429**;
  9/10 bài thành công, bài `2412.08852` còn thiếu references.
- Export: **0,448 giây**; xuất 9 dòng papers và 101 dòng references.
- Tổng wall time: **278,020 giây**, khoảng **4 phút 38 giây**.
- RAM đỉnh **103,320 MiB**, trung bình mẫu **67,872 MiB**; disk output
  đỉnh/cuối **1,468 MiB**, lấy mẫu mỗi giây trên Windows local CPU.

Thời gian Stage gồm chờ rate limit/backoff trong lời gọi đó. Tổng Stage khác
wall time do runner và ghi checkpoint còn overhead. Khoảng 130 giây đầu có
một tiến trình thu thập test offline chạy riêng rồi được dừng, nên lượt mẫu
chưa phải phép đo trong môi trường cô lập. Bằng chứng nằm ở
[ngochai06-sample10.json](ngochai06-sample10.json) và
`data/sample10-20261103-103748/samples.csv`.

Lượt 5.000 ID tích lũy qua nhiều lần chạy/resume chưa có log đo liên tục đầy
đủ để chốt tổng thời gian và thời gian từng bước. Không cộng thời gian nghỉ
theo cấu hình hoặc nhân thời gian mẫu 10 bài để suy ra số đo toàn Range.
