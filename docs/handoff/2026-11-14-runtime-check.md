# Handoff 2026-11-14: Engine có thời gian chạy dự đoán được, chờ chạy thử trên Colab

Tiếp nối `docs/handoff/2026-11-13-benchmark-colab.md`. Nhánh `feat/predictable-runtime`
(từ `main` `6e4d622`, đã gồm PR #49 References theo lô). Thuật ngữ theo `CONTEXT.md`.

Quyết định 14/11 (Bảo): Bảo tự sửa Engine M1 và chạy thử trên Colab; đạt cổng thì mới đặt tag
mới và chia cho cả nhóm chạy.

## 1. Đã thay đổi

| Phần | Nội dung | File |
|---|---|---|
| Log từng request | Mỗi lần gọi HTTP và mỗi lần backoff ghi một dòng (service, endpoint, status, byte, giây, giây giãn cách, giây chờ 429), không có URL, header hay body | `src/crawl/http_client.py`, `src/common/metrics.py` (`JsonlLog`), `src/crawl/cli.py` → `manifests/requests.jsonl` |
| S2 không chặn arXiv | Lô S2 chạy ở một luồng riêng có hàng đợi; lô kế được xếp khi còn nửa lô hiện tại; lô bị 429 thử lại mỗi 60 giây tới 30 phút; sau khi tải source, một bài chờ lô tối đa 10 giây (không chờ nếu đã có bài đang chờ S2); lô trễ được ghi sau qua `settle_references`, Runner gọi giữa các bài, trước Export và khi dừng | `src/crawl/pipeline.py`, `src/crawl/runner.py` |
| Mô hình dự đoán | Mỗi request `/src/` chiếm `max(3,1 s, độ trễ + byte/băng thông)`; kích thước theo mẫu 415 Version | `src/crawl/runtime_model.py`, `configs/size_sample_bytes.json` |
| Script | `speedtest` (tải 2 Version, đo băng thông, dự đoán giờ một Range), `check` (so tốc độ thật với dự đoán, đếm 429, phần arXiv phải chờ S2) | `scripts/predict_runtime.py` |
| Notebook | Ô đo tốc độ trước khi crawl, ô kiểm dự đoán sau các đoạn, tham số `RUNTIME_CHECK`, hướng dẫn cổng chạy thử | `notebooks/colab_m1_selftest.ipynb` |

`timings.jsonl` thêm `references_wait_seconds`. Không đổi schema bảng hay cấu trúc cache.
Test: 310 qua trên Mac (Python 3.14 trong venv).

## 2. Số đo trên Mac (14/11, Range Bảo)

| | Lượt 1 (ID 1–60, trước bản sửa lô trễ) | Lượt 2 (ID 61–120) |
|---|---|---|
| Băng thông (speedtest) | 4,24 MB/s | (dùng lại) |
| Wall time | 617 s | 371 s |
| Tốc độ thực tế / dự đoán | 350 / 548 bài/giờ (lệch −36%) | 582 / 627 bài/giờ (lệch −7%) |
| S2 | 5/5 request 429, lô hỏng; arXiv chờ 226 s (37%) | 2/3 request 429 rồi 200; arXiv chờ 20 s (5,5%) |
| Mô hình giải thích wall time | 99,5% | 99,1% |
| References | 0/60 | 60/60 |
| Publication hoàn chỉnh | 0/60 | 58/60 (2 bài arXiv trả 404 cho `/src/`) |

- Phần arXiv khớp mô hình ở cả hai lượt (giải thích 99% wall time); sai lệch còn lại là do S2.
- 20 s chờ ở lượt 2 là hai bài chờ đủ 10 s khi S2 đang 429. Bản sửa cuối (`afd5974`) chỉ cho
  bài đầu tiên chờ; **chưa chạy lại trên Mac**, mới có unit test.
- Ước cả Range trên Mac: 8,6 giờ theo tốc độ đo, 7,2–8,0 giờ theo mô hình.
- **Băng thông Colab vẫn chưa đo.** Theo mô hình: 1 MB/s → 12,3 giờ; 2 MB/s → 9,3 giờ; ≥ 5 MB/s → khoảng 8 giờ.

## 3. Chạy thử trên Colab (Bảo)

Cần nhánh có trên GitHub (`git push -u origin feat/predictable-runtime`).

1. Không để lượt crawl nào khác của Bảo chạy cùng lúc (cùng S2 key, quy tắc một kết nối arXiv).
2. Runtime CPU mới. Ô Tham số: `REF = "feat/predictable-runtime"`, `MEMBER = "bao"`,
   `ID_MODE = "range"`, `MAX_SEGMENTS = 2`, giữ `RUNTIME_CHECK = True`. Run all.
3. Ô **Đo tốc độ** in băng thông và số giờ dự đoán. Ghi lại.
4. Sau 2 đoạn (khoảng 90 phút), ô **Kiểm dự đoán** in `KẾT LUẬN: ĐẠT` khi tốc độ thực tế lệch dự
   đoán không quá 15% và arXiv chờ S2 không quá 5% wall time. File `runtime-check.json` nằm trong
   thư mục phiên.

**Đọc kết quả:**

| Kết quả | Nghĩa là | Làm tiếp |
|---|---|---|
| ĐẠT, dự đoán ≤ 12 giờ | Thời gian chạy dự đoán được | Review, merge, đặt tag `m1-bench-v3`, đổi `REF` mặc định trong notebook, báo nhóm |
| ĐẠT nhưng dự đoán > 12 giờ | Mô hình đúng, Colab tải chậm | Báo nhóm số giờ thật; vẫn kịp 17/11 nếu bắt đầu ngay |
| KHÔNG ĐẠT, chờ S2 > 5% | S2 vẫn giữ arXiv | Xem `references_wait_seconds` trong `timings.jsonl` và dòng `s2` trong `requests.jsonl` |
| KHÔNG ĐẠT, lệch > 15% mà S2 thấp | Có chi phí ngoài mô hình | Xem `explained_share`; so `paced + seconds` của request arXiv với `timings.jsonl` |

## 4. Chưa làm, chưa kiểm

- Chưa push, chưa PR, chưa review. Chưa đặt tag. `REF` mặc định trong notebook vẫn `m1-bench-v2`.
- Chưa chạy trên Colab. Chưa chạy lại trên Mac sau `afd5974`.
- Lô S2 bị 429 quá 30 phút thì các bài trong lô ghi lỗi 429 và được gom lại ở lượt sau
  (`--max-passes 3 --retry-delay 600` trong notebook).
