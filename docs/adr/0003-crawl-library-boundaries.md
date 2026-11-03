---
status: accepted
---

# Tách Runner, đọc corpus và Export khỏi CLI và điều phối crawl

Ngày 03/11/2026, nhóm trưởng cho phép refactor khung M1 sau khi review kiến trúc.
Giữ quyết định một Engine `src/crawl/` và file là nguồn dữ liệu gốc (ADR 0001/0002).

## Vấn đề

Logic chạy Range nằm trong `scripts/`, trong khi CLI ở `src/` import ngược lại.
Reporting khởi tạo `CrawlPipeline` bằng `object.__new__` để dùng hàm private đọc
cache. Pipeline vừa điều phối mạng vừa kiểm tra cache và xuất bảng. M2 phải
import tiện ích JSON từ crawler.

## Quyết định

- `src/crawl/runner.py`: điều phối Range, retry nhiều lượt và checkpoint.
- `src/crawl/corpus.py`: `CorpusReader` chỉ đọc và xác minh metadata/references;
  nhận một view Manifest, không sửa checkpoint hoặc gọi mạng.
- `src/crawl/export.py`: tạo bảng batch và `PublicationBundle` có kiểu tường minh.
- `src/crawl/cli.py`: CLI chuẩn cho Engine; `scripts/` chỉ là entry point.
- `src/common/json_io.py`: ghi JSON nguyên tử dùng chung cho M1/M2.
- Publisher có `validate_destination()` công khai thay cho caller gọi `_info()`.

## Tương thích và giới hạn

Giữ CLI cũ, `LieuPipeline`, nhãn `engine="lieu"`, import runner từ
`scripts.crawl_range` và `storage.write_json`. Không đổi schema Parquet, raw
layout, receipt, rate limit, retry policy hoặc nội dung export. Bảng cục bộ do
export tạo vẫn chỉ chứa batch được yêu cầu. Không đổi các quy ước M2 chưa chốt.

Reporting dùng CorpusReader trực tiếp, không tạo pipeline giả. Validator vẫn
có đường kiểm tra độc lập để đưa ra diagnostics đầy đủ; không gộp máy móc các
chế độ thống kê Manifest nhanh và kiểm tra checksum.

Các bài kiểm thử tích hợp giữ lại bằng chứng resume, lỗi từng Version,
source non-TeX, xuất Parquet, upload với fake Hub và báo cáo chỉ đọc. Kiểm thử
bổ sung xác minh cache sửa đổi bị từ chối, export rỗng, JSON lỗi giữ nguyên
checkpoint trước và các entry point tương thích.
