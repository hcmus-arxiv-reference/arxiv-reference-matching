# Milestone 1 - Tài liệu kỹ thuật pipeline crawl dữ liệu arXiv

Môn: Introduction to Data Science - arXiv Project - Milestone 1 (Data Crawling).
Đề gốc: https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling (trang tổng quan: https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/).

Tài liệu này viết cho các thành viên trong nhóm. Đọc xong bạn nên:
- hiểu pipeline làm gì và vì sao thiết kế như vậy,
- chạy được code trên máy mình hoặc trên Colab,
- đọc được từng file dữ liệu sinh ra (kiểu dữ liệu, định dạng JSON),
- biết những gì đã kiểm tra, những gì chưa, và việc còn lại.

## Trạng thái của tài liệu (đọc trước)

| Mục | Tình trạng |
|---|---|
| Code | 7 script Python: `milestone1_crawler.py`, `make_ids.py`, `make_stats.py`, `benchmark.py`, `merge_benchmarks.py`, `analyze_errors.py`, `diagnose_download.py` (+ `requirements.txt`) |
| Môi trường đã thử | Python 3.12, thư viện `arxiv` 4.0.1 (kéo theo `requests`) |
| Kiểm thử đã làm | Kiểm thử **offline bằng mạng giả** (xem mục 11) |
| Chưa kiểm chứng | Chưa chạy trên arXiv và Semantic Scholar **thật** (môi trường soạn code không truy cập được hai trang này). Việc đầu tiên khi nhận code là thử 1 bài thật |
| Số liệu tốc độ | Mục 10 là **ước lượng tính toán**, chưa phải số đo. Có bảng trống để điền số đo thật |
| Báo cáo Jupyter Book, README, chạy thật 5000 ID | **Chưa làm** |

Phần "yêu cầu của đề" ở mục 1.5 là tóm tắt theo hiểu biết của người soạn. Hãy đối chiếu lại với đề gốc, nhất là những chỗ ghi "cần xác nhận".

---

## 1. Tổng quan

### 1.1 Bài toán, nói đơn giản

arXiv là kho bài nghiên cứu. Tác giả có thể sửa bài nhiều lần, mỗi lần là một **phiên bản** (version): v1, v2, v3... Milestone 1 yêu cầu viết chương trình tự động để, với **mỗi bài và mỗi phiên bản**:

1. Lấy thông tin bài (tên, tác giả, ngày đăng...).
2. Tải "bản thảo gốc" LaTeX (chỉ giữ file `.tex` và `.bib`, bỏ ảnh).
3. Lấy danh sách các bài mà bài đó trích dẫn (từ Semantic Scholar).

Sau đó viết báo cáo thống kê và đo hiệu năng. Dữ liệu này là nguyên liệu cho Milestone 2 (phân tích cấu trúc LaTeX) và Milestone 3 (ghép tham khảo bằng machine learning).

### 1.2 Đầu vào

- Một **dải arXiv ID liên tục** do giảng viên giao: **5000 ID** (chưa tính các version trong mỗi ID).
- Ví dụ định dạng ID: `2310.12345` (kiểu mới), `hep-th/9901001` (kiểu cũ, trước 2007, có dấu `/`).

### 1.3 Đầu ra (trên máy người chạy, **không nộp**)

| Thư mục | Nội dung |
|---|---|
| `data/` | Dữ liệu từng bài, từng version (mục 7) |
| `logs/run_log.jsonl` | Nhật ký mỗi bài (mục 7.7) |
| `logs/cooldowns.jsonl` | Mỗi lần crawler tự nghỉ vì lỗi mạng liên tiếp (mục 7.7.2) |
| `stats/` | Số liệu thống kê và đo hiệu năng cho báo cáo (mục 7.8 đến 7.10). Số đo hiệu năng nằm trong `stats/runs/run_XX/` (mỗi đoạn chạy một thư mục) và được gộp thành `stats/benchmark_total.json` |

### 1.4 Nộp bài

- Nộp trên Moodle: link repo code và link báo cáo (Jupyter Book trên GitHub Pages).
- Repo code chỉ chứa mã nguồn, README, requirements. **Không** chứa dữ liệu hay file chạy.
- Báo cáo ở một repo riêng, biểu đồ và bảng sinh bằng code khi dựng sách.
- Không nhận nộp trễ.

### 1.5 Tóm tắt yêu cầu của đề (cần đối chiếu với đề gốc)

- Lấy **mọi version** của mỗi bài, không chỉ v1.
- Chỉ giữ `.tex` và `.bib`; giữ nguyên các lệnh chèn ảnh trong `.tex` (`\includegraphics`, khối `figure`).
- Version không có TeX (chỉ có PDF...) vẫn phải có **bản ghi rỗng**, không được bỏ qua.
- Metadata bài (tên, tác giả, ngày đăng, ngày sửa, nơi đăng) và danh sách tham khảo từ Semantic Scholar. Bảng tham khảo cuối chỉ giữ tham khảo **có arXiv ID**; ID kiểu cũ giữ nguyên.
- Dùng `export.arxiv.org` (không dùng `arxiv.org` vì bị chặn 403), chờ tối thiểu 3 giây giữa 2 lần hỏi, mỗi lần một kết nối.
- Số liệu báo cáo: tỷ lệ thành công, dung lượng trung bình trước và sau khi bỏ ảnh, số tham khảo trung bình, thời gian, RAM tối đa và trung bình, đĩa tối đa và đĩa cuối.
- Đo hiệu năng cuối cùng trên Google Colab chế độ CPU. Hiệu năng được so với các nhóm khác.
- Cần xác nhận với giảng viên: xem mục 12.2.

---

## 2. Những gì đã làm

| Hạng mục | Trạng thái |
|---|---|
| Phân tích đề (3 milestone, chi tiết Milestone 1) | Xong |
| Crawler `milestone1_crawler.py` (hỏi arXiv theo lô, tải từng version, hỏi Semantic Scholar, checkpoint, log) | Viết xong, test offline, **chưa test mạng thật** |
| Sinh danh sách ID liên tục `make_ids.py` | Xong, có test |
| Thống kê `make_stats.py` | Xong, test offline |
| Đo hiệu năng `benchmark.py` (chạy từng đoạn, chịu được việc bị ngắt) và gộp bằng `merge_benchmarks.py` | Xong, test offline bằng lệnh giả; **chưa chạy với crawler thật** |
| Ghi thời gian cooldown (`logs/cooldowns.jsonl`) để báo cáo wall time đầy đủ và wall time trừ cooldown | Xong, test offline |
| Cách chờ khi 429/5xx, xử lý `Retry-After`, ETag yếu, giới hạn thời gian và log khi tải file (mục 5.7.1) | Xong, test trên server giả lập; **chưa kiểm chứng trên arXiv thật** |
| Xin API key Semantic Scholar (mức 1 request/giây) | Xong |
| Cấu trúc repo đề xuất | Có (mục 3), chưa tạo repo |
| README và `.gitignore` | Chưa viết |
| Báo cáo Jupyter Book | Chưa làm |
| Chạy thử 100 bài thật, chạy bản chính 5000 ID | Chưa làm |
| Đo hiệu năng thật trên Colab CPU | Chưa làm |

---

## 3. Cấu trúc repo

Dùng **hai repo riêng**.

### 3.1 Repo code

```
intro-ds-arxiv-crawler/
|-- README.md
|-- .gitignore
`-- src/
    |-- requirements.txt         (arxiv, requests, psutil)
    |-- milestone1_crawler.py    crawler chính
    |-- make_ids.py              sinh danh sách ID từ ID đầu đến ID cuối
    |-- make_stats.py            tính số liệu thống kê từ nhật ký
    |-- analyze_errors.py        cho biết vì sao các bài bị error (đọc logs/run_log.jsonl)
    |-- diagnose_download.py     tải thử một file bằng nhiều cách để tìm nguyên nhân khi tải bị đứt
    |-- benchmark.py             chạy crawler và đo thời gian, RAM, đĩa (mỗi đoạn một thư mục --out)
    `-- merge_benchmarks.py      gộp các đoạn đo thành một kết quả cho cả lần crawl
```

Các thư mục/file chỉ tồn tại trên máy chạy, **không commit** (ghi trong `.gitignore`):

```
data/   logs/   stats/   ids.txt   ids_part_*.txt   .venv/   __pycache__/   *.pyc   run.out   .env
```

| File | Vai trò |
|---|---|
| `milestone1_crawler.py` | Toàn bộ pipeline crawl. Chạy từ thư mục gốc của repo |
| `make_ids.py` | Từ ID đầu và ID cuối, sinh file danh sách ID (có thể chia nhỏ) |
| `make_stats.py` | Đọc `logs/run_log.jsonl`, tạo `stats/summary.json` và `stats/papers.csv` |
| `analyze_errors.py` | Đọc `logs/run_log.jsonl`, chia các bài lỗi theo nhóm nguyên nhân, cho xu hướng lỗi theo thời gian |
| `diagnose_download.py` | Tải cùng một file nguồn bằng 6 cách khác nhau (ví dụ header mặc định, `identity`, giữ kết nối, `urllib`, thử `Range`) rồi so sánh để tìm nguyên nhân khi tải bị đứt giữa chừng |
| `benchmark.py` | Bọc quanh lệnh bất kỳ, đo thời gian, RAM, đĩa của **một đoạn chạy**, tạo `benchmark.json` và `benchmark_samples.csv` trong thư mục `--out` (mục 7.10). Chịu được `Ctrl+C`, từ chối ghi đè kết quả cũ |
| `merge_benchmarks.py` | Gộp mọi thư mục `stats/runs/run_*` (và `logs/cooldowns.jsonl`) thành `stats/benchmark_total.json` và `stats/benchmark_samples_all.csv` (mục 7.10.1) |
| `requirements.txt` | Chỉ thư viện crawler cần: `arxiv`, `requests`, `psutil` |

### 3.2 Repo báo cáo (Jupyter Book)

Đề xuất theo Jupyter Book bản 2 (MyST). Hãy kiểm tra môn đang dùng bản nào.

```
intro-ds-report/
|-- README.md
|-- myst.yml                     cấu hình, mục lục
|-- requirements.txt             jupyter-book, pandas, plotly, ...
|-- index.md
|-- milestone1.ipynb             đọc file thống kê, vẽ biểu đồ bằng code
|-- stats/                       chỉ file thống kê nhỏ chép từ repo code
`-- .github/workflows/           tạo bằng: jupyter book init --gh-pages
```

---

## 4. Hướng dẫn chạy

Mọi lệnh giả định bạn **đứng ở thư mục gốc của repo code**. Nếu các file nằm chung một thư mục thì bỏ chữ `src/`.

### 4.1 Yêu cầu

- Python 3.10 trở lên (đã thử 3.12).
- Kết nối Internet ổn định, máy chạy được nhiều giờ.
- Dung lượng ổ đĩa trống đủ cho `data/` (chưa đo, xem mục 10.6).

### 4.2 Cài đặt

Windows PowerShell:
```
python -m venv .venv
.venv\Scripts\activate
pip install -r src/requirements.txt
```
Mac, Linux:
```
python3 -m venv .venv
source .venv/bin/activate
pip install -r src/requirements.txt
```
Nếu PowerShell chặn script: `Set-ExecutionPolicy -Scope Process Bypass`, rồi bật lại.

### 4.3 Biến môi trường

| Biến | Bắt buộc? | Ý nghĩa |
|---|---|---|
| `CONTACT_EMAIL` | Nên có | Email của bạn, đưa vào User-Agent để arXiv biết ai đang gọi |
| `S2_API_KEY` | Nên có | Key Semantic Scholar (mức 1 request/giây). Không có key vẫn chạy nhưng chậm hơn và dễ lỗi 429 |

Windows PowerShell: `$env:CONTACT_EMAIL="..."` và `$env:S2_API_KEY="..."`.
Mac, Linux: `export CONTACT_EMAIL="..."` và `export S2_API_KEY="..."`.

Lưu ý:
- Biến chỉ có hiệu lực trong cửa sổ terminal đó.
- Script **chỉ đọc biến môi trường, không đọc file `.env`**.
- Đặt biến **trước khi** chạy script (script chọn khoảng chờ Semantic Scholar lúc khởi động: 1,1 giây nếu có key, 3,2 giây nếu không).
- **Không** ghi key vào code, README hay lịch sử chat.

### 4.4 Sinh danh sách ID

```
python src/make_ids.py <ID đầu> <ID cuối> -o ids.txt
```
Ví dụ: `python src/make_ids.py 2310.00001 2310.05000 -o ids.txt` tạo 5000 dòng, **tính cả hai đầu**. Số ID in ra màn hình để đối chiếu với số giảng viên giao.

Quy tắc:
- Giữ số 0 đứng đầu: `2310.00001` (đúng), `2310.1` (sai).
- ID là ID gốc, không kèm version (`2310.00001`, không phải `2310.00001v2`).
- ID đầu và ID cuối phải **cùng tháng**. Nếu dải đi qua nhiều tháng, chạy mỗi tháng một lần rồi nối file.

### 4.5 Tham số các script

**`milestone1_crawler.py`**

| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `--id ID` | (không) | Một arXiv ID. Có thể lặp lại nhiều lần |
| `--ids-file FILE` | (không) | File văn bản, mỗi dòng một ID. Dòng bắt đầu bằng `#` là ghi chú |
| `--limit N` | (không) | Chỉ chạy N ID đầu (để thử) |
| `--discover-batch N` | 50 | Số ID hỏi arXiv mỗi lần (tối đa 100). Đặt 0 để hỏi lẻ từng bài |
| `--discover-only` | tắt | Chỉ hỏi thông tin các bài (tạo `meta.json`) rồi dừng, in tổng số version. Không tải source, không hỏi Semantic Scholar. Không dùng cùng `--discover-batch 0` |
| `--gap-from-start` | tắt | Tính khoảng chờ 3 giây từ lúc **bắt đầu** lần gọi arXiv trước (nhanh hơn). Mặc định tính từ lúc **kết thúc** (thận trọng). Chỉ bật khi đã xác nhận quy tắc với giảng viên (mục 10.9) |
| `--default-encoding` | tắt | Không gửi `Accept-Encoding: identity` (để thư viện dùng mặc định). Chỉ để **thử** khi nghi cách tải làm máy chủ cắt kết nối (mục 4.14) |

Bắt buộc có `--id` hoặc `--ids-file`.

**`make_ids.py`**: `start end [-o FILE] [--chunk N]`. Có `--chunk N` thì chia thành `ids_part_01.txt`, `ids_part_02.txt`... mỗi file tối đa N ID.

**`make_stats.py`**: `[--log logs/run_log.jsonl] [--ids-file ids.txt] [--out stats]`.

**`benchmark.py`**: `[--data-dir data] [--out stats] [--interval 1.0] [--disk-interval 5.0] -- <lệnh cần đo>`. Mỗi đoạn chạy dùng một `--out` riêng (ví dụ `stats/runs/run_01`); nếu thư mục `--out` đã có `benchmark_samples.csv` thì script từ chối chạy để không ghi đè số liệu cũ.

**`merge_benchmarks.py`**: `[--runs stats/runs] [--out stats] [--cooldown-log logs/cooldowns.jsonl]`. Gộp mọi thư mục `run_*` trong `--runs`.

### 4.6 Chạy thử 1 bài

```
python src/milestone1_crawler.py --id 1706.03762
```
Kết quả mong đợi:
```
[1/1] 1706.03762: done
Finished in ...s. Summary: {'done': 1}
```
Mở `data/1706-03762/`, kiểm tra: số thư mục `v...` khớp `n_versions` trong `meta.json`, file `.tex` còn dòng `\includegraphics`. Chạy lại đúng lệnh: phải ra `skipped`.

### 4.7 Chạy thử 100 bài

```
python src/milestone1_crawler.py --ids-file ids.txt --limit 100
python src/make_stats.py --ids-file ids.txt
```
Xem `logs/run_log.jsonl` và `stats/summary.json` để biết số version trung bình, số bài `not_found`, `error`. (Vì `--ids-file` là cả 5000 ID nên tỷ lệ thành công trong lần thử này sẽ thấp, không sao.)

### 4.7.1 Biết trước tổng số version (nên làm trước khi chạy dài)

```
python src/milestone1_crawler.py --ids-file ids.txt --discover-only
```
Hỏi arXiv theo lô cho cả dải ID (khoảng 100 lần hỏi, vài phút), tạo `meta.json`, rồi in tổng số version. Dùng số này để ước lượng thời gian chạy chính xác (mục 10.3). Lần chạy chính sau đó dùng lại các `meta.json` này.

### 4.8 Chạy bản chính

Cách khuyên dùng: chạy dưới `benchmark.py` để một lần chạy cho cả dữ liệu và số đo hiệu năng. Cần xóa `data/`, `logs/` và `stats/runs/` trước (sau khi sao lưu thứ cần giữ) để lần chạy tính từ đầu:
```
python src/benchmark.py --out stats/runs/run_01 -- python src/milestone1_crawler.py --ids-file ids.txt
```
Nếu bị ngắt giữa chừng, xem mục 4.8.1.
Hoặc chạy trực tiếp: `python src/milestone1_crawler.py --ids-file ids.txt`.

Chạy nền:
- Linux, Mac: `nohup python src/milestone1_crawler.py --ids-file ids.txt > run.out 2>&1 &`
- Windows: để cửa sổ chạy, tắt chế độ ngủ của máy (hoặc dùng WSL).

### 4.8.1 Đo hiệu năng khi chạy bị gián đoạn

Chạy 5000 ID mất nhiều giờ nên có thể bị ngắt (mất mạng, máy ngủ, `Ctrl+C`, crawler tự dừng sau 15 lỗi liên tiếp). Crawler tự chạy tiếp được (mục 5.6); việc đo thì làm theo từng **đoạn**, mỗi đoạn một thư mục `--out`, cuối cùng gộp lại:

```
# đoạn 1
python src/benchmark.py --out stats/runs/run_01 -- python src/milestone1_crawler.py --ids-file ids.txt
# bị ngắt: chạy tiếp, chỉ đổi tên thư mục --out
python src/benchmark.py --out stats/runs/run_02 -- python src/milestone1_crawler.py --ids-file ids.txt
# xong hết thì gộp
python src/merge_benchmarks.py
```

Quy tắc:
- Dùng **cùng** `--ids-file` và cùng thư mục `data/` ở mọi đoạn. Không chạy hai bản cùng lúc (arXiv chỉ cho một kết nối).
- Tên thư mục bắt đầu bằng `run_` và **đệm số 0** (`run_01` ... `run_10`), vì `merge_benchmarks.py` sắp xếp theo thứ tự chữ cái: `run_10` sẽ đứng trước `run_2`.
- `benchmark.py` từ chối chạy nếu `--out` đã có kết quả, nên không ghi đè nhầm. Luôn tăng số thứ tự cho đoạn mới.
- Bị ngắt thì cứ chạy đoạn tiếp theo; **không cần canh** để bấm `Ctrl+C` lúc crawler đang `cooling down`. Thời gian cooldown được ghi vào `logs/cooldowns.jsonl` và được tách ra khi gộp.
- `benchmark.py` vẫn ghi kết quả khi bị `Ctrl+C` (mẫu RAM và đĩa được ghi dần từng giây). Đoạn bị tắt máy đột ngột vẫn được gộp từ file mẫu.

Cách `merge_benchmarks.py` tính:

| Chỉ số | Cách tính |
|---|---|
| `total_wall_seconds` | Tổng thời gian các đoạn **thật sự chạy**. Khoảng nghỉ giữa các đoạn không tính |
| `total_cooldown_seconds`, `wall_seconds_excl_cooldown` | Tổng thời gian crawler tự ngủ (cooldown) nằm trong các đoạn (khớp theo thời điểm với `logs/cooldowns.jsonl`), và wall time sau khi trừ đi. Đề tính wall time từ đầu đến cuối nên **số chính là số đầy đủ**; số trừ cooldown là số phụ |
| `peak_rss_mb` | Lớn nhất qua mọi đoạn |
| `avg_rss_mb` | Trung bình theo mẫu (khoảng cách mẫu cố định nên xấp xỉ trung bình theo thời gian) |
| `peak_disk_mb`, `final_disk_mb` | Đĩa tích lũy qua các đoạn nên lấy lớn nhất, và giá trị cuối của đoạn cuối |

Chi phí "tìm bài" nằm gần hết ở `run_01`: `discover_many` hỏi arXiv theo lô 50 ID (khoảng 100 lần gọi cho 5000 ID, cách nhau ít nhất 3 giây); các đoạn sau đọc lại `meta.json`.

### 4.9 Theo dõi tiến độ

- Linux, Mac: `tail -f run.out` và `ls data/*/done.json | wc -l`
- Windows PowerShell: `(Get-ChildItem data -Recurse -Filter done.json).Count` và `Get-Content logs\run_log.jsonl -Tail 5`

Số `done.json` là số bài đã xong.

Màn hình còn in các dòng về tải file và thử lại (`[net error]`, `[retry]`, `[206]`, `[HTTP 429]`...); cách đọc xem mục 5.7.1. Muốn đếm lại sau, chạy kèm `| tee run.out` (Linux, Mac) hoặc `| Tee-Object run.out` (PowerShell).

### 4.10 Dừng và chạy tiếp

`Ctrl+C` để dừng. Chạy lại **đúng lệnh cũ**: bài đã xong được bỏ qua, version đã tải không tải lại (mục 5.6). Nếu đang đo hiệu năng, chạy tiếp với thư mục `run_XX` kế tiếp (mục 4.8.1).

### 4.11 Chạy theo từng phần

```
python src/make_ids.py 2310.00001 2310.05000 --chunk 500 -o ids.txt
python src/milestone1_crawler.py --ids-file ids_part_01.txt
python src/milestone1_crawler.py --ids-file ids_part_02.txt
```
Dữ liệu vẫn vào chung `data/`.

### 4.12 Tính số liệu sau khi chạy

```
python src/make_stats.py --ids-file ids.txt
```

### 4.13 Chạy trên Google Colab

Mỗi khối dưới đây là một ô (cell):
```
!git clone <link-repo-code>
%cd <ten-thu-muc-repo>
!pip install -r src/requirements.txt
```
```python
import os
from google.colab import userdata
os.environ["S2_API_KEY"] = userdata.get("S2_API_KEY")      # dùng Secrets của Colab
os.environ["CONTACT_EMAIL"] = "email-cua-ban@example.com"
```
```
!python src/make_ids.py 2310.00001 2310.05000 --chunk 500 -o ids.txt
!python src/milestone1_crawler.py --ids-file ids_part_01.txt
```
Lưu ý: phiên Colab có thể bị ngắt khi chạy lâu hoặc không hoạt động, dữ liệu trên đĩa tạm sẽ mất. Nếu chạy lâu hãy gắn Google Drive (`drive.mount`) và chạy trong thư mục trên Drive, chia phần 500 ID như trên.

### 4.14 Khi có bài bị `error`

Màn hình chỉ in chữ `error`; lý do nằm trong `logs/run_log.jsonl` (trường `error` và `where`). Để đọc nhanh nguyên nhân và xem số lỗi có tăng dần theo thời gian không:
```
python src/analyze_errors.py
```
Kết quả gồm: số dòng log theo trạng thái; các bài đang lỗi chia theo nhóm nguyên nhân (đĩa đầy, bị chặn 403, quá tải 429/5xx, mạng, lỗi file hệ thống, file nén hỏng, dữ liệu API lạ) kèm ví dụ và gợi ý; tỷ lệ lỗi theo từng đợt 100 lần xử lý; số bài lỗi lặp lại so với bài tự hết lỗi.

Xem nhanh không cần script (Windows PowerShell): `Select-String -Path logs\run_log.jsonl -Pattern '"status": "error"' | Select-Object -Last 5 | ForEach-Object { $_.Line }`

Sau khi xử lý nguyên nhân, chạy lại đúng lệnh cũ: chỉ các bài chưa xong được làm tiếp.

**Lỗi `IncompleteRead` / `Connection broken`** (kết nối đứt giữa lúc tải): thông báo này chỉ cho biết kết nối bị đóng trước khi nhận đủ file; chưa nói được phía nào cắt (mạng, máy chủ hoặc CDN, proxy hoặc phần mềm diệt virus, hay cách tải của code). Để tách từng khả năng:
1. **Dừng crawler** (arXiv chỉ cho một kết nối tại một thời điểm).
2. Chạy `python src/diagnose_download.py --id <ID bị lỗi>` (tự chọn version chưa tải xong; dùng `--version N` để chỉ định). Script tải cùng một file bằng 6 cách, cách nhau 3,5 giây, in kết quả từng cách và một dòng kết luận.
3. Cách làm tay bằng `curl` (Windows): `curl.exe -L -A "IntroDS-student-crawler/0.1 (mailto:<email>)" -o test.bin -w "%{http_code} %{size_download} bytes %{time_total}s\n" https://export.arxiv.org/src/<ID>v<N>`; so `size_download` với `Content-Length`.
4. Nếu kết luận là do header `identity`, chạy crawler với `--default-encoding`.
5. Nếu máy chủ trả `206` cho thử `Range`, có thể làm tính năng tải tiếp phần còn thiếu.

---

## 5. Luồng hoạt động

### 5.1 Sơ đồ tổng thể

```
make_ids.py                    milestone1_crawler.py                         make_stats.py
ID đầu, ID cuối  -> ids.txt -> [ hỏi arXiv theo lô ]                     
                               [ từng bài: tải version + hỏi S2 ] -> data/  -> stats/summary.json
                                          |                           logs/  -> stats/papers.csv
                                          +--> logs/run_log.jsonl ------^
benchmark.py: bọc quanh lệnh trên, đo thời gian / RAM / đĩa  ----------------> stats/runs/run_XX/ (mỗi đoạn một thư mục)
merge_benchmarks.py: gộp các đoạn + logs/cooldowns.jsonl -----------------> stats/benchmark_total.json
```

### 5.2 Luồng của chương trình chính (`main`)

```
1. Đọc tham số, gom danh sách ID (--id, --ids-file, --limit)
2. discover_many(ids): hỏi arXiv THEO LÔ -> dict {id: meta hoặc None}
3. Mở 1 luồng phụ (ThreadPoolExecutor, 1 worker)
4. Với từng ID (trong try/except, một bài lỗi không làm hỏng cả lần chạy):
      kết quả = process_paper(id, pool, metas)
      in "[i/n] id: kết quả"
5. In tổng kết: thời gian và số bài theo từng kết quả
```

### 5.3 Luồng xử lý một bài (`process_paper`)

```
có done.json?  --có-->  trả "skipped"
     |không
     v
lấy meta: (a) từ lô đã hỏi  (b) từ meta.json  (c) hỏi lẻ discover_paper
     |
     +-- meta = None --> ghi log not_found, trả "not_found"
     v
giao cho LUỒNG PHỤ: fetch_and_save_refs  (hỏi Semantic Scholar)
     |
luồng chính: với v = 1..n_versions:  download_version(v)
     |
chờ luồng phụ xong (lỗi ở luồng phụ nổ ra ở bước này)
     |
ghi done.json (tóm tắt) + thêm 1 dòng vào run_log.jsonl, trả "done"
```
`done.json` được ghi **cuối cùng**, nên chỉ khi mọi việc của bài xong mới coi là xong.

### 5.4 Hai việc chạy song song

arXiv và Semantic Scholar là hai server khác nhau nên chạy cùng lúc không vi phạm quy tắc của mỗi bên:

```
Luồng chính  : [tải v1]--3s--[tải v2]--3s--[tải v3]  ...  [chờ luồng phụ]  [ghi done]
Luồng phụ    : [hỏi Semantic Scholar]-----------------------> xong
```
Thời gian hỏi Semantic Scholar thường ngắn hơn thời gian tải các version, nên gần như bị "che" và không làm tăng tổng thời gian.

### 5.5 Nhận dạng file tải về (`extract_tex_bib`)

Nhận dạng bằng **nội dung** (không tin đuôi file), theo thứ tự:

```
bắt đầu bằng "%PDF"                    -> pdf        (bản ghi rỗng)
mở được như túi nén tar / tar.gz       -> tar        (chọn lọc .tex, .bib)
bắt đầu bằng 1f 8b (gzip), không phải túi:
      giải nén ra là PDF               -> pdf        (rỗng)
      có byte 0 (nhị phân)             -> other      (rỗng)
      còn lại                          -> gz_single  (lưu thành main.tex)
còn lại (ví dụ file Word)              -> other      (rỗng)
```
Trong túi nén: chỉ xét file thật; bỏ qua đường dẫn nguy hiểm (tuyệt đối, hoặc chứa `..`); chỉ ghi file đuôi `.tex`/`.bib` (không phân biệt hoa thường), giữ thư mục con. Nội dung file được **ghi nguyên văn**, không sửa gì.

### 5.6 Checkpoint (điểm lưu)

Chạy lại sau khi bị ngắt không mất công, nhờ 4 "dấu hiệu đã xong":

| Mức | Dấu hiệu | Hành động khi chạy lại |
|---|---|---|
| Tìm bài | `meta.json` | Không hỏi arXiv lại cho bài đó |
| Version | `v<n>/status.json` | Không tải lại version đó |
| Tham khảo | `references.json` và `references_all.json` đều có | Không hỏi Semantic Scholar lại |
| Cả bài | `done.json` | Bỏ qua bài (`skipped`) |

Mọi file JSON được ghi bằng **file tạm rồi đổi tên** (`write_json`), nên bị ngắt giữa lúc ghi cũng không để lại file dở dang.

### 5.7 Xử lý lỗi

| Tình huống | Hành vi |
|---|---|
| HTTP 404 | Coi là "không có", trả `None`, không thử lại |
| HTTP 403 | Dừng ngay bài đó, báo lỗi rõ ràng (bị chặn), không thử lại |
| HTTP 429, 500, 502, 503, 504 | Thử lại tối đa 4 lần sau lần đầu (5 lần nếu đang giữ từ 20 MB của file). Chờ đúng số giây `Retry-After` nếu server gửi; không thì chờ 15, 30, 60, 120 giây (bậc thứ 5: 240 giây), mỗi lần lệch ngẫu nhiên ±20%. `Retry-After` lớn hơn 15 phút thì bỏ bài đó ngay (báo lỗi, tính vào bộ đếm lỗi liên tiếp bên dưới) thay vì ngủ hàng giờ. Mỗi lần chờ in một dòng (mục 5.7.1) |
| Mạng đứt, quá 60 giây, **kết nối đứt giữa lúc đang tải** (`ProtocolError`, `IncompleteRead`), hoặc nhận thiếu byte so với `Content-Length` | Thử lại với kết nối mới, chờ 5, 10, 20, 40 giây. Với file nguồn: **giữ phần đã nhận và xin tải tiếp** (`Range`, kèm `If-Range` nếu có ETag mạnh) nếu máy chủ hỗ trợ; không hỗ trợ thì tải lại từ đầu. Lần thử đi xa hơn mọi lần trước không tính là thất bại, nên file lớn bị cắt nhiều lần vẫn tải xong (tối đa 60 lần gọi và có giới hạn thời gian cho một file, mục 5.7.1). Các lỗi này tính vào bộ đếm "bị chặn/mạng" bên dưới |
| Một lô hỏi arXiv bị lỗi | In thông báo, bỏ qua lô, các bài trong lô được hỏi lẻ sau |
| Lỗi trong một bài (kể cả lỗi từ Semantic Scholar) | Bắt ở `main`, ghi dòng `error` vào log (kèm `where`: dòng code nơi lỗi xảy ra), **chạy tiếp bài khác**. Bài không có `done.json` nên chạy lại sẽ làm tiếp; version đã tải xong không tải lại |
| Version chỉ có PDF/Word hoặc không có file | Tạo `status.json` với `status = "empty"` (bản ghi rỗng), vẫn tiếp tục |
| File nén hỏng hoặc bị cắt cụt (tải thiếu) | `kind = "corrupt"`, `status = "empty"` (bản ghi rỗng), **không** tính là `error`. Trước khi ghi file, code đọc hết luồng nén để kiểm tra, nên không để lại file dở. Muốn tải lại version đó thì xóa `v<n>/status.json` |
| Nhiều lỗi kiểu bị chặn, mạng, quá tải liên tiếp (HTTP 403, 429, 5xx, mất mạng, quá thời gian cho phép tải một file) | Cứ 5 lỗi liên tiếp thì nghỉ (5 phút, rồi 10 phút, tối đa 30 phút) và không gửi thêm yêu cầu; 15 lỗi liên tiếp thì dừng cả lần chạy và báo cách chạy tiếp. Một bài chạy xong (`done`) đặt lại bộ đếm. Mỗi lần nghỉ được ghi vào `logs/cooldowns.jsonl` (thời gian ngủ thực tế, kể cả khi bị `Ctrl+C` giữa chừng). Lỗi riêng của từng bài (ví dụ lỗi ghi file, hết dung lượng đĩa) không kích hoạt việc nghỉ |
| Semantic Scholar chưa có bài (404) | `n_refs` = `null`, bài vẫn `done` |

Lưu ý: `main` **trả mã thoát 0 ngay cả khi có bài `error`**. Hãy đọc dòng tổng kết hoặc chạy `make_stats.py` để biết số bài lỗi.

### 5.7.1 Giới hạn thời gian và các dòng log khi tải file

**Giới hạn thời gian cho một file:** `max(600 giây, dung lượng / 10 KB/s)`; không biết dung lượng thì 3600 giây. Ví dụ file 25 MB được tối đa 2500 giây. Được kiểm tra ở đầu mỗi lần thử và sau mỗi khối 64 KB, nên kết nối nhỏ giọt không treo vô hạn (`timeout=60` của `requests` chỉ áp cho từng lần đọc). Quá giới hạn thì báo `RuntimeError` bắt đầu bằng `Timeout:`, được tính vào bộ đếm lỗi mạng.

**Các dòng log trên màn hình:**

| Dòng | Ý nghĩa |
|---|---|
| `downloading <url>: 15.8/25.1 MB (255 KB/s)` | Tiến độ, in mỗi 60 giây khi đang tải file lớn |
| `[net error] ProtocolError on <url> -> wait 5s` | Kết nối bị cắt giữa lúc tải (máy chủ vẫn trả lời). **Chưa phải lỗi của bài**: nếu sau đó có `[retry]` rồi `done` thì bình thường |
| `[retry n] <url> (have X/Y MB, fails=k)` | Lần gọi thứ n+1. `n` là số lần gọi, **không phải số lần thất bại**. `have` là phần đang giữ; `fails` là số lần lỗi liên tiếp mà không đi xa thêm, về 0 khi nhận thêm được byte. Bài chỉ báo `error` khi `fails` vượt giới hạn |
| `[206] resumed at X MB` | Tải tiếp thành công từ vị trí đang có |
| `[200] server ignored Range, restarting from 0` | Máy chủ không cho tải tiếp (trả cả file): phần đã tải bị bỏ, tải lại từ đầu |
| `[HTTP 429]` hoặc `[HTTP 503]` ... `sleeping Ns before retry` | Máy chủ từ chối tạm thời; chờ rồi thử lại |
| `[HTTP ...] server asks to wait Ns: giving up on <url>` | `Retry-After` lớn hơn 15 phút: bỏ bài này, tính vào bộ đếm cooldown |

**Phần đã tải chỉ nằm trong RAM.** Bài báo `error` thì lần chạy sau tải lại từ byte 0 (chưa lưu tạm ra đĩa).

**Ví dụ từ log chạy thật** (bản trước khi đổi bảng chờ):
- Bài 2410.08225 (19.6 MB) có dòng `[retry 7]` nhưng chỉ là lần gọi thứ 8: 4 lần nhận dữ liệu (đến 12.6, 14.7, 17.8 MB rồi xong) và 4 lần bị 429. `fails` không vượt 2 vì mỗi lần nhận thêm dữ liệu thì về 0.
- Bài 2410.08159 (25.1 MB) bị cắt ở 15.8 MB, rồi nhận 503, 429, 503, 503, 503 liên tiếp trong khoảng 75 giây, hết lượt thử và báo `error`; chạy lại thì tải lại từ đầu. Bảng chờ mới (tổng khoảng 3 phút 45 giây, hoặc khoảng 7 phút 45 giây khi đang giữ từ 20 MB) nhằm xử lý trường hợp này; con số là điểm khởi đầu, cần hiệu chỉnh.

**Cách hiệu chỉnh bảng chờ:** sau khoảng 500 bài, đếm các đợt `[HTTP 429/503]` và xem chúng hết ở lần thử thứ mấy. Hết ở lần 1 đến 2 thì giữ hoặc rút ngắn; nhiều đợt tới lần thứ 4 trở đi thì kéo dài thêm một bậc; gần như không đợt nào hết trong vài phút thì máy chủ đang giới hạn mình, nên giảm tốc độ thay vì chờ lâu hơn.

### 5.8 Ví dụ một bài có 3 version

Bài `2310.12345`, v3 chỉ có PDF:
1. `discover_many` hỏi lô, nhận "có v3", ghi `meta.json`.
2. `process_paper` giao việc Semantic Scholar cho luồng phụ.
3. `download_version` tải v1, v2 (có TeX), v3 (PDF nên `empty`), mỗi lần cách nhau tối thiểu 3 giây.
4. Luồng phụ trả 45 tham khảo, 18 có arXiv ID, ghi `references_all.json` và `references.json`.
5. Ghi `done.json` và một dòng vào `run_log.jsonl`. Lần chạy sau bài này bị bỏ qua.

---

## 6. Các module và hàm

### 6.1 `milestone1_crawler.py`

Hằng số cấu hình ở đầu file:

| Tên | Giá trị | Ý nghĩa |
|---|---|---|
| `CONTACT` | biến môi trường `CONTACT_EMAIL` (mặc định `your-email@example.com`) | Email để đưa vào User-Agent |
| `USER_AGENT` | `IntroDS-student-crawler/0.1 (mailto:<CONTACT>)` | "Danh thiếp" gửi kèm mỗi yêu cầu HTTP |
| `S2_API_KEY` | biến môi trường `S2_API_KEY` (có thể rỗng) | Key Semantic Scholar |
| `DATA_DIR` | `data/` | Nơi lưu dữ liệu |
| `LOG_FILE` | `logs/run_log.jsonl` | Nhật ký |
| `ARXIV_THROTTLE` | `Throttle(3.0)` | Khoảng chờ tối thiểu giữa 2 lần gọi arXiv. Mặc định tính từ lúc lần gọi trước kết thúc; `--gap-from-start` đổi sang tính từ lúc bắt đầu |
| `S2_THROTTLE` | `Throttle(1.1)` nếu có key, `Throttle(3.2)` nếu không | Khoảng chờ tối thiểu giữa 2 lần gọi Semantic Scholar |
| `ARXIV_CLIENT` | `arxiv.Client(page_size=100, delay_seconds=3.0, num_retries=3)` | Đối tượng thư viện `arxiv` để hỏi thông tin bài |
| `ACCEPT_IDENTITY` | `True` (đổi bằng `--default-encoding`) | Có gửi `Accept-Encoding: identity` hay không |
| `NETWORK_ERRORS` | `(requests.RequestException, urllib3.exceptions.HTTPError)` | Các loại lỗi mạng được thử lại; gồm cả lỗi của `urllib3` vì dữ liệu được đọc thô |
| `MAX_ATTEMPTS` | `60` | Số lần gọi tối đa cho MỘT file (chặn vòng lặp vô tận khi mỗi lần đều tiến thêm một ít) |
| `MAX_FILE_SECONDS` | `600` | Thời gian tối đa (giây) cho một file nhỏ |
| `MIN_SPEED` | `10_000` | Tốc độ sàn (byte/giây): thời gian tối đa một file là `max(MAX_FILE_SECONDS, dung lượng / MIN_SPEED)` |
| `UNKNOWN_SIZE_SECONDS` | `3600` | Thời gian tối đa (giây) khi server không báo dung lượng |
| `PROGRESS_EVERY` | `60` | Số giây giữa 2 dòng báo tiến độ khi đang tải file lớn |
| `HTTP_WAITS` | `(15, 30, 60, 120, 240)` | Giây chờ sau lần 429/5xx thứ 1, 2, 3, 4, 5 liên tiếp (lệch ngẫu nhiên ±20%) khi server không gửi `Retry-After` |
| `BIG_PARTIAL` | `20_000_000` | Đang giữ từ ngần này byte của file thì được thêm một lần thử (bậc chờ 240 giây) |
| `RETRY_AFTER_MAX` | `900` | `Retry-After` lớn hơn (giây) thì bỏ bài đó, để cơ chế cooldown xử lý |
| `S2_FIELDS` | `title,references.title,references.authors,references.publicationDate,references.externalIds,references.paperId` | Các trường xin Semantic Scholar (không có dấu cách sau dấu phẩy) |

Các hàm:

| Hàm | Làm gì | Kiểu trả về |
|---|---|---|
| `Throttle(min_gap, from_start=False)` | "Người gác cổng". `wait()` ngủ cho đủ `min_gap` giây tính từ lúc lần gọi trước **kết thúc** (hoặc **bắt đầu** nếu `from_start=True`); `mark()` ghi nhận lần gọi vừa kết thúc. Ngoài ra đo số lần gọi, tổng thời gian chờ, tổng thời gian gọi mạng; `summary()` trả các số này | Đối tượng; `wait()`, `mark()` trả `None`; `summary()` trả `dict` |
| `fetch_bytes(url, throttle, headers=None, retries=4, raw=True)` | Tải một URL bằng `requests.Session` (giữ kết nối mở giữa các lần gọi), có chờ lịch sự và thử lại khi lỗi tạm thời. `raw=True`: đọc byte thô đúng như server gửi (cho file nguồn arXiv); `raw=False`: để thư viện tự giải nén (cho JSON của Semantic Scholar). Sau mỗi lỗi mạng, bỏ session cũ và mở kết nối mới cho lần thử sau; với `raw=True` còn tải tiếp phần còn thiếu bằng `Range` (xem `_fetch_bytes`). Khi báo lỗi, gắn thuộc tính `crawler_url` vào ngoại lệ | `bytes`; hoặc `None` nếu HTTP 404. HTTP 403 gây `RuntimeError`. Quá thời gian cho một file gây `RuntimeError` bắt đầu bằng `Timeout:` (được tính vào bộ đếm lỗi mạng). Lỗi khác sau khi hết lượt thử gây ngoại lệ của `requests` hoặc `urllib3` (`ProtocolError`, `IncompleteRead`...). Nhận thiếu byte so với `Content-Length` (chế độ `raw`) cũng bị coi là lỗi và thử lại |
| `_retry_after(value, default)` | Đọc giá trị header `Retry-After` (không cắt ngắn), không đọc được thì dùng `default` | `float` (giây) |
| `_limit(total)` | Thời gian tối đa cho một file: `max(MAX_FILE_SECONDS, total / MIN_SPEED)`; không biết dung lượng (`None`) thì `UNKNOWN_SIZE_SECONDS` | `float` (giây) |
| `_session_for(throttle)` | Trả về `requests.Session` riêng của một "người gác cổng" (tạo lần đầu, dùng lại sau đó) | `requests.Session` |
| `_drop_session(throttle)` | Đóng và bỏ session (kết nối) hiện tại của một "người gác cổng" | `None` |
| `_parse_content_range(value)` | Đọc header `Content-Range`, ví dụ `bytes 1048576-5000000/5000001` | `(start, end, total)` hoặc `None` nếu không đọc được |
| `_fetch_bytes(url, throttle, headers, retries, raw)` | Vòng tải thật. Giữ dữ liệu nhận được trong bộ đệm; khi đứt giữa chừng và máy chủ có `Accept-Ranges: bytes` thì lần sau xin tiếp `Range: bytes=<đã có>-` kèm `If-Range` (ETag mạnh hoặc Last-Modified; ETag yếu `W/...` thì không gửi vì theo RFC 7233 máy chủ sẽ bỏ qua Range). Kiểm tra `Content-Range` khớp vị trí và tổng dung lượng; máy chủ trả 200 (bỏ qua Range), 416 hoặc `Content-Range` sai thì bỏ phần đã có và tải lại từ đầu. "Tiến triển" được tính theo mức xa nhất từng đạt. Giới hạn thời gian (`_limit`) được kiểm tra ở đầu mỗi lần thử và sau mỗi khối 64 KB. Với 429/5xx: chờ theo `HTTP_WAITS` hoặc đúng `Retry-After` (quá `RETRY_AFTER_MAX` thì bỏ bài). Các mã khác 200/206 được đóng `resp` ngay. Mọi lần chờ, thử lại, tải tiếp đều in một dòng (mục 5.7.1). Lỗi vĩnh viễn (400, 401...) báo ngay, không thử lại | `bytes` hoặc `None` |
| `throttle_report(wall_seconds)` | In và ghi số liệu chờ đợi / gọi mạng của lần chạy (kèm `cooldown_seconds`) vào `logs/throttle_runs.jsonl` | `None` |
| `sleep_cooldown(seconds)` | Ngủ để hạ nhiệt khi gặp nhiều lỗi mạng liên tiếp và ghi thời gian ngủ **thực tế** (kể cả khi bị `Ctrl+C`) vào `logs/cooldowns.jsonl`; cộng vào biến `COOLDOWN_TOTAL` | `None` |
| `_safe_rel(name)` | Chuẩn hóa đường dẫn trong file nén, loại đường dẫn nguy hiểm | `str`, hoặc `None` nếu nguy hiểm |
| `_save_tar(tar, out_dir)` | Duyệt túi nén, ghi các `.tex`/`.bib` ra đĩa | `(files: list[str], kept: int, everything: int)` |
| `extract_tex_bib(data, out_dir)` | Nhận dạng loại file tải về và giải nén chọn lọc | `(kind: str, files: list[str], bytes_after: int, bytes_all: int)` |
| `safe_dirname(paper_id)` | Đổi ID thành tên thư mục: `.` và `/` thành `-` | `str` |
| `split_versioned_id(entry_id)` | Tách `http://arxiv.org/abs/2310.12345v4` | `(base_id: str, n_versions: int)`; không có đuôi version thì `n_versions = 1` |
| `write_json(path, obj)` | Ghi JSON (UTF-8, thụt lề 2) qua file tạm rồi đổi tên | `None` |
| `read_json(path)` | Đọc file JSON | Đối tượng Python |
| `append_log(rec)` | Thêm một dòng JSON vào `LOG_FILE` | `None` |
| `rss_mb()` | RAM tiến trình hiện tại (MB), cần `psutil` | `float`, hoặc `None` nếu chưa cài `psutil` |
| `meta_from_result(r, base_id, n_versions, discover_seconds)` | Đóng gói kết quả của thư viện `arxiv` thành dict | `dict` (định dạng ở 7.2) |
| `discover_paper(paper_id)` | Hỏi arXiv cho **một** bài (dự phòng) | `dict`, hoặc `None` nếu không có bài |
| `discover_many(ids, batch_size=50)` | Hỏi arXiv **theo lô**; bỏ qua bài đã `done.json`, đọc lại `meta.json` đã có | `dict[str, dict or None]`: `id -> meta`, hoặc `None` nếu arXiv không có bài. ID **vắng mặt** trong dict = lô bị lỗi, sẽ hỏi lẻ sau |
| `download_version(paper_id, version, paper_dir)` | Tải và giải nén một version; có `status.json` thì trả luôn kết quả cũ | `dict` (định dạng ở 7.3) |
| `fetch_and_save_refs(paper_id, paper_dir)` | Hỏi Semantic Scholar, ghi 2 file tham khảo | `(n_refs: int or None, n_refs_with_arxiv_id: int or None)`; `(None, None)` nếu Semantic Scholar không có bài |
| `process_paper(paper_id, pool, metas=None)` | Xử lý trọn một bài (mục 5.3) | `str`: `"skipped"`, `"not_found"` hoặc `"done"` |
| `main()` | Đọc tham số, chạy toàn bộ | `None` |

### 6.2 `make_ids.py`

| Hàm | Làm gì | Kiểu trả về |
|---|---|---|
| `parse(arxiv_id)` | Tách ID thành phần đầu và số thứ tự, ví dụ `2310.00001` thành `("2310.", "00001")` | `(prefix: str, num: str)`; `ValueError` nếu ID sai định dạng |
| `build_range(start, end)` | Sinh danh sách ID từ `start` đến `end` (tính cả hai đầu), giữ số 0 đứng đầu | `list[str]`; `ValueError` nếu khác tháng, khác số chữ số, hoặc đầu lớn hơn cuối |
| `main()` | Giao diện dòng lệnh | `None` |

Hỗ trợ ID kiểu mới (`YYMM.NNNNN`, cũng nhận 4 chữ số cho giai đoạn trước 2015) và kiểu cũ (`hep-th/9901001`).

### 6.3 `make_stats.py`

| Hàm | Làm gì | Kiểu trả về |
|---|---|---|
| `load_last_per_id(log_path)` | Đọc nhật ký, chỉ giữ dòng **cuối** của mỗi ID | `dict[str, dict]` |
| `avg(values)` | Trung bình làm tròn 3 chữ số, bỏ qua `None` | `float`, hoặc `None` nếu không có giá trị |
| `main()` | Tính số liệu, ghi `stats/summary.json` và `stats/papers.csv` | `None` |

### 6.4 `benchmark.py`

| Hàm | Làm gì | Kiểu trả về |
|---|---|---|
| `dir_size(path)` | Tổng dung lượng các file trong thư mục (byte) | `int` |
| `tree_rss(proc)` | RAM của tiến trình và các tiến trình con (byte) | `int` |
| `count_done(data_dir)` | Đếm số bài đã có `done.json` (để biết đoạn bắt đầu từ đâu) | `int` |
| `main()` | Từ chối chạy nếu `--out` đã có kết quả; ghi `benchmark_start.json` ngay khi bắt đầu; chạy lệnh sau `--` như tiến trình con, lấy mẫu RAM và đĩa và ghi **dần** vào `benchmark_samples.csv` mỗi giây; bắt `Ctrl+C` để vẫn ghi `benchmark.json` (`interrupted = true`) | Thoát với đúng mã thoát của lệnh được đo |

### 6.4.1 `merge_benchmarks.py`

| Hàm | Làm gì | Kiểu trả về |
|---|---|---|
| `read_run(run_dir)` | Đọc một đoạn: file mẫu (bỏ qua dòng ghi dở), `benchmark.json` nếu có, thời điểm bắt đầu (từ `benchmark.json` hoặc `benchmark_start.json`) | `dict`, hoặc `None` nếu không có mẫu |
| `read_cooldowns(path)` | Đọc `logs/cooldowns.jsonl` | `list[(start_epoch, seconds)]` |
| `cooldown_in_run(cooldowns, run)` | Tổng giây cooldown có thời điểm bắt đầu nằm trong khoảng chạy của đoạn | `float`, hoặc `None` nếu không biết đoạn chạy lúc nào |
| `main()` | Gộp các đoạn `run_*` theo thứ tự tên, ghi `benchmark_total.json` và `benchmark_samples_all.csv` (thời gian nối liền mạch giữa các đoạn) | `None` |

### 6.5 `analyze_errors.py`

| Hàm | Làm gì | Kiểu trả về |
|---|---|---|
| `categorize(message)` | Xếp một thông báo lỗi vào nhóm nguyên nhân theo thứ tự ưu tiên (đĩa đầy, 403, 429/5xx, mạng, file hệ thống, file nén hỏng, dữ liệu API lạ, bộ nhớ, khác) | `str` |
| `hint_for(name)` | Gợi ý cách xử lý cho một nhóm | `str` |
| `shorten(message, width)` | Rút gọn thông báo để in | `str` |
| `main()` | Đọc `logs/run_log.jsonl`, in 4 phần: trạng thái, nhóm nguyên nhân, xu hướng theo đợt, lỗi lặp lại | `None` |

Tham số: `--log` (mặc định `logs/run_log.jsonl`), `--bucket` (số lần xử lý mỗi đợt khi xét xu hướng, mặc định 100), `--show` (số ví dụ mỗi nhóm, mặc định 3).

### 6.6 `diagnose_download.py`

Tải cùng một file nguồn bằng 6 cách, cách nhau `--gap` giây (mặc định 3,5; bắt buộc từ 3 trở lên với arxiv.org): (1) `requests`, kết nối mới, header mặc định (như `curl`); (2) kết nối mới, `identity`, đọc thô (cách crawler đang dùng); (3) và (4) cùng một session dùng lại hai lần (kiểm tra việc giữ kết nối); (5) `urllib` của Python; (6) thử xin 1 KB bằng `Range`. In trạng thái, số byte nhận được so với `Content-Length`, thời gian, lỗi (nếu có), một số header của máy chủ, và một dòng kết luận. Ngoài ra in: các số byte nhận được trước khi đứt (và nhận xét nếu **tất cả** đều là bội số của 1 MiB, dấu hiệu bên gửi cắt theo từng khối 1 MiB), và nhà cấp chứng chỉ TLS của kết nối (phần mềm diệt virus quét HTTPS thường chèn chứng chỉ của chính nó; script cảnh báo nếu tên giống phần mềm bảo mật hoặc proxy).

| Tham số | Ý nghĩa |
|---|---|
| `--id` | arXiv ID gốc |
| `--version` | Số version; mặc định chọn version đầu tiên chưa có `status.json` |
| `--url` | URL đầy đủ, thay cho `--id` |
| `--data-dir` | Thư mục dữ liệu (mặc định `data`) |
| `--gap` | Giây nghỉ giữa 2 lần tải |

Hàm chính: `pick_version(paper_id, data_dir)` trả `int`; `attempt(name, fn)` chạy một cách tải và trả `dict` kết quả; `main()`.

---

## 7. Dữ liệu và định dạng JSON

Tất cả JSON dùng UTF-8, `ensure_ascii=False` (giữ nguyên chữ có dấu). File `.json` thụt lề 2 khoảng trắng; `run_log.jsonl` mỗi dòng một bản ghi gọn.

Các ví dụ dưới đây lấy từ lần chạy thử bằng **mạng giả**, nên giá trị chỉ mang tính minh họa. Định dạng (tên trường, kiểu) là thật.

### 7.1 Cây thư mục `data/`

```
data/
`-- 2310-00002/                    (ID 2310.00002; dấu "." và "/" đổi thành "-")
    |-- meta.json                  thông tin bài
    |-- references.json            tham khảo CÓ arXiv ID
    |-- references_all.json        TẤT CẢ tham khảo
    |-- done.json                  dấu "đã xong" + tóm tắt
    |-- v1/
    |   |-- main.tex               nội dung nguyên văn, giữ thư mục con (vd sections/intro.tex)
    |   |-- refs.bib
    |   `-- status.json
    |-- v2/ ...
    `-- v3/
        `-- status.json            (chỉ có PDF: không có .tex/.bib, vẫn có status.json)
```
ID kiểu cũ `hep-th/9901001` có thư mục `hep-th-9901001`. Bài `not_found` có thể để lại thư mục rỗng.

### 7.2 `meta.json`

```json
{
  "arxiv_id": "2310.00002",
  "n_versions": 3,
  "title": "Example paper 2310.00002",
  "authors": ["An Nguyen", "Binh Tran"],
  "published": "2023-10-02T08:30:00+00:00",
  "updated": "2023-11-15T09:00:00+00:00",
  "journal_ref": null,
  "discover_seconds": 0.12
}
```

| Trường | Kiểu | Ý nghĩa |
|---|---|---|
| `arxiv_id` | string | ID gốc, không kèm version (kiểu cũ giữ dấu `/`) |
| `n_versions` | int | Số version = số trong đuôi `vN` của version mới nhất |
| `title` | string | Tên bài |
| `authors` | list[string] | Tên tác giả theo thứ tự |
| `published` | string (ISO 8601, UTC) | Ngày nộp lần đầu |
| `updated` | string (ISO 8601, UTC) | Ngày cập nhật của **version mới nhất** (chưa có ngày sửa từng version, xem mục 13) |
| `journal_ref` | string hoặc null | Nơi đăng nếu tác giả có khai báo |
| `discover_seconds` | float hoặc null | Thời gian "tìm bài". Nếu hỏi theo lô: thời gian của cả lô **chia đều** cho các bài trong lô |

### 7.3 `v<n>/status.json`

```json
{
  "version": 1,
  "kind": "tar",
  "status": "ok",
  "files": ["main.tex", "refs.bib"],
  "bytes_downloaded": 357,
  "bytes_before": 170574,
  "bytes_after": 20574,
  "seconds": 0.001
}
```
Một version chỉ có PDF (bản ghi rỗng):
```json
{
  "version": 3,
  "kind": "pdf",
  "status": "empty",
  "files": [],
  "bytes_downloaded": 13,
  "bytes_before": 13,
  "bytes_after": 0,
  "seconds": 0.0
}
```

| Trường | Kiểu | Ý nghĩa |
|---|---|---|
| `version` | int | Số version |
| `kind` | string | `"tar"`, `"gz_single"`, `"pdf"`, `"other"`, `"corrupt"` hoặc `"not_found"` (mục 8) |
| `status` | string | `"ok"` nếu có ít nhất một file giữ lại, `"empty"` nếu không |
| `files` | list[string] | Đường dẫn tương đối các file đã giữ (dấu `/`) |
| `bytes_downloaded` | int | Dung lượng file **nén** tải về |
| `bytes_before` | int | Dung lượng **giải nén đầy đủ** của mọi file (gồm ảnh) = "trước khi bỏ ảnh" |
| `bytes_after` | int | Dung lượng các file `.tex`/`.bib` giữ lại = "sau khi bỏ ảnh" |
| `seconds` | float | Thời gian xử lý version này (gồm cả thời gian chờ lịch sự). Giá trị cũ nếu lấy từ checkpoint |

Ba loại dung lượng được tách riêng vì so file nén với file giải nén sẽ cho kết quả sai (đã gặp lỗi này lúc kiểm thử, xem mục 17.2). `bytes_before` và `bytes_after` cùng là dung lượng chưa nén nên so sánh được với nhau.

### 7.4 File `.tex` và `.bib`

Ghi **nguyên văn** như tải về, không sửa. Các lệnh `\includegraphics` và khối `figure` còn nguyên (Milestone 2 cần). File `.gz` đơn được lưu thành `main.tex`.

### 7.5 `references_all.json` và `references.json`

Cả hai là **danh sách** các đối tượng cùng định dạng, theo thứ tự Semantic Scholar trả về. `references_all.json` có tất cả, `references.json` chỉ giữ phần tử có `arxiv_id`.

```json
[
  {
    "s2_id": "abc123",
    "arxiv_id": "1706.03762",
    "title": "Attention Is All You Need",
    "authors": ["A. Vaswani"],
    "date": "2017-06-12"
  },
  {
    "s2_id": "def456",
    "arxiv_id": null,
    "title": "A Textbook",
    "authors": ["C. Author"],
    "date": null
  }
]
```

| Trường | Kiểu | Ý nghĩa |
|---|---|---|
| `s2_id` | string hoặc null | Mã bài trên Semantic Scholar |
| `arxiv_id` | string hoặc null | arXiv ID của bài được trích dẫn (kiểu cũ giữ dấu `/`). `null` nếu không có |
| `title` | string hoặc null | Tên bài được trích dẫn |
| `authors` | list[string] | Tên tác giả (có thể rỗng) |
| `date` | string hoặc null | Ngày công bố `YYYY-MM-DD` do Semantic Scholar cung cấp (đây là ngày công bố, không nhất thiết là ngày nộp lên arXiv) |

Lưu ý: tham khảo được lấy **một lần cho cả bài**, không tách theo version (mục 12).

### 7.6 `done.json`

Tóm tắt một bài, cũng chính là dòng `done` trong nhật ký (mục 7.7).

```json
{
  "id": "2310.00002",
  "status": "done",
  "n_versions": 3,
  "versions_with_tex": 2,
  "bytes_downloaded": 727,
  "bytes_before": 341161,
  "bytes_after": 41148,
  "n_refs": 2,
  "n_refs_with_arxiv_id": 1,
  "discover_seconds": 0.12,
  "seconds": 41.7,
  "rss_mb": 52.3
}
```

| Trường | Kiểu | Ý nghĩa |
|---|---|---|
| `id` | string | arXiv ID gốc |
| `status` | string | Luôn là `"done"` |
| `n_versions` | int | Số version |
| `versions_with_tex` | int | Số version có ít nhất một `.tex`/`.bib` |
| `bytes_downloaded`, `bytes_before`, `bytes_after` | int | Tổng của các version (định nghĩa như 7.3) |
| `n_refs` | int hoặc null | Tổng số tham khảo; `null` nếu Semantic Scholar không có bài |
| `n_refs_with_arxiv_id` | int hoặc null | Số tham khảo có arXiv ID |
| `discover_seconds` | float hoặc null | Như 7.2 |
| `seconds` | float | Tổng thời gian xử lý bài trong lần chạy này |
| `rss_mb` | float hoặc null | RAM của chương trình lúc xong bài; `null` nếu chưa cài `psutil` |

### 7.7 `logs/run_log.jsonl`

Mỗi dòng là một JSON, thêm vào cuối file (file không bị ghi đè). Có 3 dạng:

```json
{"id": "2310.00001", "status": "done", "n_versions": 1, "versions_with_tex": 1, "bytes_downloaded": 357, "bytes_before": 170574, "bytes_after": 20574, "n_refs": 2, "n_refs_with_arxiv_id": 1, "discover_seconds": 0.12, "seconds": 3.4, "rss_mb": 48.0}
{"id": "2310.00099", "status": "not_found"}
{"id": "2310.00003", "status": "error", "error": "ProtocolError('Connection broken: IncompleteRead(1048576 bytes read, 909298 more expected)')", "where": "milestone1_crawler.py:153 in fetch_bytes (raised in response.py:930 in _error_catcher)", "url": "https://export.arxiv.org/src/2310.00003v2"}
```
- `done`: giống `done.json`.
- `not_found`: arXiv không có bài này.
- `error`: có lỗi; trường `error` là mô tả lỗi, `where` là dòng code của dự án nơi lỗi xảy ra (kèm dòng trong thư viện nếu lỗi bắt nguồn từ đó), `url` là địa chỉ đang tải khi lỗi (có thể `null`). Dùng các trường này khi báo lỗi cho người hỗ trợ.

Bài bị bỏ qua (`skipped`) **không** ghi dòng mới. Một bài có thể có nhiều dòng (lỗi lần trước, thành công lần sau). `make_stats.py` chỉ lấy dòng cuối của mỗi ID.

### 7.7.1 `logs/throttle_runs.jsonl`

Mỗi lần chạy `milestone1_crawler.py` (kể cả `--discover-only`) thêm **một dòng** khi kết thúc, cho biết thời gian thật sự đi vào chờ đợi hay vào gọi mạng. Ví dụ (giá trị **minh họa**, không phải số đo):

```json
{"time": "2026-10-20 01:03:41", "wall_seconds": 5400.0, "cooldown_seconds": 0.0, "gap_from_start": false, "arxiv": {"requests": 1500, "min_gap": 3.0, "waited_seconds": 4500.0, "busy_seconds": 900.0, "avg_request_seconds": 0.6}, "semantic_scholar": {"requests": 1000, "min_gap": 1.1, "waited_seconds": 300.0, "busy_seconds": 400.0, "avg_request_seconds": 0.4}}
```

| Trường | Ý nghĩa |
|---|---|
| `time` | Giờ kết thúc lần chạy |
| `wall_seconds` | Thời gian chạy của lần này |
| `cooldown_seconds` | Tổng thời gian ngủ vì cooldown trong lần chạy này |
| `gap_from_start` | `true` nếu bật `--gap-from-start` |
| `arxiv` / `semantic_scholar` | Số liệu của từng "người gác cổng": `requests` (số lần gọi, tính cả lần thử lại), `min_gap`, `waited_seconds` (tổng thời gian ngủ để chờ), `busy_seconds` (tổng thời gian đang gọi mạng), `avg_request_seconds` (trung bình mỗi lần gọi, hay còn gọi là thời gian phản hồi `r` ở mục 10.9) |

Các bộ đếm tính **theo từng lần chạy** (mỗi lần chạy đếm lại từ 0), nên chạy theo nhiều phần thì mỗi phần một dòng. Dòng này chỉ được ghi khi lần chạy kết thúc bình thường; bị `Ctrl+C` thì không có dòng, và cooldown của lần đó chỉ còn trong `logs/cooldowns.jsonl`.

### 7.7.2 `logs/cooldowns.jsonl`

Mỗi lần crawler tự nghỉ (cooldown) thêm **một dòng** ngay sau khi nghỉ xong, hoặc khi bị ngắt giữa lúc nghỉ. Ví dụ (giá trị **minh họa**):

```json
{"start_epoch": 1792922774.4, "seconds": 300.0}
```

| Trường | Ý nghĩa |
|---|---|
| `start_epoch` | Thời điểm bắt đầu nghỉ (giây Unix) |
| `seconds` | Thời gian ngủ **thực tế** |

`merge_benchmarks.py` dùng các dòng này, khớp theo thời điểm với từng đoạn đo, để tính tổng cooldown. Chỉ tính cooldown (nghỉ sau 5 lỗi mạng liên tiếp); các lần chờ giữa các lần thử lại và chờ giữ khoảng cách 3 giây không tính. File ghi thêm vào cuối, không bị xóa khi chạy lại; xóa cùng `logs/` khi muốn đo từ đầu.

### 7.8 `stats/summary.json`

Do `make_stats.py` tạo. Ví dụ (từ dữ liệu giả):
```json
{
  "papers_requested": 6,
  "papers_done": 3,
  "papers_not_found": 1,
  "papers_error": 1,
  "papers_never_logged": 1,
  "paper_success_rate": 0.5,
  "versions_total": 5,
  "versions_with_tex": 4,
  "version_tex_rate": 0.8,
  "avg_bytes_downloaded_per_paper": 480,
  "avg_bytes_before_per_paper": 227436,
  "avg_bytes_after_per_paper": 27432,
  "size_reduction_pct": 87.94,
  "avg_refs_per_paper": 2,
  "avg_refs_with_arxiv_id_per_paper": 1,
  "papers_with_ref_metadata": 2,
  "ref_metadata_rate": 0.6667,
  "avg_seconds_per_paper": 0.002,
  "avg_discover_seconds": 0.0,
  "max_rss_mb_seen_in_log": 34.9
}
```

| Trường | Cách tính |
|---|---|
| `papers_requested` | Số ID trong `--ids-file` (`null` nếu không đưa file) |
| `papers_done` / `papers_not_found` / `papers_error` | Số ID có dòng log **cuối** là `done` / `not_found` / `error` |
| `papers_never_logged` | Số ID trong file nhưng chưa từng được chạy |
| `paper_success_rate` | `papers_done / papers_requested` (4 chữ số thập phân). `done` nghĩa là bài chạy xong, **không** có nghĩa là có TeX |
| `versions_total` | Tổng `n_versions` của các bài `done` |
| `versions_with_tex` | Tổng `versions_with_tex` |
| `version_tex_rate` | `versions_with_tex / versions_total` |
| `avg_bytes_*_per_paper` | Trung bình trên các bài `done` (làm tròn thành số nguyên) |
| `size_reduction_pct` | `100 x (1 - tổng bytes_after / tổng bytes_before)`. Cả hai chưa nén |
| `avg_refs_per_paper`, `avg_refs_with_arxiv_id_per_paper` | Trung bình trên các bài có dữ liệu tham khảo |
| `papers_with_ref_metadata` | Số bài `done` có `n_refs` khác `null` |
| `ref_metadata_rate` | `papers_with_ref_metadata / papers_done`. **Cách định nghĩa này cần xác nhận với giảng viên** (mục 12.2) |
| `avg_seconds_per_paper` | Trung bình `seconds` của các bài `done`, kể cả thời gian chờ lịch sự |
| `avg_discover_seconds` | Trung bình `discover_seconds` (đã chia đều theo lô) |
| `max_rss_mb_seen_in_log` | RAM lớn nhất ghi trong nhật ký (chỉ là mẫu tại thời điểm xong mỗi bài; số đo chính thức dùng `stats/benchmark_total.json`) |

### 7.9 `stats/papers.csv`

Mỗi ID một dòng (dòng log cuối), sắp theo ID. Cột:

```
id,status,n_versions,versions_with_tex,bytes_downloaded,bytes_before,bytes_after,n_refs,n_refs_with_arxiv_id,discover_seconds,seconds,rss_mb
2310.00001,done,1,1,357,170574,20574,2,1,0.0,0.002,34.8
2310.00003,error,,,,,,,,,,
2310.00099,not_found,,,,,,,,,,
```
Bài `error` và `not_found` có các cột số để trống. `n_refs` trống ở bài `done` nghĩa là Semantic Scholar không có dữ liệu. File dùng để vẽ biểu đồ trong báo cáo (đọc bằng `pandas.read_csv`).

### 7.10 `stats/runs/run_XX/`: `benchmark.json`, `benchmark_samples.csv`, `benchmark_start.json`

Mỗi đoạn chạy có một thư mục riêng (mục 4.8.1). Nếu chạy một mạch thì chỉ có `run_01`.

```json
{
  "command": ["python", "src/milestone1_crawler.py", "--ids-file", "ids.txt"],
  "return_code": 0,
  "interrupted": false,
  "wall_seconds": 2.52,
  "started_at": 1792922773.2,
  "ended_at": 1792922775.7,
  "peak_rss_mb": 8.9,
  "avg_rss_mb": 8.2,
  "peak_disk_mb": 0.1,
  "final_disk_mb": 0.1,
  "n_samples": 5,
  "done_papers_at_start": 0,
  "done_papers_at_end": 3
}
```

| Trường | Ý nghĩa |
|---|---|
| `command` | Lệnh đã đo |
| `return_code` | Mã thoát của lệnh được đo |
| `interrupted` | `true` nếu đoạn bị `Ctrl+C` |
| `wall_seconds` | Thời gian chạy của **đoạn này** (đồng hồ treo tường), từ lúc bắt đầu đến lúc kết thúc |
| `started_at`, `ended_at` | Thời điểm bắt đầu và kết thúc đoạn (giây Unix); dùng để khớp với `logs/cooldowns.jsonl` |
| `peak_rss_mb` | RAM lớn nhất (tiến trình và tiến trình con), lấy mẫu mỗi `--interval` giây |
| `avg_rss_mb` | Trung bình các mẫu RAM |
| `peak_disk_mb` | Dung lượng lớn nhất của thư mục `data/` (đo mỗi `--disk-interval` giây và một lần cuối) |
| `final_disk_mb` | Dung lượng `data/` sau khi chạy xong |
| `n_samples` | Số mẫu RAM đã lấy |
| `done_papers_at_start`, `done_papers_at_end` | Số bài đã có `done.json` lúc bắt đầu và lúc kết thúc đoạn |

`benchmark_samples.csv` có 3 cột `t_seconds,rss_mb,disk_mb`, mỗi dòng một mẫu theo thời gian, dùng để vẽ biểu đồ RAM và đĩa theo thời gian. Các mẫu được ghi dần từng giây, nên đoạn bị tắt máy đột ngột vẫn còn số liệu đến lúc đó. `benchmark_start.json` (`{"started_at": ...}`) được ghi ngay khi đoạn bắt đầu để biết đoạn chạy lúc nào kể cả khi không có `benchmark.json`.

### 7.10.1 `stats/benchmark_total.json` và `stats/benchmark_samples_all.csv`

Do `merge_benchmarks.py` tạo. Ví dụ (giá trị **minh họa** từ lần thử bằng lệnh giả, không phải số đo thật):

```json
{
  "segments": 2,
  "total_wall_seconds": 7.52,
  "total_wall_hours": 0.0,
  "total_cooldown_seconds": 4.8,
  "wall_seconds_excl_cooldown": 2.72,
  "peak_rss_mb": 35.3,
  "avg_rss_mb": 31.2,
  "peak_disk_mb": 0.0,
  "final_disk_mb": 0.0,
  "per_segment": [
    {"name": "run_01", "wall_seconds": 4.53, "peak_rss_mb": 35.2, "done_papers_at_start": 0, "done_papers_at_end": 0, "cooldown_seconds": 2.0, "ended": "finished"},
    {"name": "run_02", "wall_seconds": 2.99, "peak_rss_mb": 35.3, "done_papers_at_start": 0, "done_papers_at_end": 0, "cooldown_seconds": 2.8, "ended": "Ctrl+C"}
  ]
}
```

| Trường | Ý nghĩa |
|---|---|
| `segments` | Số đoạn đã gộp |
| `total_wall_seconds`, `total_wall_hours` | Tổng thời gian các đoạn thật sự chạy (không tính khoảng nghỉ giữa các đoạn) |
| `total_cooldown_seconds`, `wall_seconds_excl_cooldown` | Tổng cooldown và wall time sau khi trừ. `null` nếu có đoạn không biết giờ bắt đầu |
| `peak_rss_mb`, `avg_rss_mb` | RAM lớn nhất qua mọi đoạn; trung bình theo mẫu |
| `peak_disk_mb`, `final_disk_mb` | Đĩa lớn nhất qua mọi đoạn; giá trị cuối của đoạn cuối |
| `per_segment` | Từng đoạn: thời gian, RAM tối đa, số bài xong lúc đầu và cuối, cooldown, cách kết thúc (`finished`, `Ctrl+C`, hoặc `no benchmark.json (hard stop)` nếu bị tắt đột ngột) |

`benchmark_samples_all.csv` có 3 cột `t_seconds,rss_mb,disk_mb`; thời gian nối liền mạch qua các đoạn, dùng để vẽ một biểu đồ cho cả lần crawl.

### 7.11 `ids.txt`

Mỗi dòng một ID gốc. Dòng trống bị bỏ qua, dòng bắt đầu bằng `#` là ghi chú.
```
2310.00001
2310.00002
```

### 7.12 Gợi ý ánh xạ sang bảng cuối của đề

Milestone 1 chưa phải xuất bảng Parquet; các bảng này sẽ dựng ở các milestone sau. Dữ liệu hiện có đủ để dựng:

| Bảng (theo đề) | Nguồn dữ liệu |
|---|---|
| `papers` | `meta.json` (ngày nộp lần đầu = `published`; **chưa có** danh sách ngày sửa từng version) |
| `references` | `references.json` (bài trích dẫn = ID của thư mục; bài được trích dẫn = `arxiv_id`) |

Hãy đối chiếu tên cột chính xác với đề.

---

## 8. Bảng trạng thái và ý nghĩa

### 8.1 Kết quả xử lý một bài

| Giá trị | Nơi xuất hiện | Ý nghĩa |
|---|---|---|
| `done` | `done.json`, log, kết quả `process_paper` | Chạy xong. Không bảo đảm có TeX; xem `versions_with_tex` |
| `skipped` | Chỉ in ra màn hình | Bài đã có `done.json`, bỏ qua |
| `not_found` | Log, màn hình | arXiv không có bài này |
| `error` | Log, màn hình | Có lỗi; chạy lại sẽ làm tiếp |

### 8.2 Một version

| Trường | Giá trị | Ý nghĩa |
|---|---|---|
| `status` | `ok` | Có ít nhất một `.tex`/`.bib` được giữ |
| `status` | `empty` | Không có file giữ lại (bản ghi rỗng) |
| `kind` | `tar` | Túi nén (tar hoặc tar.gz) |
| `kind` | `gz_single` | File gzip đơn, lưu thành `main.tex` |
| `kind` | `pdf` | PDF (kể cả PDF nén gzip) |
| `kind` | `other` | Loại khác (ví dụ file Word) hoặc dữ liệu nhị phân không nhận dạng được |
| `kind` | `corrupt` | File nén bị hỏng hoặc bị cắt cụt (tải thiếu); ghi bản ghi rỗng |
| `kind` | `not_found` | Server trả 404 cho version này |

Một túi nén không chứa `.tex`/`.bib` nào (ví dụ chỉ có ảnh) có `kind = "tar"` nhưng `status = "empty"`.

---

## 9. Quy tắc lịch sự và giới hạn tốc độ

| Bên | Quy tắc | Cách code tuân thủ |
|---|---|---|
| arXiv (`export.arxiv.org`) | Chờ tối thiểu 3 giây giữa 2 lần hỏi, mỗi lần một kết nối. Không dùng `arxiv.org` để tải tự động (bị chặn 403) | Một `Throttle(3.0)` dùng cho cả hỏi thông tin lẫn tải source, chỉ dùng ở luồng chính. Tải từ `export.arxiv.org`. Khoảng chờ tính từ lúc lần gọi trước kết thúc (mặc định) |
| Semantic Scholar | Có key: 1 request/giây. Không key: dùng chung giới hạn với mọi người dùng ẩn danh, dễ gặp 429 | `Throttle(1.1)` có key, `Throttle(3.2)` không key, chỉ dùng ở luồng phụ. Key gửi trong header `x-api-key` |
| Cả hai | Khai báo rõ chương trình | `User-Agent` kèm email liên hệ |

Quy tắc riêng:
- Theo điều khoản sử dụng API của arXiv (https://info.arxiv.org/help/api/tou.html): giới hạn 1 yêu cầu mỗi 3 giây và một kết nối tại một thời điểm áp dụng cho **tất cả máy bạn kiểm soát gộp lại**, và không được tăng số máy để vượt giới hạn. Vì vậy **không chia dải ID cho nhiều máy chạy cùng lúc**.
- Không mở nhiều kết nối đến arXiv để chạy nhanh hơn.
- Bị chặn (403) hoặc gặp 429 liên tục thì dừng và chờ, không rút ngắn khoảng chờ.
- Key Semantic Scholar là bí mật cá nhân: không commit, không đưa vào tài liệu hay tin nhắn.

---

## 10. Đánh giá tốc độ

> **Quan trọng:** tất cả con số trong các mục 10.1 đến 10.6 là **ước lượng tính toán** từ quy tắc giới hạn tốc độ, **chưa phải số đo thực tế**. Số đo thật sẽ điền vào mục 10.8 sau khi chạy `benchmark.py`.

### 10.1 Điều gì quyết định tốc độ

- arXiv chỉ cho phép 1 lần hỏi mỗi 3 giây, tức tối đa 20 lần/phút, 1.200 lần/giờ. Đây là **giới hạn cứng** và là điểm nghẽn chính của cả pipeline.
- Việc giải nén, ghi file, đọc JSON chỉ tốn mili giây so với 3 giây chờ, nên gần như không ảnh hưởng tổng thời gian.
- `Throttle` mặc định đo khoảng 3 giây tính từ lúc lần gọi trước **kết thúc** (cách thư viện `arxiv` chính thức làm), nên mỗi vòng thực tế = 3 giây + thời gian phản hồi `r` của server. Các số ở bảng 10.3 là **mức sàn** (chưa cộng `r`); mục 10.9 cho biết cộng thêm bao nhiêu. Đây là cách làm thận trọng; có tùy chọn `--gap-from-start` nhưng mặc định tắt.
- Hiệu năng được chấm so với các nhóm khác, nhưng không có cách hợp lệ nào để hỏi arXiv nhanh hơn. Chỗ có thể cải thiện là **giảm số lần hỏi** và **không làm lãng phí tài nguyên**.

### 10.2 Công thức ước lượng

Gọi `N` = số bài (5000), `v` = số version trung bình mỗi bài.

```
Số lần hỏi arXiv:
    hỏi thông tin theo lô (50 ID/lần):  ceil(N / 50) + N x v   = 100 + 5000 x v
    hỏi từng bài (không lô):            N x (1 + v)            = 5000 x (1 + v)

Thời gian chờ tối thiểu  ~=  số lần hỏi x 3 giây   (chưa cộng thời gian phản hồi)

Semantic Scholar (luồng phụ, chạy song song với arXiv):
    có key (1,1 giây/lần):    5000 x 1,1  = 5.500 giây   ~= 1 giờ 32 phút
    không key (3,2 giây/lần): 5000 x 3,2  = 16.000 giây  ~= 4 giờ 27 phút
```

### 10.3 Bảng ước lượng cho 5000 ID

Số version trung bình `v` **chưa biết** (tùy dải ID). Bảng cho 4 kịch bản:

| `v` | Hỏi theo lô: số lần hỏi | Hỏi theo lô: thời gian chờ | Hỏi từng bài: số lần hỏi | Hỏi từng bài: thời gian chờ |
|---|---|---|---|---|
| 1 | 5.100 | 4 giờ 15 phút | 10.000 | 8 giờ 20 phút |
| 1,5 | 7.600 | 6 giờ 20 phút | 12.500 | 10 giờ 25 phút |
| 2 | 10.100 | 8 giờ 25 phút | 15.000 | 12 giờ 30 phút |
| 3 | 15.100 | 12 giờ 35 phút | 20.000 | 16 giờ 40 phút |

Hỏi theo lô tiết kiệm `5000 - 100 = 4.900` lần hỏi, tức khoảng 4.900 x 3 giây = 14.700 giây, **khoảng 4 giờ 5 phút**, bất kể `v`.

**Biết chính xác `v` trước khi chạy dài:** dùng chế độ chỉ hỏi thông tin.
```
python src/milestone1_crawler.py --ids-file ids.txt --discover-only
```
Lệnh này hỏi arXiv theo lô (khoảng 100 lần, vài phút với 5000 ID), tạo `meta.json` cho từng bài, in ra dòng như:
```
Discovery finished: 4987/5000 papers have meta.json (the rest: not found or failed), 9421 versions in total
```
Lấy tổng số version cộng với số bài là ra số lần hỏi còn lại, nhân 3 giây (và cộng thêm thời gian phản hồi) để có ước lượng sát. Khi chạy bản chính sau đó, các `meta.json` này được dùng lại, không hỏi lại arXiv.

### 10.4 Vai trò của Semantic Scholar

Việc hỏi Semantic Scholar chạy ở luồng phụ, song song với việc tải arXiv. Với mỗi bài, thời gian hỏi Semantic Scholar (khoảng 1,1 giây cộng thời gian phản hồi nếu có key) thường ngắn hơn thời gian tải các version (mỗi version tối thiểu 3 giây), nên **gần như không cộng thêm vào tổng thời gian**. Khi chưa có key (3,2 giây mỗi lần) và gặp nhiều lỗi 429, luồng phụ có thể chậm hơn luồng chính và kéo dài tổng thời gian. Đây là lý do nên dùng key.

### 10.5 Các tối ưu đã làm

| Tối ưu | Tác dụng | Mức độ kiểm chứng |
|---|---|---|
| Hỏi thông tin arXiv theo lô 50 ID | Giảm 4.900 lần hỏi, khoảng 4 giờ 5 phút | Tính toán; logic đã test bằng mạng giả; chưa đo thật |
| Hai luồng song song (arXiv và Semantic Scholar) | Che thời gian hỏi Semantic Scholar (khoảng 1 giờ 32 phút nếu có key) | Tính toán; chưa đo thật |
| Giải nén thẳng từ bộ nhớ, không lưu file nén ra đĩa | Giảm dung lượng đĩa tối đa; đổi lại giữ tạm một file tải về trong RAM (mỗi lần một file) | Thiết kế; chưa đo |
| Chỉ ghi `.tex` và `.bib` | Giảm dung lượng đĩa cuối cùng | Đúng theo đề; mức giảm chưa đo trên dữ liệu thật |
| Checkpoint nhiều mức | Chạy lại không làm lại việc đã xong | Đã test bằng mạng giả |
| Giữ kết nối mở (`requests.Session`, keep-alive) | Bớt thời gian thiết lập kết nối (TCP, TLS) ở mỗi lần gọi, tức giảm `r` | Kiểm chứng trên server HTTP cục bộ (10 lần gọi chỉ mở 1 kết nối); chưa đo trên arXiv thật |
| Đo đạc trong `Throttle` + `logs/throttle_runs.jsonl` | Cho biết `r` thật và thời gian chờ thật, làm cơ sở quyết định tối ưu tiếp | Đã test |

Không làm (vì vi phạm quy tắc hoặc rủi ro): mở nhiều kết nối đến arXiv, rút ngắn khoảng chờ 3 giây.

### 10.6 Dung lượng đĩa và RAM

- **Đĩa:** `final_disk_mb` ~= `avg_bytes_after_per_paper x 5000`. Chưa đo trên dữ liệu thật. Cách ước lượng: chạy 100 bài đầu, đọc `avg_bytes_after_per_paper` trong `summary.json`, nhân 50. Kiểm tra dung lượng trống trước khi chạy dài.
- **RAM:** chương trình giữ trong bộ nhớ một file tải về tại một thời điểm và giải nén từ đó. Chưa đo trên dữ liệu thật; số đo chính thức lấy từ `stats/benchmark_total.json` (`peak_rss_mb`, `avg_rss_mb`).

### 10.7 Cách đo (quy trình chuẩn)

Bảng đối chiếu chỉ số báo cáo với nơi lấy số:

| Chỉ số báo cáo | Lấy ở đâu |
|---|---|
| Tổng thời gian chạy | `stats/benchmark_total.json`, `total_wall_seconds` (tổng các đoạn; số chính theo đề) |
| Thời gian chạy trừ cooldown (số phụ) | `stats/benchmark_total.json`, `wall_seconds_excl_cooldown` và `total_cooldown_seconds` |
| Thời gian trung bình mỗi bài | `stats/summary.json`, `avg_seconds_per_paper` (hoặc `wall_seconds / papers_done`) |
| Thời gian "tìm bài" | `stats/summary.json`, `avg_discover_seconds` (trung bình theo lô); hoặc tự đo riêng bằng `--discover-only` |
| Thời gian phản hồi trung bình mỗi lần gọi arXiv, tổng thời gian chờ, tổng thời gian gọi mạng | `logs/throttle_runs.jsonl`, trường `arxiv` (`avg_request_seconds`, `waited_seconds`, `busy_seconds`) |
| RAM tối đa, RAM trung bình | `stats/benchmark_total.json`, `peak_rss_mb`, `avg_rss_mb` |
| Đĩa tối đa, đĩa cuối | `stats/benchmark_total.json`, `peak_disk_mb`, `final_disk_mb` |
| Tỷ lệ thành công | `stats/summary.json`, `paper_success_rate`, `version_tex_rate` |
| Dung lượng trước và sau khi bỏ ảnh | `stats/summary.json`, `avg_bytes_before_per_paper`, `avg_bytes_after_per_paper`, `size_reduction_pct` |
| Số tham khảo trung bình | `stats/summary.json`, `avg_refs_per_paper`, `avg_refs_with_arxiv_id_per_paper` |

Quy trình đo:
1. Xóa `data/`, `logs/` và `stats/runs/` (để checkpoint không bỏ qua bài nào, và `benchmark.py` không từ chối vì thư mục đã có kết quả).
2. Chạy `python src/benchmark.py --out stats/runs/run_01 -- python src/milestone1_crawler.py --ids-file <file ID>`. Nếu bị ngắt, chạy tiếp với `run_02`, `run_03`... (mục 4.8.1).
3. Chạy `python src/merge_benchmarks.py`, rồi `python src/make_stats.py --ids-file <file ID>`.
4. Ghi lại cấu hình: số CPU, RAM của máy, phiên bản Python, ngày giờ chạy, loại mạng, có dùng API key không.
5. Đo trên Google Colab chế độ CPU theo yêu cầu của đề. Không chạy việc nặng khác cùng lúc.
6. Chạy lặp ít nhất 3 lần trên tập mẫu nhỏ nếu muốn có số đo đáng tin; mỗi lần phải xóa `data/`, `logs/` và `stats/runs/`.

Lưu ý khi diễn giải:
- Nếu lần crawl bị ngắt rồi chạy tiếp, số đo là **tổng các đoạn**, không phải một lần chạy liền mạch. Nói rõ trong báo cáo lần crawl gồm bao nhiêu đoạn (`segments`), hoặc đo thêm một tập mẫu chạy liền một mạch.
- Cooldown (nghỉ sau 5 lỗi mạng liên tiếp) nằm trong wall time. Báo cáo cả hai số: `total_wall_seconds` (đầy đủ, số chính vì đề tính từ đầu đến cuối) và `wall_seconds_excl_cooldown` (số phụ), kèm cách tính.
- Bài đang chạy dở lúc bị ngắt, hoặc bài lỗi được thử lại, có `seconds` thấp hơn thực tế vì các version đã tải được bỏ qua. Chỉ ảnh hưởng số ít bài nhưng nên nêu.
- Các lần chờ giữa các lần thử lại (retry) không được ghi riêng như cooldown; chúng vẫn nằm trong wall time.
- Đo đĩa chỉ tính thư mục `data/` (tổng dung lượng file, không tính phần dư của ổ đĩa như lệnh `du`).
- RAM lấy mẫu mỗi giây nên có thể bỏ lỡ đỉnh rất ngắn.
- Nếu giảng viên cho phép đo trên tập con (mục 12.2), hãy ghi rõ cỡ mẫu và cách chọn.

### 10.8 Kết quả đo thực tế (điền sau)

| Chỉ số | Mẫu 100 bài | Toàn bộ dải ID (Colab CPU) | Ghi chú |
|---|---|---|---|
| Số bài chạy xong / được giao | (điền sau) | (điền sau) | |
| Số version trung bình mỗi bài | (điền sau) | (điền sau) | |
| Tổng thời gian chạy | (điền sau) | (điền sau) | |
| Số đoạn chạy (nếu bị ngắt) / tổng cooldown | (điền sau) | (điền sau) | |
| Thời gian trung bình mỗi bài | (điền sau) | (điền sau) | |
| Thời gian "tìm bài" | (điền sau) | (điền sau) | |
| RAM tối đa / trung bình | (điền sau) | (điền sau) | |
| Đĩa tối đa / cuối | (điền sau) | (điền sau) | |
| Tỷ lệ thành công (bài, version có TeX) | (điền sau) | (điền sau) | |
| Dung lượng trung bình trước / sau khi bỏ ảnh | (điền sau) | (điền sau) | |
| Số tham khảo trung bình (tất cả / có arXiv ID) | (điền sau) | (điền sau) | |
| So với ước lượng ở 10.3 | (điền sau) | (điền sau) | Giải thích nếu lệch nhiều |

### 10.9 Đánh giá mức độ tối ưu và các hướng nhanh hơn

**Kết luận ngắn.** Trong phạm vi quy tắc của arXiv, cấu trúc hiện tại đã gần mức tối ưu: thời gian chủ yếu là thời gian chờ bắt buộc, không có khoảng trống lãng phí giữa các bài, thông tin bài được hỏi theo lô, việc hỏi Semantic Scholar chạy song song. Chỗ còn cải thiện được là **thời gian phản hồi `r` của mỗi lần gọi bị cộng thêm vào khoảng chờ 3 giây** (vì khoảng chờ tính từ lúc lần gọi trước kết thúc). Mức ảnh hưởng chưa biết cho tới khi đo: xem `avg_request_seconds` trong `logs/throttle_runs.jsonl` sau khi chạy 100 bài đầu.

**Giới hạn cứng, không thể vượt.** Điều khoản của arXiv: không quá 1 yêu cầu mỗi 3 giây, một kết nối tại một thời điểm, áp dụng cho tất cả máy bạn kiểm soát gộp lại. Do đó thời gian tối thiểu = số lần hỏi x 3 giây (mức sàn ở mục 10.3).

**Chi phí thêm do `r`** (ví dụ 5000 ID, `v` = 2, tức 10.100 lần hỏi, mức sàn 8 giờ 25 phút). Đây là phép tính với các giá trị `r` giả định, `r` thật phụ thuộc mạng, vị trí máy và kích thước file:

| `r` trung bình mỗi lần | Thời gian thêm | Tổng | Chậm hơn mức sàn |
|---|---|---|---|
| 0,5 giây | 1 giờ 24 phút | 9 giờ 49 phút | +17% |
| 1 giây | 2 giờ 48 phút | 11 giờ 13 phút | +33% |
| 2 giây | 5 giờ 37 phút | 14 giờ 2 phút | +67% |

**Mô phỏng thu nhỏ để kiểm tra logic** (thời gian thu nhỏ 10 lần: 3 giây thành 0,3 giây, `r` = 1 giây thành 0,1 giây; 60 bài, 93 lần hỏi arXiv gồm 3 lô và 90 version). Đây **không phải số đo thật**, chỉ chứng minh logic của code khớp với phép tính:

| Cấu hình | Thời gian mô phỏng | So với mức sàn (27,9) |
|---|---|---|
| Mặc định (chờ từ lúc kết thúc), Semantic Scholar nhanh | 36,95 | +32% (khớp `r`/3 = 33%) |
| `--gap-from-start`, Semantic Scholar nhanh | 27,72 | khoảng 0% |
| Mặc định, Semantic Scholar chậm (phản hồi tương đương 5 giây thật) | 38,70 | +39% (tăng thêm khoảng 5% so với dòng đầu) |

Dòng cuối cho thấy luồng Semantic Scholar chỉ "được che" khi nó nhanh hơn thời gian tải các version của bài đó. Khi nó chậm (hay bị 429), luồng chính phải chờ ở cuối mỗi bài và tổng thời gian tăng nhẹ.

**Các hướng nhanh hơn, hợp lệ:**

| Hướng | Tác dụng ước tính | Ghi chú | Trạng thái |
|---|---|---|---|
| Giữ kết nối mở (keep-alive) | Giảm phần thiết lập kết nối trong `r` | An toàn, vẫn một kết nối. Mức giảm phụ thuộc mạng (xa máy chủ thì nhiều hơn) | Đã làm, chưa đo trên arXiv thật |
| Chạy ở nơi mạng nhanh và gần máy chủ (ví dụ Colab) | Giảm `r` | So `avg_request_seconds` giữa nơi chạy | Cần đo |
| `--gap-from-start` (tính 3 giây từ lúc bắt đầu lần gọi trước) | Bỏ `r` khỏi vòng chờ, tối đa bằng mức chậm hơn sàn ở bảng trên | Đúng với câu chữ "không quá 1 yêu cầu mỗi 3 giây", nhưng mạnh hơn cách thư viện `arxiv` chính thức làm, và đề có thể hiểu "giữa 2 lần hỏi" khác. Mặc định tắt, chỉ bật khi giảng viên xác nhận | Đã làm (tùy chọn) |
| Lô 100 ID thay vì 50 (`--discover-batch 100`) | Bớt 50 lần hỏi, khoảng 2,5 phút (dưới 1%) | Không đáng kể | Có sẵn tham số |
| Dùng bộ metadata offline (ví dụ bản chụp arXiv trên Kaggle) thay cho bước hỏi thông tin | Bớt khoảng 100 lần hỏi, khoảng 5 đến 6 phút; có thể có ngày từng version | Phải tải bộ dữ liệu lớn, có thể thiếu bài mới, cần kiểm tra các trường dữ liệu trước | Chưa làm, lợi nhỏ |
| Gối đầu Semantic Scholar giữa các bài (không chờ ở cuối mỗi bài) | Khoảng 5% khi Semantic Scholar chậm | Chỉ có ích khi hay bị 429 | Chưa làm |
| Tự tăng khoảng chờ sau khi gặp 429 | Không tăng tốc, tăng độ bền | Tránh thử lại dồn dập khi arXiv bận | Chưa làm |

**Không nên làm** (vi phạm quy tắc hoặc rủi ro cao):
- Mở nhiều kết nối đến arXiv cùng lúc.
- Chạy nhiều máy cùng lúc, kể cả chia dải ID cho các bạn trong nhóm: điều khoản nói rõ không được tăng số máy để vượt giới hạn.
- Dùng `arxiv.org` hoặc máy chủ khác để né giới hạn, hoặc rút ngắn khoảng chờ dưới 3 giây.
- Tải dữ liệu hàng loạt (bulk) để thay việc tải từng version: theo hiểu biết của người soạn, bộ này chỉ có phiên bản mới nhất nên không đủ mọi version (chưa kiểm tra lại).

**Quy trình quyết định.**
1. Chạy 100 bài đầu, mở `logs/throttle_runs.jsonl`, đọc `avg_request_seconds` của `arxiv`.
2. Nếu `r` nhỏ hơn khoảng 0,3 giây: hầu như không còn gì đáng tối ưu.
3. Nếu `r` từ 1 giây trở lên: thử đổi nơi chạy (ví dụ Colab) và so sánh; hỏi giảng viên về `--gap-from-start`.
4. Đưa số trước và sau mỗi thay đổi vào báo cáo.


---

## 11. Kiểm thử

### 11.1 Đã kiểm thử (offline, bằng dữ liệu và mạng giả, trên Linux, Python 3.12)

| Nhóm | Nội dung đã kiểm tra | Kết quả |
|---|---|---|
| Nhận dạng và giải nén | `.tar.gz` (giữ `main.tex`, `refs.bib`, `sections/intro.tex`; bỏ ảnh; bỏ đường dẫn `../evil.tex` và `/abs.tex`); `.tar` không nén; `.gz` đơn thành `main.tex`; PDF; PDF bị nén gzip; dữ liệu giống file Word; túi nén chỉ có ảnh | Đúng như mong đợi. Dòng `\includegraphics` còn nguyên |
| Đếm dung lượng | `bytes_after` chỉ tính `.tex`/`.bib`, `bytes_before` tính mọi file (ví dụ 1.100 và 51.100); PDF thì `after = 0` | Đúng |
| Hàm ID | `split_versioned_id` (ID mới, ID cũ có `/`, không có đuôi version), `safe_dirname` | Đúng |
| Pipeline với mạng giả | Bài 3 version (v2 trả 404, v3 là PDF), tham khảo 3 trong đó 1 có arXiv ID; bài không tồn tại; bài Semantic Scholar không có dữ liệu; bài lỗi Semantic Scholar | Kết quả `done`, `not_found`, `done` với `n_refs = null`, `error` đúng như thiết kế |
| Checkpoint | Chạy lại lần hai | Bài đã xong bị bỏ qua, không tải lại, không hỏi lại Semantic Scholar |
| Hỏi theo lô | 122 ID chia lô 50, 50, 22; giả lập một lô lỗi; bài không tồn tại; ID kiểu cũ; chạy lại | Đúng số lô; lô lỗi chuyển sang 50 lần hỏi lẻ; chạy lại chỉ hỏi lại 1 bài `not_found` |
| `--discover-only` | 20 ID, 1 ID không tồn tại | 1 lần hỏi, không tải gì, không ghi log từng bài (chỉ ghi `throttle_runs.jsonl`), in đúng tổng version (21); chạy lại chỉ hỏi lại bài chưa có `meta.json` |
| `fetch_bytes` với server HTTP cục bộ | 10 lần gọi liên tiếp chỉ mở 1 kết nối (keep-alive); 404 trả `None`; 403 báo `RuntimeError`; 503 và 429 có `Retry-After` thì thử lại sau khoảng 1 giây rồi thành công; hết lượt thử báo `HTTPError`; 400 báo ngay; theo chuyển hướng (redirect); server gửi `Content-Encoding: x-gzip` vẫn nhận **byte thô**; header `x-api-key` và User-Agent được gửi; mất kết nối thì báo lỗi sau khi thử lại | Đúng |
| `Throttle` | Hai chế độ tính khoảng chờ; đếm số lần gọi, thời gian chờ, thời gian gọi mạng | Đúng; chế độ từ lúc bắt đầu nhanh hơn như kỳ vọng |
| Mô phỏng thu nhỏ 10 lần toàn bộ pipeline | 60 bài, đúng 93 lần hỏi arXiv như tính toán; các số ở mục 10.9 | Đúng (không phải số đo thật) |
| Xử lý lỗi | File nén bị cắt cụt ở 30%, 60%, 95%, byte bị hỏng giữa file, `.gz` đơn bị cắt: đều thành `corrupt` và không ghi file nào; lỗi ghi đĩa (hết dung lượng) vẫn báo lỗi thật; nghỉ sau lỗi mạng thứ 5 và 10 rồi dừng ở lỗi thứ 15; lỗi riêng của từng bài không kích hoạt nghỉ; một bài thành công đặt lại bộ đếm; log có trường `where` | Đúng |
| `analyze_errors.py` | Log giả 606 dòng có tỷ lệ lỗi tăng dần và nhiều nguyên nhân | Phân nhóm, xu hướng và lỗi lặp lại đúng |
| Kết nối đứt giữa lúc tải | Server gửi `Content-Length` 3 MB nhưng đóng kết nối sau 1,5 MB: tải lại thành công ở lần thứ 3 (chờ 5 và 10 giây); luôn đứt thì báo lỗi mạng sau khi hết lượt thử. Đã tái hiện đúng thông báo `IncompleteRead` trong log của người dùng với code cũ | Đúng |
| Chế độ tải `raw`, `--default-encoding`, URL trong lỗi | `raw=False` trả JSON đã giải nén, `raw=True` giữ nguyên byte gzip; `--default-encoding` bỏ header `identity`; lỗi có `crawler_url` và log có trường `url`; sau lỗi mạng mở kết nối mới | Đúng |
| Tải tiếp khi đứt (`Range`) | File 10 MB, máy chủ cắt mỗi 1 MB: ghép đủ qua 10 lần gọi, đúng từng byte (vượt xa 4 lần thử vì mỗi lần đều tiến thêm); lần xin tiếp có `Range` và `If-Range` đúng; file đổi giữa các lần (ETag khác): nhận lại toàn bộ bản mới, không bị trộn; không hỗ trợ `Range`: tải lại từ đầu, chờ 5 và 10 giây như trước; máy chủ báo có `Range` nhưng trả 200: vẫn đúng; 416 và `Content-Range` sai vị trí: tải lại từ đầu; lỗi 400: báo ngay sau 1 lần gọi | Đúng |
| Bản `fetch_bytes` hiện tại (server thử) | ETag mạnh và yếu, máy chủ cắt mỗi 4 MiB; máy chủ bỏ qua Range; 404 và 403; 429 liên tục; `Retry-After` 3600 và 20; 503 năm lần sau khi đã giữ một phần dữ liệu; kết nối nhỏ giọt (giảm giới hạn thời gian để thử) | Tải xong và đúng từng byte ở cả ETag mạnh và yếu (với `If-Range` luôn gửi thì ETag yếu thất bại); in `[200] ... restarting` khi máy chủ bỏ qua Range; 429 liên tục: chờ khoảng 13, 28, 54, 119 giây rồi bỏ cuộc; `Retry-After: 3600`: bỏ ngay, không ngủ; 503 năm lần: bỏ cuộc nếu không giữ nhiều, chờ thêm bậc 240 giây rồi tải xong nếu đang giữ nhiều; nhỏ giọt: bị cắt đúng giới hạn, tính vào bộ đếm lỗi mạng |
| `diagnose_download.py` | Bốn máy chủ thử: luôn đứt, chỉ đứt khi có header `identity`, chỉ đứt khi dùng lại kết nối, và máy chủ tốt | Kết luận in ra đúng cho từng trường hợp; nhận ra máy chủ có hỗ trợ `Range` |
| `make_stats.py` | Chạy trên nhật ký giả có `done`, `error`, `not_found`, bài chưa chạy | Các con số khớp tính tay |
| `benchmark.py` | Bọc một lệnh giả | Ra thời gian, RAM, đĩa, mã thoát; tạo file mẫu theo thời gian |
| `benchmark.py` (chạy từng đoạn) | Lệnh giả bị `Ctrl+C` giữa chừng; chạy lại cùng thư mục `--out` | Vẫn ghi `benchmark.json` với `interrupted = true`; lần chạy lại cùng `--out` bị từ chối |
| `merge_benchmarks.py` | 3 đoạn giả: bình thường, `Ctrl+C`, tắt đột ngột (chỉ có file mẫu, dòng cuối ghi dở) | Gộp đúng tổng thời gian, RAM, đĩa; đoạn thiếu `benchmark.json` vẫn được tính; dòng ghi dở bị bỏ qua |
| `sleep_cooldown` và gộp cooldown | Nghỉ 2 giây ở đoạn 1; ngắt giữa lần nghỉ 20 giây ở đoạn 2 | `logs/cooldowns.jsonl` ghi 2,0 và 2,8 giây (thực tế); `total_cooldown_seconds` = 4,8 |
| `make_ids.py` | Dải 5000 ID; ID kiểu cũ (120 ID); ID 4 chữ số; 1 ID; 5 loại lỗi nhập (khác tháng, thiếu số 0, ID kèm version, đầu lớn hơn cuối, khác số chữ số); `--chunk 500` | Đúng (5000 ID, 10 file mỗi file 500; lỗi báo rõ) |

### 11.2 Chưa kiểm thử

- **Chạy thật** trên arXiv và Semantic Scholar: cách thư viện `arxiv` phản hồi với `id_list` 50 ID, ID kiểu cũ trên máy chủ thật; định dạng thật của phản hồi Semantic Scholar (code giả định `references` là danh sách các đối tượng có `paperId`, `externalIds`, `title`, `authors`, `publicationDate`); header `Retry-After` thật; tải source thật. Việc giữ kết nối mở mới được chứng minh trên server HTTP cục bộ (không có TLS); cách máy chủ arXiv thật xử lý chưa kiểm tra.
- Phân trang hoặc bị cắt của danh sách tham khảo ở bài có rất nhiều tham khảo.
- Windows, macOS, Google Colab (mới chạy thử trên Linux).
- `benchmark.py` bắt `Ctrl+C`, `merge_benchmarks.py` và `sleep_cooldown` với crawler thật chạy nhiều giờ, và trên Windows (mới thử bằng lệnh giả trên Linux).
- Bảng chờ và các xử lý mới ở mục 5.7.1 trên arXiv thật (mới thử trên máy chủ giả lập); chưa biết ETag thật của arXiv có dạng yếu hay không.
- Chạy dài nhiều giờ, bị ngắt mạng thật, bị chặn 403 hoặc 429 thật.
- Túi nén rất lớn hoặc hỏng ở mức thực tế.

Các đoạn kiểm thử trên được chạy thủ công trong lúc soạn code và **chưa nằm trong repo**. Nên đưa vào thư mục `tests/` và chạy bằng `pytest` để repo có kiểm thử đi kèm.

---

## 12. Quyết định thiết kế và câu hỏi cần xác nhận

### 12.1 Các quyết định thiết kế

| Quyết định | Lý do |
|---|---|
| Tải source bằng `urllib` thay vì thư viện `arxiv` | Thư viện `arxiv` bản 4.x đã bỏ hàm tải; `urllib` có sẵn, ít phụ thuộc |
| Nhận dạng loại file bằng nội dung | Đuôi file và kiểu trả về của server không đáng tin; có bài trả PDF hoặc `.gz` đơn |
| Ghi `.tex`/`.bib` nguyên văn | Milestone 2 cần nguyên bản (kể cả dòng chèn ảnh) |
| Bản ghi rỗng cho version không có TeX | Đề yêu cầu không bỏ version |
| Tách 3 loại dung lượng (`downloaded`, `before`, `after`) | So file nén với file giải nén cho kết quả sai (mục 17.2) |
| Hỏi thông tin arXiv theo lô 50 ID | Giảm khoảng 4.900 lần hỏi cho 5000 ID |
| Lô lỗi thì hỏi lẻ từng bài | Một lô lỗi không làm mất cả lần chạy |
| Hai luồng (arXiv, Semantic Scholar) | Hai server độc lập, mỗi bên có quy tắc riêng, chạy song song hợp lệ |
| `Throttle` mặc định tính từ lúc lần gọi trước kết thúc | Thận trọng, bảo đảm không vi phạm quy tắc 3 giây; giống cách thư viện `arxiv` chính thức làm |
| Tải bằng `requests.Session`, gửi `Accept-Encoding: identity` và đọc byte thô | Giữ kết nối mở nhưng vẫn nhận đúng byte server gửi (không tự giải nén), để việc nhận dạng `.gz`/`.tar.gz` không đổi. `requests` đã là phụ thuộc của thư viện `arxiv` |
| `--gap-from-start` là tùy chọn, mặc định tắt | Nhanh hơn nhưng mạnh hơn cách làm chuẩn của thư viện; chỉ bật khi giảng viên xác nhận |
| Ghi `logs/throttle_runs.jsonl` mỗi lần chạy | Có số liệu thật để quyết định tối ưu và đưa vào báo cáo |
| Đo hiệu năng theo từng đoạn rồi gộp (`merge_benchmarks.py`) | Chạy 5000 ID nhiều giờ dễ bị ngắt; `benchmark.py` bản đầu ghi đè mỗi lần chạy và không ghi gì nếu bị `Ctrl+C` |
| `benchmark.py` từ chối ghi vào `--out` đã có kết quả | Tránh mất số liệu của đoạn trước khi quên đổi tên thư mục |
| Ghi riêng thời gian cooldown (`logs/cooldowns.jsonl`) và báo cả hai số (đầy đủ, trừ cooldown) | Đề tính wall time từ đầu đến cuối nên số chính là số đầy đủ; cooldown là thời gian chờ mạng chứ không phải thời gian làm việc, nên cần số phụ để diễn giải |
| Chờ lâu dần khi 429/5xx (15 đến 240 giây, lệch ±20%), thêm một bậc khi đang giữ từ 20 MB | Bỏ cuộc giữa chừng làm mất công tải lại, còn chờ vô hạn làm cả lần chạy đứng yên; độ lệch ngẫu nhiên tránh các lần thử dồn vào cùng lúc. Con số là điểm khởi đầu |
| `Retry-After`: chờ đúng yêu cầu, nhưng quá 15 phút thì bỏ bài | Tôn trọng máy chủ mà không ngủ hàng giờ; lỗi tính vào bộ đếm để cơ chế cooldown xử lý |
| Giới hạn thời gian cho từng file theo dung lượng (tốc độ sàn 10 KB/s) | `timeout=60` chỉ áp cho từng lần đọc, nên kết nối nhỏ giọt có thể treo rất lâu |
| Không gửi `If-Range` khi ETag yếu | Theo RFC 7233 máy chủ bỏ qua Range trong trường hợp này, khiến tải tiếp không có tác dụng |
| Checkpoint nhiều mức, `done.json` ghi cuối cùng | Chạy lại không mất công; bài chỉ coi là xong khi mọi việc xong |
| Ghi file qua file tạm rồi đổi tên | Bị ngắt giữa chừng không để lại file dở |
| Lấy tham khảo một lần cho cả bài | Semantic Scholar khó phân biệt theo version (cần xác nhận, mục 12.2) |
| Lưu cả `references_all.json` | Giữ đủ dữ liệu cho các milestone sau; bảng cuối chỉ cần bản có arXiv ID |
| Hỏi Semantic Scholar bằng ID gốc không kèm version | Semantic Scholar nhận `arXiv:<id>` |
| Một bài lỗi không làm hỏng cả lần chạy | Chạy hàng nghìn bài, lỗi lẻ tẻ là bình thường |

### 12.2 Câu hỏi cần xác nhận với giảng viên thực hành

1. **Tham khảo theo version:** đề nói mỗi version có tham khảo riêng nhưng Semantic Scholar khó phân biệt. Có chấp nhận lấy một lần cho cả bài rồi gắn cho mọi version không?
2. **Ngày sửa từng version:** Milestone 1 có yêu cầu không? Hiện `meta.json` chỉ có ngày của version mới nhất.
3. **Định nghĩa "tỷ lệ thành công của reference metadata":** tỷ lệ bài lấy được dữ liệu từ Semantic Scholar, hay tỷ lệ tham khảo có arXiv ID?
4. **"Dung lượng trước và sau khi bỏ ảnh":** so file nén tải về với file giữ lại, hay so giải nén đầy đủ với giải nén chỉ `.tex`/`.bib`? (Code đang ghi cả ba số.)
5. **File `.bbl`:** có cần giữ không? Milestone 2 cần các mục `\bibitem`, đôi khi nằm trong `.bbl` (hiện chỉ giữ `.tex`/`.bib`).
6. **Đo hiệu năng:** có được đo trên tập con đại diện ở Colab nếu chạy toàn bộ dải quá lâu không? Có được lưu dữ liệu sang Drive không?
7. **Đưa số liệu vào Jupyter Book:** repo code không chứa dữ liệu, vậy có được commit file thống kê nhỏ (`summary.json`, `papers.csv`, `benchmark.json`) vào repo báo cáo không?
8. **Dải ID:** hai đầu có tính không? Dải có đi qua nhiều tháng không?
9. **Bản Jupyter Book:** môn đang dùng bản 1 hay bản 2 (MyST)?

---

## 13. Hạn chế đã biết và hướng cải tiến

| Hạn chế | Hướng xử lý |
|---|---|
| `meta.json` chỉ có ngày của version mới nhất | Thử hỏi API bằng ID kèm đuôi `vN` để lấy ngày từng version (tốn thêm 1 lần hỏi mỗi version) |
| Tham khảo không tách theo version | Phụ thuộc câu trả lời của giảng viên (12.2, câu 1) |
| Bài mà Semantic Scholar chưa có dữ liệu vẫn được đánh dấu `done` (`n_refs = null`) | Sau vài ngày, xóa `done.json` của các bài đó rồi chạy lại. Có thể thêm cờ tự động thử lại |
| Một lỗi từ Semantic Scholar làm cả bài thành `error` dù đã tải xong các version | Chạy lại chỉ cần làm phần tham khảo (version đã tải không tải lại). Có thể tách thành lỗi riêng |
| Không giữ `.bbl` | Xem 12.2, câu 5 |
| Chưa kiểm tra danh sách tham khảo có bị cắt ở bài nhiều tham khảo | Đọc tài liệu API; có thể cần endpoint phân trang |
| ID đầu vào phải là ID gốc (không kèm version) | `make_ids.py` đã chặn; nếu dùng `--id` trực tiếp phải tự chú ý |
| `main` luôn thoát mã 0, kể cả khi có bài `error` | Đọc dòng tổng kết hoặc chạy `make_stats.py`; có thể đổi sang mã thoát khác 0 khi có lỗi |
| `discover_seconds` là trung bình theo lô, không phải thời gian riêng từng bài | Chấp nhận được; số tổng thể vẫn đúng |
| Chạy bị ngắt nhiều đoạn: số đo là tổng các đoạn, không phải một lần chạy liền mạch | Đã có cách đo theo đoạn và gộp (mục 4.8.1); ghi rõ số đoạn trong báo cáo, hoặc đo thêm một tập mẫu chạy liền một mạch |
| Bài chạy dở lúc bị ngắt, hoặc bài lỗi được thử lại, có `seconds` thấp hơn thực tế vì các version đã tải được bỏ qua | Chỉ ảnh hưởng số ít bài; nêu rõ trong báo cáo |
| Chỉ cooldown được ghi riêng; các lần chờ giữa các lần thử lại (retry) vẫn nằm trong wall time | Chấp nhận được; nếu cần thì ghi thêm tương tự `sleep_cooldown` |
| Thời gian phản hồi `r` của mỗi lần gọi bị cộng thêm vào khoảng chờ 3 giây | Đo `r` thật rồi quyết định theo mục 10.9 |
| Giữ kết nối mở chưa kiểm chứng với arXiv thật | Chạy 100 bài đầu, so `avg_request_seconds` |
| Tải tiếp (`Range`) chỉ có tác dụng nếu máy chủ hỗ trợ; nếu không, phải tải lại file từ đầu | Log chạy thật cho thấy số byte đã giữ tăng dần qua các lần thử (ví dụ 12.6, 14.7, 17.8 MB rồi xong), nên tải tiếp nhiều khả năng hoạt động. Bản mới in `[206]` hoặc `[200]` ở mỗi lần tải tiếp để xác nhận chắc. Chạy `diagnose_download.py` (cách thứ 6) cũng cho biết arXiv có trả `206` không |
| Crawler gửi `If-Range` kèm ETag mạnh hoặc Last-Modified (ETag yếu `W/...` thì không gửi). Nếu máy chủ vẫn bỏ qua nó (ví dụ ETag khác nhau giữa các node CDN) thì trả `200` và crawler tải lại từ đầu | Đã tái hiện trên máy chủ thử rằng `If-Range` kèm ETag yếu làm tải tiếp thất bại; chưa biết ETag thật của arXiv có dạng yếu không. Kiểm tra: xin `Range` ở vị trí từng bị đứt rồi xem `[206]` hay `[200]` trong log, hoặc xem header `ETag` qua `curl.exe -s -D - -o NUL -r 0-0 <url>` |
| Phần đã tải chỉ nằm trong RAM: bài báo `error` thì lần chạy sau tải lại từ byte 0 | Chưa lưu `.part` ra đĩa; cân nhắc thêm nếu bài lớn hay lỗi lặp lại |
| Bảng chờ 15/30/60/120/240 giây là điểm khởi đầu, chưa hiệu chỉnh bằng số liệu đủ lớn | Đếm các đợt 429/503 và lần thử hết đợt trong log sau khoảng 500 bài (mục 5.7.1) |
| Bảng chờ mới cũng áp dụng cho lỗi 429 của Semantic Scholar (trước đây 5 giây trở lên, nay 15 giây trở lên) | Chấp nhận được vì lỗi này hiếm khi đã đặt `S2_API_KEY` |
| Chưa có kiểm thử tự động trong repo | Đưa các kiểm thử ở mục 11.1 vào `tests/` |

---

## 14. Xử lý sự cố

| Triệu chứng | Nguyên nhân và cách sửa |
|---|---|
| `ModuleNotFoundError: No module named 'arxiv'` | Chưa cài thư viện hoặc chưa bật môi trường ảo: bật `.venv` rồi `pip install -r src/requirements.txt` |
| `ModuleNotFoundError: No module named 'requests'` | Như trên: bật `.venv` rồi `pip install -r src/requirements.txt` |
| `python` không chạy được | Thử `python3` hoặc `py` |
| `FileNotFoundError: ids.txt` | Đứng sai thư mục, hoặc chưa chạy `make_ids.py` |
| `error: no ids given` | Quên `--id` hoặc `--ids-file` |
| `make_ids.py` báo khác tháng | Dải đi qua 2 tháng: tạo 2 danh sách rồi nối file |
| Lỗi 403 | Bị chặn: kiểm tra đã đặt `CONTACT_EMAIL`, đang dùng `export.arxiv.org`; dừng một lúc rồi chạy lại, không rút ngắn khoảng chờ |
| Nhiều lỗi 429 từ Semantic Scholar | Key chưa được đặt trong cửa sổ terminal này, hoặc đang hỏi quá nhanh. Kiểm tra biến `S2_API_KEY` |
| Dòng `discover batch ... failed ...; will ask one by one` | Một lô hỏi arXiv lỗi mạng; script tự hỏi lẻ từng bài của lô đó. Nếu xuất hiện liên tục, kiểm tra mạng |
| Có dòng `error` trong log | Chạy `python src/analyze_errors.py` để biết nhóm nguyên nhân (mục 4.14); chạy lại cùng lệnh để thử lại bài đó |
| Số bài `error` tăng dần theo thời gian | Thường do bị chặn hoặc giới hạn tốc độ, mất mạng, đĩa đầy, hoặc chạy 2 bản cùng lúc (cùng key Semantic Scholar, cùng IP). Chạy `analyze_errors.py` xem phần xu hướng và nhóm nguyên nhân; kiểm tra dung lượng đĩa; chỉ chạy một bản tại một thời điểm |
| `ProtocolError('Connection broken: IncompleteRead(... bytes read, ... more expected)')` | Kết nối bị đóng trước khi nhận đủ file. Có thể do mạng, máy chủ hoặc CDN, proxy hoặc phần mềm diệt virus, hoặc cách tải. Bản crawler mới tự thử lại bằng kết nối mới và tải tiếp phần còn thiếu nếu máy chủ hỗ trợ. Để tìm nguyên nhân: dừng crawler, chạy `python src/diagnose_download.py --id <ID>` (mục 4.14) |
| Dòng `[net error] ProtocolError ...` mà bài vẫn ra `done` | Bình thường: kết nối bị cắt giữa chừng và crawler tải tiếp. Chỉ cần xử lý bài kết thúc bằng `error` (mục 5.7.1) |
| `[retry 7]` có phải 7 lần thất bại? | Không, đó là số lần gọi. `fails` mới là số lần lỗi liên tiếp mà không đi xa thêm; bài chỉ lỗi khi `fails` vượt giới hạn |
| Bài `error` sau chuỗi `[HTTP 503]` hoặc `[HTTP 429]` | Máy chủ từ chối lâu hơn tổng thời gian chờ. Phần đã tải bị mất. Chạy lại cùng lệnh khi arXiv ít tải; nếu xảy ra nhiều, đếm các đợt để chỉnh `HTTP_WAITS` (mục 5.7.1) |
| `server asks to wait Ns: giving up` | `Retry-After` lớn hơn 15 phút: bài bị bỏ và tính vào bộ đếm cooldown. Chạy lại sau |
| Số bài `not_found` nhiều bất thường | Kiểm tra lại ID đầu và ID cuối, cách nhập dải ID |
| `benchmark.py: error: ... already has results` | Thư mục `--out` đã có kết quả của đoạn trước. Dùng `run_XX` kế tiếp (không ghi đè); chỉ xóa thư mục cũ khi muốn đo lại từ đầu |
| `merge_benchmarks.py` báo `no runs found` | Tên thư mục không bắt đầu bằng `run_`, hoặc `--runs` trỏ sai chỗ |
| `total_cooldown_seconds` là `null` trong `benchmark_total.json` | Có đoạn không biết giờ bắt đầu (thiếu `benchmark_start.json`, ví dụ đoạn đo bằng bản `benchmark.py` cũ). Chỉ báo `total_wall_seconds` |
| Bị ngắt giữa chừng | Chạy lại đúng lệnh cũ. Nếu đang đo hiệu năng, dùng thư mục `run_XX` kế tiếp (mục 4.8.1) |
| Colab bị ngắt, mất dữ liệu | Chạy trong thư mục trên Google Drive, chia phần 500 ID |
| Hết dung lượng đĩa | Kiểm tra dung lượng trống; ước lượng theo 10.6 |
| Thiếu số RAM trong báo cáo | Chưa cài `psutil` |

---

## 15. Bảo mật và quy tắc repo

- **Không commit**: `data/`, `logs/`, `stats/`, `ids.txt`, `ids_part_*.txt`, `.venv/`, `.env`, mọi file chứa key. Kiểm tra bằng `git status` trước mỗi lần commit.
- **Key Semantic Scholar** là bí mật cá nhân: chỉ đặt qua biến môi trường (hoặc Secrets của Colab). Nếu lỡ lộ, xin key mới và hủy key cũ.
- **Điều khoản sử dụng** của các dịch vụ: không vượt giới hạn tốc độ; không chia sẻ key. Trong báo cáo nên ghi nguồn dữ liệu là arXiv và Semantic Scholar.
- **Không chạy song song nhiều máy** (kể cả máy của các bạn trong nhóm) để tăng tốc: điều khoản của arXiv áp dụng giới hạn cho tất cả máy gộp lại và cấm tăng số máy để vượt giới hạn.
- Repo code chỉ chứa mã nguồn, README, requirements (theo đề).
- Commit nhỏ và thường xuyên với mô tả rõ, vì lịch sử commit thể hiện tiến độ nhóm.
- Trước khi nộp: clone repo vào thư mục mới và làm theo README từ đầu để chắc người khác chạy được.

---

## 16. Thuật ngữ

| Thuật ngữ | Giải thích |
|---|---|
| arXiv ID | Mã bài, ví dụ `2310.12345` (kiểu cũ: `hep-th/9901001`) |
| Version (phiên bản) | Mỗi lần tác giả nộp lại bài: v1, v2, v3... |
| LaTeX, `.tex` | "Bản thảo gốc" dạng văn bản có lệnh, ví dụ `\section{...}` |
| `.bib` | File danh sách tài liệu được trích dẫn (BibTeX) |
| Metadata | Thông tin về bài (tên, tác giả, ngày), không phải nội dung |
| Tham khảo (reference) | Bài mà một bài trích dẫn |
| Semantic Scholar (S2) | Dịch vụ lưu "bản đồ trích dẫn" |
| S2 ID | Mã bài trên Semantic Scholar |
| API | "Cửa sổ" để chương trình hỏi dịch vụ và nhận câu trả lời có cấu trúc |
| Rate limit | Giới hạn tốc độ hỏi |
| HTTP 403 / 404 / 429 | Bị chặn / không có / hỏi quá nhanh |
| Checkpoint | "Điểm lưu": chạy lại thì phần đã xong được bỏ qua |
| Luồng (thread) | Một "dây chuyền" làm việc; hai luồng làm hai việc cùng lúc |
| Theo lô (batch) | Gộp nhiều ID vào một lần hỏi |
| JSON, JSONL | Định dạng dữ liệu dạng văn bản; JSONL là mỗi dòng một JSON |
| RSS / RAM | Bộ nhớ chương trình đang dùng |
| Wall time | Thời gian trôi qua thực tế (đồng hồ treo tường) |
| Colab | Máy tính miễn phí của Google chạy trên mạng |
| Bản ghi rỗng | Version tồn tại nhưng không có TeX; vẫn có thư mục và `status.json` với `status = "empty"` |

---

## 17. Phụ lục

### 17.1 Tóm tắt lệnh

```
# Cài đặt (một lần)
python -m venv .venv  &&  (bật .venv)  &&  pip install -r src/requirements.txt
# Đặt biến môi trường CONTACT_EMAIL và S2_API_KEY

# Sinh danh sách ID
python src/make_ids.py <ID đầu> <ID cuối> -o ids.txt

# Thử
python src/milestone1_crawler.py --id 1706.03762
python src/milestone1_crawler.py --ids-file ids.txt --limit 100

# Biết tổng số version trước khi chạy dài
python src/milestone1_crawler.py --ids-file ids.txt --discover-only

# Chạy bản chính (kèm đo hiệu năng; mỗi đoạn một run_XX, bị ngắt thì chạy tiếp với run_02, run_03...)
python src/benchmark.py --out stats/runs/run_01 -- python src/milestone1_crawler.py --ids-file ids.txt

# Gộp các đoạn đo
python src/merge_benchmarks.py

# Tính số liệu
python src/make_stats.py --ids-file ids.txt
```

### 17.2 Lịch sử thay đổi trong quá trình làm

| # | Thay đổi | Lý do |
|---|---|---|
| 1 | Khung ban đầu `milestone1_starter.py` (về sau đổi tên, xem dòng 8): hỏi từng bài, tải từng version, nhận dạng file, hỏi Semantic Scholar, checkpoint, log | Bản chạy đầu tiên từ đầu đến cuối |
| 2 | Tách dung lượng thành 3 số: `bytes_downloaded`, `bytes_before`, `bytes_after` | **Lỗi phát hiện khi kiểm thử**: lúc đầu "trước khi bỏ ảnh" là dung lượng file nén còn "sau" là dung lượng đã giải nén, nên mức giảm bị tính sai (thậm chí âm). Giờ cả hai cùng là dung lượng chưa nén |
| 3 | Thêm `discover_seconds` | Báo cáo cần thời gian "tìm bài" |
| 4 | Hỏi thông tin arXiv theo lô (`discover_many`), có dự phòng hỏi lẻ | Dải 5000 ID: tiết kiệm khoảng 4.900 lần hỏi |
| 5 | Thêm `make_stats.py` và `benchmark.py` | Báo cáo cần số liệu thống kê và đo hiệu năng |
| 6 | Thêm `make_ids.py` | Giảng viên giao dải ID liên tục, không cần gõ tay 5000 dòng |
| 7 | Thêm tùy chọn `--discover-only` | Biết tổng số version trước khi chạy dài để ước lượng thời gian chính xác |
| 8 | Đổi tên `milestone1_starter.py` thành `milestone1_crawler.py` | Tên phản ánh đúng vai trò (không còn chỉ là khung mẫu) |
| 9 | Thêm đo đạc trong `Throttle` và file `logs/throttle_runs.jsonl` | Biết thời gian thật đi vào chờ đợi hay vào gọi mạng |
| 10 | Chuyển phần tải sang `requests.Session` (giữ kết nối mở, đọc byte thô) | Giảm thời gian thiết lập kết nối mỗi lần gọi; không đổi cách nhận dạng file |
| 11 | Thêm tùy chọn `--gap-from-start` (mặc định tắt) | Cho phép bỏ `r` khỏi vòng chờ nếu giảng viên xác nhận quy tắc |
| 12 | Thêm `kind = "corrupt"` và đọc hết luồng nén trước khi ghi file | **Lỗi phát hiện khi kiểm thử**: file `.gz` bị cắt cụt làm `tarfile.open` ném `EOFError` mà code cũ không bắt, khiến bài bị tính là `error` thay vì bản ghi rỗng |
| 13 | Ghi vị trí lỗi (`where`) vào dòng `error` của log | Biết lỗi xảy ra ở dòng code nào |
| 14 | Nghỉ khi gặp nhiều lỗi bị chặn/mạng liên tiếp, dừng sau 15 lỗi | Tránh dồn dập gửi thêm yêu cầu khi đang bị chặn hoặc mất mạng, vốn làm số bài `error` tăng dần |
| 15 | Thêm `analyze_errors.py` | Cho biết nguyên nhân các bài `error` và xu hướng theo thời gian |
| 16 | Bắt cả lỗi của `urllib3` (`ProtocolError`/`IncompleteRead`) khi tải, kiểm tra đủ byte so với `Content-Length`, tính vào bộ đếm lỗi mạng; `where` ưu tiên dòng trong code của dự án | **Lỗi do chính code gây ra**: từ khi đổi sang đọc byte thô (dòng 10 của bảng này), lỗi đứt kết nối giữa lúc tải không được bọc bởi `requests` nên không được thử lại. Người dùng gặp lỗi này ở nhiều bài, đã tái hiện bằng server thử |
| 17 | Sau lỗi mạng bỏ session cũ và mở kết nối mới; gắn URL vào lỗi và ghi `url` vào log; chế độ `raw=False` cho JSON | Không dùng lại kết nối có thể đã hỏng; biết chính xác URL nào lỗi |
| 18 | Thêm `diagnose_download.py` và tùy chọn `--default-encoding` | Người dùng cho biết mạng bình thường, nên cần công cụ tách các khả năng (mạng, máy chủ, header, giữ kết nối) thay vì đoán |
| 19 | Tải tiếp phần còn thiếu bằng `Range` + `If-Range`, kiểm tra `Content-Range`, lần thử có tiến triển không tính là thất bại, lỗi vĩnh viễn không thử lại | Đã kiểm chứng một đề xuất sửa lỗi từ nguồn khác bằng thực nghiệm: ý tưởng tải tiếp đúng, nhưng bản đề xuất hết lượt sau 7 lần dù mỗi lần đều tiến thêm, có thể ghép lẫn hai phiên bản file nếu file đổi giữa các lần, và thử lại vô ích 7 lần với lỗi 400 |
| 20 | `diagnose_download.py` in thêm nhận xét bội số 1 MiB và nhà cấp chứng chỉ TLS | Số byte nhận được trong log đều là bội số của 1 MiB; đã kiểm tra rằng cách đọc của thư viện không tự làm tròn như vậy, nên cần xem bên gửi hay thiết bị trên đường đi |
| 21 | `benchmark.py` ghi mẫu dần từng giây, vẫn lưu `benchmark.json` khi bị `Ctrl+C`, ghi `started_at` và `done_papers_*`; thêm `merge_benchmarks.py` gộp các đoạn | `benchmark.py` bản đầu ghi đè kết quả mỗi lần chạy và không ghi gì nếu bị ngắt; chạy 5000 ID nhiều giờ dễ bị ngắt, nên cần đo theo đoạn rồi gộp |
| 22 | `benchmark.py` từ chối chạy nếu `--out` đã có kết quả | Tránh mất số liệu đoạn trước khi quên đổi tên thư mục `run_XX` |
| 23 | Thêm `sleep_cooldown` và `logs/cooldowns.jsonl`; `throttle_report` ghi thêm `cooldown_seconds`; `merge_benchmarks.py` tính `wall_seconds_excl_cooldown` | Cooldown nằm trong wall time nhưng là thời gian chờ mạng, không phải thời gian làm việc; không cần canh máy để ngắt khi crawler đang nghỉ |
| 24 | Thêm giới hạn thời gian cho một file (`_limit`), log tiến độ và thử lại ra màn hình, tính "tiến triển" theo mức xa nhất từng đạt; lỗi `Timeout` được tính vào bộ đếm lỗi mạng | `timeout=60` chỉ áp cho từng lần đọc nên kết nối nhỏ giọt có thể treo vô hạn; cần thấy crawler đang làm gì khi tải file lớn. **Lỗi phát hiện khi đánh giá**: lỗi `Timeout` lúc đầu không được tính vào chuỗi lỗi liên tiếp, nên mạng chậm kéo dài không kích hoạt cooldown |
| 25 | Không gửi `If-Range` khi ETag dạng yếu `W/...` | Theo RFC 7233 máy chủ phải bỏ qua Range khi validator yếu. Đã tái hiện trên máy chủ thử: lỗi lặp lại ở cùng một chỗ sau mỗi lần chạy, sửa xong thì tải xong. Chưa biết ETag thật của arXiv |
| 26 | `Retry-After`: chờ đúng số giây server bảo, quá 15 phút thì bỏ bài; bỏ cách cắt ở 120 giây | Cắt 120 giây là bỏ qua yêu cầu của máy chủ (thử lại 4 lần cách nhau 120 giây dù server bảo 3600). Không cắt mà không giới hạn thì một bài có thể ngủ 4 giờ im lặng (đã tái hiện trên máy chủ thử) |
| 27 | Bảng chờ khi 429/5xx đổi thành 15, 30, 60, 120 giây (±20%), thêm bậc 240 giây khi đang giữ từ 20 MB; đóng kết nối ở các nhánh khác 200/206; in `[206]` và `[200]` | Log chạy thật: có bài nhận 503 và 429 liên tiếp trong khoảng 75 giây khi đang giữ 17.8 MB, hết lượt và mất công tải lại; 429 sau khi bị cắt thường hết trong 10 đến 15 giây. Con số mới là điểm khởi đầu, cần hiệu chỉnh bằng log |
