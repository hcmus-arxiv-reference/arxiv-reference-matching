---
status: accepted
---

# `src/crawl/` là khung crawler duy nhất

Sau khi merge nhánh Liễu, `origin/main` có framework `CrawlPipeline` (`src/crawl/`, tách theo Stage) và script crawler standalone `src/milestone1_crawler.py` (799 dòng). Script này không định nghĩa lớp `LieuPipeline`. Nhóm đã crawl bằng 5 pipeline khác nhau và cần ghép phần tốt nhất của từng người. Việc ghép theo Stage chỉ làm được khi có một khung với ranh giới Stage rõ ràng, nên chọn `src/crawl/` làm khung duy nhất. Batch discovery và S2 chạy đồng thời của script standalone sẽ được chuyển vào khung thành một cách cài đặt Discovery và một chiến lược của Runner, sau đó script standalone có thể bị xóa.

## Considered Options

- **Giữ script standalone làm khung**: đã chạy được toàn Range, có batch discovery và S2 chạy đồng thời tải source, nhưng các Stage và ghi log nằm chung trong script nên khó thay riêng từng phần.
- **Giữ cả hai engine**: không tốn công chuyển, nhưng mọi sửa lỗi phải làm hai lần, và benchmark không biết đang đo engine nào.

## Consequences

- Script standalone ghi vào `data/<safe-publication-id>/v<n>/` và dùng `done.json`/run log; `src/crawl/` dùng `data/raw/<publication-key>/v<n>/`, manifest và Parquet exports. Có thể tái sử dụng dữ liệu file sau khi viết và kiểm tra bước migration; tương thích hiện chưa được xác minh.
- `make_stats` phải đọc được `crawl.jsonl` của khung chứ không chỉ log gốc của Liễu.
