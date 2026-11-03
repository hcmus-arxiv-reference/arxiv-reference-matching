---
status: accepted
---

# File trên đĩa là nguồn dữ liệu gốc của corpus

Ba cách lưu đã xuất hiện trong nhóm: thư mục file + manifest JSONL (main, Nghiêm), SQLite (Hải) và cơ sở dữ liệu SQL (Minh). Chọn **file làm nguồn gốc**: mỗi Publication một thư mục, mỗi Version một thư mục con chứa `.tex/.bib` và metadata. Manifest JSONL ghi trạng thái để resume. `papers`/`references` chỉ là bảng Parquet **xuất ra** từ file. Lý do: đề Crawling gợi ý đúng cách tổ chức này và chấm theo mức tuân thủ quy ước; Parser ở Milestone 2 đọc trực tiếp `.tex`; kiểm tra bằng mắt và đo `du` trên Colab đơn giản.

## Considered Options

- **SQLite**: resume có transaction và truy vấn tiện, nhưng là một file nhị phân lệch khỏi quy ước của đề, và Parser phải xuất ra file trước khi đọc. Có thể dùng làm chỉ mục phụ, không làm nguồn gốc.
- **SQL server**: cần dịch vụ DB trên Colab; schema hiện tại lưu `authors` dạng TEXT và chỉ một `revised_date`, trái với kiểu list of strings đã chốt.

## Consequences

- An toàn resume dựa vào ghi file atomic (tạm rồi đổi tên), checksum và manifest, không dựa vào transaction.
- Đóng góp của Hải (tải theo chunk, bundle Kaggle) và Minh (S2 pipeline có test) được giữ ở Stage tương ứng, không giữ phần lưu trữ.
