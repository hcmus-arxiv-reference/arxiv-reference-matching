# Crawler của Hải

Range: `2412.08848`–`2412.13847`, gồm 5.000 ID. Mặc định chỉ thử 3 ID đầu.

## Chạy trên PowerShell từ thư mục gốc repo

1. Cài môi trường: `python -m pip install -r requirements.txt`.
2. Tạo `.env` cục bộ, thêm `CONTACT_EMAIL=dia_chi_email_cua_ban`.
   Không commit file này. Không cần HF_TOKEN hay S2_API_KEY cho crawler này.
3. Chạy thử: `python -m scripts.crawl_arxiv --limit 3`.
4. Chạy lại đúng lệnh đó. Khi cache còn nguyên, `requests` phải bằng 0.
5. Kiểm tra `data/crawl_hai/run_summary.json`, metadata và vài file source bằng mắt.
6. Chỉ sau khi mẫu ổn, chạy toàn range:
   `python -m scripts.crawl_arxiv --prefix 2412 --start 8848 --end 13847 --limit 5000`.

## Cách hoạt động

### Tối ưu ngày 2026-10-17

- Discovery và metadata Version cũ được truy vấn batch (mặc định 25 ID);
  cấu hình bằng `--batch-size`, tối đa 100. Entry thiếu vẫn được tra riêng,
  không tự kết luận Publication không tồn tại.
- Metadata Version mới nhất dùng lại kết quả discovery.
- Source tải từng chunk 1 MiB xuống file tạm; giải nén tar từ đĩa, bỏ ảnh
  mà không giữ toàn archive/ảnh trong RAM. File TeX/Bib vẫn được giữ trong RAM
  trong bước trích với giới hạn tổng 256 MiB.
- Log hiển thị từng request, retry, tiến độ tải và cache hit.
- Mỗi lượt có bản thống kê riêng trong `runs/<UTC timestamp>.json`;
  `run_summary.json` là bản gần nhất. `http_seconds` bao gồm thời gian request
  và backoff retry, không phải chỉ thời gian server đáp ứng.
- Checkpoint có thêm thời gian download/extract cho các Version tải mới.

Không cam kết tốc độ dựa trên số request: vẫn phải tải toàn archive chứa ảnh
trước khi lọc, và source download còn phụ thuộc băng thông.

Kiểm tra thật ngày 2026-10-17 trên output riêng
`data/crawl_hai_optimized_sample`: 3 Publication đầu range, 4 Version đều
success; 6 request (2 metadata + 4 source), wall time 108,85 giây.
Đây là số đo mẫu, không phải dự báo thời gian toàn range hay so sánh tốc độ
với lượt tải cũ (không còn số đo lượt tải đầu).

- Query Atom API bằng base ID để biết Version mới nhất, rồi lấy metadata
  Version cũ và tải `/src/{id}v{n}`. Không dùng metadata bản mới nhất thay
  metadata Version cũ.
- Một request tại một thời điểm, cách nhau tối thiểu 3,1 giây, tính cả retry.
- Retry tối đa 4 lần với timeout, 429 và một số 5xx; tôn trọng Retry-After.
  403/404 lưu lỗi, không coi là Version rỗng.
- Trích file thường `.tex`/`.bib` từ tar/gzip, giữ nguyên byte và thư mục con;
  không extract link hoặc đường dẫn thoát thư mục. PDF/tar hợp lệ không có TeX
  được ghi `empty`; dữ liệu HTML, không nhận dạng được hoặc gzip hỏng là lỗi.
- Checkpoint ghi atomically sau mỗi Version. Resume xác minh SHA-256 các file
  đã lưu; file thiếu/hỏng sẽ được tải lại. Version lỗi được thử lại ở lượt sau.
- Nhấn Ctrl+C để dừng; chạy lại cùng lệnh để tiếp tục.

## Dữ liệu làm việc

`data/crawl_hai/<arxiv_id>/metadata/`: cache metadata Publication và từng Version.

`data/crawl_hai/<arxiv_id>/v<n>/`: `metadata.json`, `checkpoint.json`, `source/`.

`run_summary.json` chỉ mô tả lượt chạy gần nhất; checkpoint từng Version là
trạng thái bền vững. Không commit dữ liệu. Đây là JSON làm việc nội bộ, chưa
thay đổi schema Parquet chung. Ngày revision được lưu ở `updated` của metadata
từng Version; bước export papers sẽ cần tổng hợp các ngày đó.

## Giới hạn hiện tại

- Chưa lấy references Semantic Scholar hoặc upload Hugging Face.
- Metadata discovery được cache: muốn cập nhật Version mới phát sinh cần một
  cơ chế refresh rõ ràng; hiện lượt resume dùng snapshot đã discovery.
- Chỉ hỗ trợ ID hiện đại trong range này. Payload không nhận dạng được được
  giữ trạng thái lỗi để kiểm tra, không đoán là không có TeX.
- Giới hạn an toàn 256 MiB/response và dữ liệu giải nén; vượt giới hạn báo lỗi.
- Không chạy đồng thời nhiều tiến trình trên cùng output; bộ pacing là trong
  một tiến trình. Không chạy crawler arXiv khác song song để tăng tốc.
- Summary có wall time/request count, chưa là benchmark RAM/disk đầy đủ.

Nguồn: https://info.arxiv.org/help/api/user-manual.html và
https://info.arxiv.org/help/api/tou.html.
