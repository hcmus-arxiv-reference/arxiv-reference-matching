# Đo thật crawler cũ Hải: 10 ID đầu, 03/11/2026

File nộp: `benchmarks/ngochai06.json`; bản cùng nội dung có tên rõ phạm vi tại
`benchmarks/ngochai06-sample10.json`. Thống kê 5.000 ID cũ chuyển sang
`benchmarks/ngochai06-historical5000.json`; không dùng thời gian mẫu để điền vào lượt cũ.

## Cấu hình

- Crawler: `Hai_crawler`, core từ commit `11bd1ebe74eb229482c4a23c8d6c691f082c2e78`.
- Sample: **2412.08848–2412.08857**, 10 ID, cold run, không dùng cache cũ.
- Chạy trên Windows local CPU, Python 3.14.0; thông số máy ghi trong JSON.
- Thứ tự: batch discovery, source mọi Version, S2 tuần tự, export. Giữ nguyên
  client/rate limit/timeout/retry cũ; wrapper chỉ quan sát request và thời gian.
- RSS toàn cây tiến trình và disk output lấy mẫu 1 giây, có CSV chứng minh.

## Kết quả

- Wall: **278,020 giây**.
- Discovery: 3,106 giây, 2 request, 0 retry.
- Source: 223,221 giây, 15 request, 0 retry; 15/15 Version hợp lệ, gồm 1 non-TeX.
- S2: 50,110 giây, 24 request, 14 retry; 15 phản hồi 429, thành công 9/10 Publication.
- Export: 0,448 giây; 9 dòng papers, 101 dòng references Parquet.
- Hoàn chỉnh cả source và S2: **9/10 Publication**. Bài `2412.08852` thiếu S2 sau 429.
- Reference thô: 217; có arXiv ID trước dedup: 101.
- RSS đỉnh: **103,320 MiB**; trung bình mẫu: **67,872 MiB**.
- Disk đỉnh/cuối của output: **1,468 MiB**.
- Payload giải nén trước bỏ hình: **89.799.271 byte**; TeX/BibTeX giữ lại: **1.288.899 byte**.

## Bằng chứng và chạy lại

Output local: `data/sample10-20261103-103748/output/` gồm raw, metadata,
references, manifest và hai Parquet. CSV lấy mẫu: thư mục cha, `samples.csv`.
`validation-report.json` đối chiếu tất cả bộ đếm, checksum và schema Parquet;
không có counter mismatch, một phát hiện do thiếu S2 của `2412.08852`.

```powershell
.\.venv\Scripts\python.exe -X utf8 -u -m scripts.benchmark_sample
```

Mỗi lần chạy tạo output mới, không ghi đè cache cũ; file JSON sample sẽ cập nhật
theo lượt mới. Script cần psutil và cấu hình .env; không in key vào log.

Các hạn chế: đây là **pilot local**, chưa phải đối chứng chung Colab. Trong khoảng
130 giây đầu, một tiến trình thu thập test offline chạy riêng rồi đã dừng; không
coi CPU/disk hoàn toàn cô lập. Thời gian wall bắt đầu sau khởi tạo import/client,
kết thúc sau export, không gồm audit hậu kiểm. Thời gian Stage đo quanh lời gọi
Stage nên không cộng bằng wall do runner/ghi manifest còn overhead. Bộ đo payload
archive và sampler cũng có overhead. Giữ kết quả lỗi 429, không chạy bù vào cold run.

Sau lượt đo: **118 test và 28 subtest đạt**, chạy offline bằng `pytest tests`
để không quét các thư mục dữ liệu lớn khi thu thập test.

Link Drive do người dùng cung cấp ở `benchmarks/ngochai06-output.md` chưa được
đối chiếu/upload mẫu mới; khi gửi Bảo cần kèm đúng output của lượt đo này.
