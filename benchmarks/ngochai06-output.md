# Bàn giao output crawl của ngochai06

- File lịch sử 5.000 ID: `benchmarks/ngochai06-historical5000.json`, theo mẫu `docs/benchmark/benchmark.template.json`.
- File nộp chính `benchmarks/ngochai06.json` hiện là lượt đo mới **10 ID**;
  xem `docs/benchmark/ngochai06-sample10.md`. Không ghép số đo hai lượt.
- Nhánh crawl: `Hai_crawler`; commit trước merge: `11bd1ebe74eb229482c4a23c8d6c691f082c2e78`.
- Range: **2412.08848–2412.13847**, gồm 5.000 ID.
- Link output do thành viên cung cấp: [Google Drive](https://drive.google.com/drive/folders/1U7g1ln7nMlJQAVy-o75H5BzA8xBp23hD?usp=sharing).
- Snapshot đếm trên máy: `data/benchmark-ngochai06/`.
- Nguồn snapshot: `data/local-sequential/arxiv/` và `data/local-sequential/s2/`.
- Bằng chứng kiểm tra: `data/benchmark-audit/validation-report.json`.

## Phạm vi số liệu

Kết quả kiểm tra ngày 03/11/2026:

- Đã thử 5.000 ID; tìm được metadata hợp lệ cho 4.985 Publication.
- **4.775 Publication đủ mọi Version và S2**.
- 8.086 Version dự kiến, 7.900 Version hợp lệ (bao gồm 504 non-TeX),
  còn 186 Version thiếu/chưa hợp lệ.
- Theo bộ đếm validator, 4.917 Publication có metadata hợp lệ và S2 thành công;
  172.954 bản ghi S2 thô, 84.719 bản ghi có arXiv ID trước khử trùng lặp.
- Output snapshot: 4.018.839.158 byte (3.832,664 MiB); đây là dung lượng cuối,
  không phải peak disk, và không cộng các bản cache trùng lặp khác trên máy.
- Validator có 68 phát hiện `references_invalid`, do thiếu cache S2; kết quả
  `ok=false`, chưa hoàn tất toàn Range. Không có `counter_mismatch`.

Lưu ý bộ đếm S2 trong validator chỉ xét Publication đã có metadata hợp lệ.
Manifest worker S2 ghi 4.932 thành công trên toàn bộ 5.000 ID; chênh lệch 15
nằm ở các ID chưa có metadata hợp lệ. Không cộng hai số này hoặc dùng số dòng
Parquet đã khử trùng lặp thay cho số reference thô.

Đây là thống kê offline từ các lượt crawl/resume đã có. Không chạy lại crawl,
không đo tốc độ hoặc RAM mới, không đổi code crawler. Các số không có nguồn đo
đầy đủ giữ `null`. `versions_failed` đếm Version dự kiến nhưng chưa có cache hợp lệ,
không phải số lần request lỗi. Các lỗi S2 còn lại được ghi trong báo cáo validator;
không coi output là đã hoàn tất toàn Range.

Snapshot dùng layout `raw/`, `metadata/`, `references/`, `manifests/crawl.jsonl`.
File dữ liệu dùng hard link để tránh nhân đôi nhiều GB; không chỉnh sửa nội dung
file trong snapshot. Manifest được chép độc lập từ trạng thái cuối của hai worker.
Snapshot chưa có hai bảng Parquet cuối; bảng từng dịch vụ còn ở
`data/local-sequential/{arxiv,s2}/tables/`, không coi là bảng cho tập đã đủ cả hai phần.

Link Drive chưa được đối chiếu nội dung với snapshot này. Trước khi gửi Bảo,
đảm bảo người nhận có quyền đọc và bản upload đúng output được thống kê.

## Giới hạn môi trường kiểm tra

Tại thời điểm thu thập thống kê, lần pull dừng ở xung đột merge của AGENTS.md, requirements.txt,
scripts/crawl_range.py và ba module crawl. Không sửa xung đột để tránh thay đổi
nhánh crawler trong yêu cầu này. Validator mới được đọc từ file đã pull,
dependencies lấy từ commit crawl ở trên và nạp qua ZIP riêng trong thư mục audit.
Vì vậy chưa thể chạy nguyên lệnh validator bằng các module đang có conflict.

Sau đó người dùng yêu cầu bỏ phần code vừa pull: đã sao lưu ở
`data/pull-backup-2026-11-03/`, hủy merge, khôi phục code crawler của HEAD và giữ
các tài liệu trong docs. Không còn merge conflict. Lượt đo mới 10 ID được ghi
riêng ở `benchmarks/ngochai06-sample10.json`; không dùng các số đo đó thay cho
thời gian/RAM chưa được ghi nhận của lượt 5.000 ID này.
