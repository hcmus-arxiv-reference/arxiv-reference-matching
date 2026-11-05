# Kết quả thu thập — Hải

Nguồn cấu trúc: [Kết quả thu thập của nhóm](https://hcmus-arxiv-reference.github.io/Jupyter-Notebook-report-for-mile1/ket-qua).
Số liệu lấy từ cache crawler `Hai_crawler`, Range **2412.08848–2412.13847**,
kiểm tra lại ngày 05/11/2026. Đây là toàn Range 5.000 ID, không phải mẫu 10 bài.
File máy đọc được: [hai-summary.json](hai-summary.json), theo snapshot `format: 1`
mà `m1/m1data.py` của báo cáo đang đọc.

## Publication và Version

- Publication tìm thấy: **4.985/5.000 (99,70%)**.
- Publication hoàn chỉnh: **4.775/5.000 (95,50%)**. Hoàn chỉnh nghĩa là đủ mọi
  Version đã xác minh và lấy S2 thành công; còn 225 ID chưa đạt điều kiện này.
- Version kỳ vọng trên các Publication tìm thấy: **8.086**,
  trung bình **1,62 Version/Publication**.
- Source TeX: **7.396**; non-TeX: **504**; tổng hợp lệ: **7.900/8.086 (97,70%)**.
- Không tải được (404/410): **29**; lỗi tải/chưa hợp lệ: **157**; chưa thử: **0**.
  Số Version của 15 ID chưa có metadata hợp lệ chưa xác định, không coi là 0.
- Phân bố số Version của Publication nằm trong `versions_distribution` của JSON.

## Kích thước source

- Tổng TeX/BibTeX giữ lại ở các Version hợp lệ: **3.816.242.614 byte**.
- Với **4.775 Publication hoàn chỉnh**, trung bình sau khi bỏ hình:
  **793.990,42 byte/bài (0,794 MB)**; trung vị **129.160 byte**;
  lớn nhất **192.700.276 byte**.
- Tổng dung lượng source giữ lại của các bài hoàn chỉnh: **3.791.304.238 byte**.
- Kích thước trước bỏ hình và tỷ lệ giảm của toàn Range **chưa được đo**.
  Không dùng số của lượt 10 bài để thay vào đây. Đơn vị MB trong phần này là
  1.000.000 byte, đúng cách trình bày trên trang báo cáo.

## References

- Thành công: **4.917/4.985 (98,64%)** Publication đã có metadata hợp lệ;
  trong đó **1.121 bài** được S2 trả về danh sách rỗng hợp lệ.
- Có **172.954 Reference thô**, trung bình **35,17/bài thành công**;
  trung vị **32**, lớn nhất **428**.
- Bản ghi có arXiv ID trước dedup: **84.719/172.954 (48,98%)**;
  sau dedup cũng là **84.719** cặp, gồm **4.563** cặp có arXiv ID dạng cũ.
- Biểu đồ phân bố có thể dựng từ `references.histogram` trong JSON;
  đây là phân bố số Reference thô, không phải số dòng Parquet.
- Cache worker S2 có thêm 15 kết quả thành công ở các ID thiếu metadata.
  Chúng không được cộng vào tỷ lệ 4.917/4.985 theo hợp đồng snapshot của báo cáo.

## Kiểm tra bảng xuất ra

- `papers.parquet`: **4.775 dòng**, đúng schema, **0 khóa trùng**, **0 ID ngoài Range**.
- `references.parquet`: **81.847 dòng**, đúng schema, **0 khóa trùng**, **0 ID ngoài Range**.
- Bảng cuối chỉ gồm Publication hoàn chỉnh nên số dòng references nhỏ hơn
  84.719 cặp của toàn bộ các Publication lấy S2 thành công.
- Đã kiểm tra lại checksum source, metadata, cache S2 và hai bảng được xuất
  từ dữ liệu có sẵn. Danh sách lỗi còn lại nằm trong `failures` của JSON.
- Output đầy đủ và hai Parquet ở `data/benchmark-ngochai06/`. Chỉ xuất summary
  và bảng từ cache; không gọi API crawl lại trong lần tổng hợp này.

Để đưa vào repo báo cáo, chép `hai-summary.json` thành
`data/m1/snapshots/hai.json`. Không thay bằng `benchmarks/hai.json` vì file đó
là benchmark mẫu 10 ID, dùng cấu trúc và phạm vi khác. Không điền thời gian/RAM
của mẫu 10 bài vào benchmark toàn Range chưa được đo.
