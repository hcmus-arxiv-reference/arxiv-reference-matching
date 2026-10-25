# Hướng dẫn: crawl 5000 ID bị gián đoạn nhưng vẫn đo benchmark đúng

## 1. Vấn đề

Crawl 5000 ID mất nhiều giờ, có thể bị ngắt giữa chừng (mất mạng, máy ngủ, Ctrl+C, crawler tự dừng sau 15 lỗi liên tiếp).

- **Crawler** vốn đã chạy tiếp được: bài có `done.json` và version có `status.json` được bỏ qua.
- **`benchmark.py` bản cũ** thì không: kết quả ghi đè mỗi lần chạy, và nếu bị Ctrl+C hay tắt máy khi đang đo thì không ghi gì cả.

Cách giải quyết: chia lần crawl thành nhiều **đoạn**, mỗi đoạn đo vào một thư mục riêng, cuối cùng **gộp** lại.

## 2. Chuẩn bị (làm một lần)

1. Chép `benchmark.py` (bản mới) đè lên `src/benchmark.py`.
2. Chép `merge_benchmarks.py` vào `src/`.
3. Cài thư viện: `pip install psutil`
4. Đặt biến môi trường trong phiên PowerShell trước khi chạy:

```powershell
$env:CONTACT_EMAIL = "email-của-bạn@example.com"
$env:S2_API_KEY = "<key Semantic Scholar>"
```

> Không dán key vào chat, không commit key lên repo. Nếu key nằm trong file nào đó, thêm file đó vào `.gitignore`. Nếu lỡ lộ key thì tạo lại key mới.

Có `S2_API_KEY` quan trọng: không có key thì dễ bị lỗi 429, mỗi lỗi tính vào chuỗi lỗi liên tiếp, và 15 lỗi liên tiếp sẽ làm crawler dừng cả lần chạy.

## 3. Cách chạy

Mỗi đoạn dùng một thư mục `--out` riêng (`run_01`, `run_02`, ...). Lệnh crawler giữ nguyên giữa các đoạn.

```powershell
# Đoạn 1
python -m src.benchmark --out stats/runs/run_01 -- python -m src.milestone1_crawler --ids-file ids.txt

# Bị ngắt -> chạy tiếp, chỉ đổi tên thư mục --out
python -m src.benchmark --out stats/runs/run_02 -- python -m src.milestone1_crawler --ids-file ids.txt

# Lặp lại run_03, run_04, ... cho đến khi xong
```

Khi đã xong hết, gộp kết quả:

```powershell
python -m src.merge_benchmarks
```

Quy tắc:

- Dùng **cùng** `--ids-file` và cùng thư mục `data/` ở mọi đoạn.
- **Không** chạy hai bản crawler cùng lúc (arXiv chỉ cho phép một kết nối).
- Tên thư mục phải bắt đầu bằng `run_` thì script gộp mới nhận.

## 4. Kết quả

Mỗi đoạn (`stats/runs/run_XX/`):

| File | Nội dung |
|---|---|
| `benchmark.json` | Tổng kết đoạn, ghi cả khi bị Ctrl+C |
| `benchmark_samples.csv` | RAM và đĩa theo thời gian, ghi dần từng giây |

Sau khi gộp (`stats/`):

| File | Nội dung |
|---|---|
| `benchmark_total.json` | Số liệu tổng cho cả đợt crawl và tóm tắt từng đoạn |
| `benchmark_samples_all.csv` | Chuỗi RAM/đĩa liền mạch, dùng để vẽ biểu đồ trong báo cáo |

## 5. Cách tính khi gộp

| Chỉ số | Cách tính |
|---|---|
| `total_wall_seconds` | Tổng thời gian các đoạn **thật sự chạy**. Khoảng nghỉ giữa các đoạn không tính |
| `peak_rss_mb` | Lớn nhất qua mọi đoạn |
| `avg_rss_mb` | Trung bình theo mẫu (khoảng cách mẫu cố định nên xấp xỉ trung bình theo thời gian) |
| `peak_disk_mb` | Lớn nhất qua mọi đoạn (đĩa tích lũy qua các đoạn) |
| `final_disk_mb` | Giá trị cuối của đoạn cuối |

Đoạn bị tắt máy đột ngột (không có `benchmark.json`) vẫn được tính từ file `.csv`. Dòng mẫu bị ghi dở ở cuối được bỏ qua.

## 6. Cần ghi rõ trong báo cáo

1. **Có resume.** Nói rõ lần crawl gồm N đoạn, thời gian là tổng thời gian chạy thật. (Docstring gốc của `benchmark.py` cũng dặn ghi rõ nếu đo resume.)
2. **Thời gian nghỉ (cooldown).** Khi có 5 lỗi mạng liên tiếp, crawler ngủ 5 phút, rồi 10, rồi tối đa 30 phút. Thời gian ngủ nằm trong wall time và không được ghi riêng. Muốn loại ra thì phải thêm vào crawler đoạn log thời gian cooldown.
3. **Số liệu theo bài.** Bài đang chạy dở lúc bị ngắt, hoặc bài lỗi được thử lại, có `seconds` thấp hơn thực tế vì các version đã tải được bỏ qua. Chỉ ảnh hưởng một số ít bài, nhưng nên nêu.
4. **Nơi đo.** Đề Milestone 1 ghi bản benchmark cuối cùng chạy trên Google Colab ở chế độ CPU-only. Hỏi lại giảng viên xem số đo trên máy cá nhân có được chấp nhận không. Nếu phải đo lại trên Colab, một tập con nhỏ chạy một mạch không bị ngắt sẽ dễ làm sạch hơn so với 5000 bài.

## 7. Kiểm tra lỗi sau khi chạy

```powershell
python src/analyze_errors.py
```

Chú ý mục 4 ("Repeat failures"): `failed 2+ times and still failing` là danh sách bài thật sự có vấn đề riêng.

Cách đọc nhóm lỗi:

- **Network (IncompleteRead):** kết nối bị đứt giữa lúc tải file lớn. Bản crawler hiện tại tải tiếp được bằng Range. Nếu vẫn còn bài lặp lại lỗi này sau khi chạy lại, nghi `If-Range` làm server bỏ qua Range; gửi dòng `where` và `url` để vá.
- **429 từ Semantic Scholar:** bị giới hạn tốc độ khi lấy reference. Kiểm tra `S2_API_KEY` đã được đặt chưa. Chạy lại khá rẻ vì các version đã tải được bỏ qua.

Sau đó tính thống kê cho báo cáo:

```powershell
python make_stats.py --ids-file ids.txt
```
