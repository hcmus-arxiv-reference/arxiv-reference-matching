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

## 3b. Lượt thử Colab 15/11 (Bảo, `b60f3b6`): KHÔNG ĐẠT vì API Discovery của arXiv

Đoạn `run_001`, 03:57–04:44 UTC, 2.827 s. Số đo từ checkpoint (`requests.jsonl`):

| | Số đo |
|---|---|
| Speedtest `/src/` | 7,30 MB/s → dự đoán 7,7 giờ/Range; file 5 MB tải trong 0,17 s |
| `/api/query` (Discovery) | 55 request: 5 lần 200, 43 lần 429, 2 lần 503, 5 lần timeout 60 s |
| Backoff arXiv | 1.733 s (61% wall time) |
| S2 | 1 request, 200; arXiv chờ S2 0 s |
| Kết quả | thăm 11, hoàn chỉnh 4 Publication (14 bài/giờ) |

- Lô Discovery 50 ID bị 429 → Engine cũ hỏi từng ID → mỗi ID lại 429 và backoff tới 240 s.
- Từ Mac lúc 05:31 UTC cùng ngày: API 3/3 lần 200 (trung vị 0,16 s). **Nguyên nhân 429 chưa rõ.**
  Bảo xác nhận không phải do IP. Chưa kiểm: có thành viên khác crawl cùng lúc không, có ai dùng
  chung `CONTACT_EMAIL` (nằm trong User-Agent) hay S2 key không.
- Sửa (commit sau `b60f3b6`): lô Discovery bị 429/5xx/timeout được thử lại **cả lô** sau
  60/120/240/300/300 s; hết lượt chờ thì thử một ID, ID đó qua mới hỏi từng ID, không qua thì
  các ID ghi lỗi 429 không gửi request và được gom lại ở lượt sau. `speedtest` hỏi thử API 3 lần,
  thoát mã 3 nếu bị giới hạn; ô Đo tốc độ khi đó dừng **trước khi crawl**. `check` in số 429 và
  phần wall time chờ backoff của arXiv.
- Notebook: tách ô Gắn Drive / hàm lưu / thư mục lượt, định nghĩa / chạy crawl, thống kê / validator.

## 3c. Kế hoạch 15/11: Discovery từ snapshot metadata arXiv

Thầy (15/11) chỉ quy định đầu vào/đầu ra, không giới hạn phương pháp; Bảo chốt ưu tiên thời gian.
Discovery và ngày từng Version lấy từ snapshot Kaggle `Cornell-University/arxiv` thay cho
`/api/query` (khoảng 973 request mỗi Range, nguồn của 429 ở lượt thử 15/11).

1. Bảo tải `archive.zip` từ Kaggle (khoảng 1,5 GB) về `~/Downloads`.
2. `python -m scripts.extract_snapshot --snapshot ~/Downloads/archive.zip --member all --out <file>.json.gz`
   (25.000 ID của 5 Range, vài MB; header có sha256 snapshot và `latest_update_date`).
3. So extract với 5.000 metadata đã crawl qua API của Range Bảo (title, authors, ngày, số Version).
4. Upload extract lên HF dataset (đề xuất `inputs/arxiv-snapshot.json.gz`, tham số
   `METADATA_SNAPSHOT` của notebook) — **cần Bảo duyệt tên đường dẫn**.
5. Chạy thử Colab lại; dự đoán khoảng 6,7 giờ/Range (chỉ còn `/src/`).

`latest_update_date` của snapshot là mốc chốt độ phủ Version, ghi vào báo cáo.

**Kết quả 15/11** (snapshot Kaggle ngày 15/11, `latest_update_date` 2026-11-13, sha256 `d30041a8…`):
trích đủ 25.000/25.000 ID trong 14 giây, file 2,7 MB. So với 5.000 metadata crawl qua API trên Mac:

| Trường | Khác | Nguyên nhân |
|---|---|---|
| Ngày nộp v1 | 0 | |
| Số Version, ngày sửa | 33 | Bài sửa sau lần crawl Mac (snapshot mới hơn) |
| Tên bài | 13 | 10 do Version mới; 3 chi tiết TeX nhỏ (sau khi đổi dấu và chữ Hy Lạp sang Unicode như API; trước đó 120) |
| `venue` | 13 | 12 bài mới có `journal-ref`; 1 bài đổi `journal-ref` |
| Tác giả | 14 | Snapshot giữ hậu tố "Jr.", "III" (API cắt hoặc để "Ryan,"); còn lại do Version mới |

## 3d. Lượt thử Colab 15/11 lần 2 (Bảo, `65f5b20`, snapshot): ĐẠT

RUN_ID `2026-11-15T064334Z_5f66486`, 2 đoạn (5.468 s), Colab 2 CPU, 12,7 GiB RAM, có S2 key.
Snapshot phủ 5.000/5.000 ID của Range. pytest exit 0 (sau khi sửa tại chỗ lỗi `tests` bị che, đã có ở `65f5b20`).

| Chỉ số | Giá trị |
|---|---|
| Publication đã thăm | 978 (957 hoàn chỉnh, 12 chờ lượt thử lại) |
| Tốc độ đo | 643,9 bài/giờ, tức 7,8 giờ/Range |
| Mô hình dự đoán | 736,5 bài/giờ, tức 6,8 giờ/Range; lệch −12,6% (ngưỡng 15%) |
| Mô hình giải thích | 97% wall time |
| arXiv | 1.542 request (1.519 file `/src/`), 2 lần 429, backoff 46 s (0,8%) |
| API Discovery | 0 request (trước đó 55 request, 43 lần 429) |
| Discovery | 11,9 s cho cả lượt |
| S2 | 16 request lô, 5 lần 429, backoff 248 s; arXiv chờ S2 20 s (0,4%) |
| Bài/giờ trung vị | 3,2 s/bài; chậm nhất 141,8 s |
| RAM | đỉnh 345 MB |
| Disk | 408 MB cho 978 bài (ước khoảng 2,1 GB/Range) |
| Checkpoint | 115 MiB cho 978 bài (ước khoảng 0,6 GB/Range, Drive giữ 2 bản) |

Validator báo `references_invalid` cho `2508.03220`: bài nằm trong 12 ID chờ lượt thử lại
(`pending_ids`), crawl chưa xong nên file references chưa có. Không phải dữ liệu hỏng; kiểm lại
khi chạy hết Range.

## 4. Chưa làm, chưa kiểm

- Tag `m1-bench-v4` (Bảo duyệt 15/11) trên nhánh này; `REF` mặc định của notebook là tag đó.
  `m1-bench-v4` = `m1-bench-v3` + ghi S2 404 thành `s2_status: not_found` (data contract C10).
  Chưa PR, chưa review, chưa merge vào `main`: link notebook `blob/main/` vẫn là bản cũ.
- Chưa chạy hết một Range trên Colab; lượt thử chỉ 2 đoạn (978/5.000 bài).
- Lô S2 bị 429 quá 30 phút thì các bài trong lô ghi lỗi 429 và được gom lại ở lượt sau
  (`--max-passes 3 --retry-delay 600` trong notebook).
