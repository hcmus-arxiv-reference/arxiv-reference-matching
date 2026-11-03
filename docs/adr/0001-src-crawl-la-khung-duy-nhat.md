---
status: accepted
---

# `src/crawl/` là khung crawler duy nhất

Sau khi merge nhánh Liễu, `origin/main` có framework `CrawlPipeline` (`src/crawl/`, tách theo Stage) và script crawler standalone `src/milestone1_crawler.py` (799 dòng). Script này không định nghĩa lớp `LieuPipeline`. Nhóm đã crawl bằng 5 pipeline khác nhau và cần ghép phần tốt nhất của từng người. Việc ghép theo Stage chỉ làm được khi có một khung với ranh giới Stage rõ ràng, nên chọn `src/crawl/` làm khung duy nhất. Batch discovery và S2 chạy đồng thời của script standalone sẽ được chuyển vào khung thành một cách cài đặt Discovery và một chiến lược của Runner, sau đó script standalone có thể bị xóa.

## Bối cảnh bổ sung 2026-11-01

Ngày 25/10, nhóm đã chọn script standalone của Liễu làm hướng phát triển M1 (ghi ở
`docs/m1-standalone-trial.md` trên nhánh `backup/local-2026-10-25`). Lúc chốt ADR này
ngày 31/10, chưa ai xét tới quyết định đó. Sau khi xét lại, quyết định của ADR này được
giữ nguyên, vì:

- Dữ liệu Range của Bảo (2,2 GB, 4.941/5.000 Publication hoàn chỉnh), validator và
  Export đều theo layout của `src/crawl/`; standalone không xuất Parquet.
- Lượt thử standalone ngày 25/10 trên 59 Publication còn thiếu phục hồi được 0 bài.
- Điểm mạnh của Liễu đã chạy được trong khung qua `src/crawl/lieu_pipeline.py`
  (`BatchedDiscovery`, S2 chạy song song).

Vì vậy discovery theo lô và tải references song song trở thành **cách cài đặt mặc định**
của Stage Discovery và Runner, đặt tên theo kỹ thuật; cải tiến HTTP của Liễu (HTTP Range,
giới hạn thời gian theo dung lượng, chờ theo Retry-After) được chuyển vào HTTP client
của khung. Script standalone không lên `main`; bản cuối của Liễu được giữ bằng tag
`lieu-standalone-final`.

## Considered Options

- **Standalone làm Engine (quyết định 25/10)**: đã chạy được toàn Range, có batch discovery,
  S2 chạy đồng thời và cải tiến HTTP mới nhất. Nhưng các Stage và ghi log nằm chung trong
  script nên khó thay riêng từng phần; ngoài ra phải viết thêm Export, sửa validator và
  chuyển 2,2 GB dữ liệu sang layout của nó, trong khi chưa có bằng chứng hiệu quả hơn.
- **Giữ cả hai engine**: không tốn công chuyển, nhưng mọi sửa lỗi phải làm hai lần, và benchmark không biết đang đo engine nào.

## Consequences

- Script standalone ghi vào `data/<safe-publication-id>/v<n>/` và dùng `done.json`/run log; `src/crawl/` dùng `data/raw/<publication-key>/v<n>/`, manifest và Parquet exports. Có thể tái sử dụng dữ liệu file sau khi viết và kiểm tra bước migration; tương thích hiện chưa được xác minh.
- `make_stats` phải đọc được `crawl.jsonl` của khung chứ không chỉ log gốc của Liễu.
