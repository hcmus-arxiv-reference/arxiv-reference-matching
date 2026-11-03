# Benchmark so sánh crawler giữa các thành viên

Mục tiêu: chọn bản cài đặt tốt nhất cho **từng Stage** (Discovery, Source fetch,
References, Export, Runner) để ghép vào khung `src/crawl/`
(xem [ADR 0001](../adr/0001-src-crawl-la-khung-duy-nhat.md)).

## Hai giai đoạn

1. **Sàng lọc**: mỗi thành viên nộp `benchmark.json` (theo
   [mẫu](benchmark.template.json)) cho lượt crawl **đã chạy** trên Range của mình,
   kèm thư mục output. Giai đoạn này đánh giá chủ yếu **chất lượng dữ liệu**
   (validator chạy trên output thật). Số thời gian/RAM chỉ để tham khảo vì khác
   máy, khác mạng, khác Range.
2. **Đối chứng**: các bản ứng viên của từng Stage được cắm vào khung và chạy trên
   **cùng một tập ID mẫu**, cùng Colab CPU, cùng harness đo. Chỉ số hiệu năng
   dùng để chọn lấy từ giai đoạn này.

## Định nghĩa trường (bắt buộc dùng đúng nghĩa)

| Trường | Nghĩa |
|---|---|
| `cold_run` | `true` nếu lượt đo bắt đầu với cache rỗng. Resume thì `false` và ghi `resumed_passes`. |
| `stages.<x>.seconds` | Thời gian tường của riêng Stage đó, **gồm** chờ rate limit và backoff. Không tách được thì để `null`, không ước lượng. |
| `requests` | Số HTTP request thật gửi đi (không tính cache hit). |
| `retries` | Số lần gửi lại do lỗi. |
| `errors_by_type` | Đếm theo loại, ví dụ `{"429": 12, "timeout": 3, "404": 1, "corrupt_archive": 2}`. |
| `publications_complete` | Publication có **đủ mọi Version** (TeX hoặc bản ghi rỗng non-TeX) **và** lấy S2 thành công. |
| `versions_non_tex` | Version chỉ có PDF/docx, đã giữ bản ghi rỗng. |
| `bytes_before/after_figure_removal` | Tổng byte archive giải nén trước và sau khi bỏ file không phải `.tex/.bib`. |
| `peak_rss_mb` / `avg_rss_mb` | RAM của **cả cây tiến trình**, lấy mẫu định kỳ. Không dùng `ru_maxrss` cho trung bình. |
| `peak_disk_mb` / `output_mb` | Disk lớn nhất trong lúc chạy / dung lượng thư mục output cuối (`du -sb`). |
| `measured_by` | Công cụ đo thật sự đã dùng. Số không có nguồn đo sẽ không được dùng. |

Trường nào không có số liệu thật thì để `null`. **Không điền số ước lượng.**

## Kiểm tra chất lượng đầu ra

Với output theo layout của `src/crawl/`, chạy validator trên máy cục bộ:

```sh
python -m scripts.validate_crawl \
  --data-dir data/crawl-smoke \
  --benchmark benchmarks/<github-username>.json
```

Validator chỉ đọc dữ liệu. Nó đối chiếu số ID đã thử và các bộ đếm trong
`totals` với manifest, metadata, receipt từng Version, file TeX/BibTeX và cache
Semantic Scholar; đồng thời kiểm tra checksum, Version coverage và arXiv ID của
references. Bộ đếm khai báo là `null` sẽ được bỏ qua. Lệnh in báo cáo JSON, thoát
mã `0` khi không có phát hiện và `1` nếu có lỗi hoặc số liệu không khớp. Đây là
kiểm tra tính nhất quán/độ phủ của output; nó không đánh giá nội dung khoa học
của TeX hay xác minh các số đo hiệu năng không thể suy ra từ cache.

`references_total` và `references_with_arxiv_id` được đếm trên các bản ghi S2
thô của những Publication có cache hợp lệ; bản thứ hai đếm mỗi bản ghi có
`citedPaper.externalIds.ArXiv`, trước bước khử trùng lặp khi xuất bảng.

Hiện validator đọc manifest và layout của `src/crawl/`. Output của crawler
khác cần được chuyển sang hợp đồng này trước khi kiểm tra; không được coi việc
thiếu file trong layout chuẩn là bằng chứng rằng crawler khác tạo dữ liệu sai.

## Đo lại cho chuẩn (nếu muốn)

Harness có sẵn trên `main`: `python -m src.benchmark` (mặc định lấy mẫu RSS cả
cây tiến trình mỗi 1 giây, disk mỗi 5 giây; chỉnh bằng `--interval`,
`--disk-interval`). Bọc lệnh crawl của mình bằng harness này để có
`peak_rss_mb`, `avg_rss_mb`, `peak_disk_mb` đúng định nghĩa.
