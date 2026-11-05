# Chạy report_m1 cho dữ liệu của Hải

Chạy tại root repo, sau khi crawler đã dừng:

```powershell
.\.venv\Scripts\python.exe -X utf8 -u -m scripts.report_m1 --cache data/benchmark-ngochai06 --start 2412.08848 --end 2412.13847 --member hai --workers 16 --output benchmarks/hai-validated.json
```

Đầu vào là cache đã gom và có cả hai bảng cuối trong `tables/`. Không trỏ
vào riêng `data/local-sequential/arxiv` hoặc `s2` khi muốn kiểm tra cả pipeline.
Output JSON phải nằm ngoài cache. Lệnh không tải arXiv/S2, không upload và
không sửa payload/manifest; chỉ tạo lock file và ghi file báo cáo đã chỉ định.

Công cụ lấy hợp đồng snapshot từ
`origin/feat/m1-report:src/reporting/m1.py`. Entry point local bổ sung Range
và member tường minh thay cho Range 2508 của Bảo cố định trong script gốc.
`--workers` chỉ là số luồng I/O kiểm tra checksum trên đĩa, không phải worker crawl.
Không kéo các thay đổi crawler khác vào nhánh Hải.

Các trường cần gửi nhóm trưởng:

- `range`: phải là 2412.08848–2412.13847.
- `checks.tables.papers.valid`, `checks.tables.references.valid`: đọc đúng schema.
- `duplicate_keys`, `outside_range`: phải bằng 0 nếu bảng không có các lỗi đó.
- `provenance`: số file đầu vào đã kiểm tra và hash bằng chứng.
- `counts.complete` cùng `failures`: mức hoàn tất và phần còn thiếu của corpus.

`valid=true` của hai bảng không có nghĩa toàn bộ 5.000 ID đã hoàn tất. Các
Version thiếu source hoặc Publication thiếu S2 vẫn nằm trong `counts`/`failures`.
Script trả exit 1 nếu bảng lỗi schema, có khóa trùng hoặc ID ngoài Range; còn
thiếu dữ liệu không tự làm bảng đã xuất sai schema. Trước khi gửi, xem cả counts.

Lần tổng hợp trước ghi nhận 4.775 Publication hoàn chỉnh, 4.775 dòng papers,
81.847 dòng references. Lần chạy mới phải lấy kết quả in ra thực tế, không
điền cứng các số này nếu cache đã thay đổi. Không dùng benchmark mẫu 10 ID
thay cho validated snapshot toàn Range.
