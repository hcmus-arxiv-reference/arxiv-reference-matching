# Dự án đang làm gì và đang ở đâu? — 10/11/2026

## Mục đích

Dự án biến bài báo khoa học ở dạng LaTeX thành dữ liệu có cấu trúc, rồi tìm
đúng bài báo tương ứng với từng mục tài liệu tham khảo. Đây là bài toán
**ghép thực thể**: cùng một bài có thể xuất hiện dưới nhiều cách viết tên,
viết tắt tác giả hoặc thiếu thông tin.

Ví dụ minh họa: trong LaTeX có một mục `Smith et al., A method, 2020`.
Semantic Scholar cung cấp nhiều bài được trích dẫn, mỗi bài có tên, tác giả
và định danh. Pipeline cần xác định mục này tương ứng với bài nào, rồi trả
về danh sách ứng viên được xếp hạng. Mục tiêu cuối không chỉ là tải bài hay
tách văn bản; phải đi hết từ thu thập, làm sạch đến mô hình và đánh giá.

## Ba chặng

```text
Range ID của mỗi thành viên
  → M1: metadata + source từng Version + references từ Semantic Scholar
  → M2: cây nội dung + nội dung đã chuẩn hóa + BibTeX đã khử trùng lặp
  → M3: nhãn đúng/sai + đặc trưng + mô hình xếp hạng
  → sáu bảng Parquet + báo cáo Jupyter Book + poster
```

**M1 — Crawling:** biết có những Publication nào, bao nhiêu Version, tải
source từng Version và thông tin các bài được trích dẫn. Có checkpoint để
chạy tiếp sau lỗi, kiểm checksum để biết file còn nguyên, và thống kê độ
bao phủ. Một Version không có TeX vẫn được ghi nhận; lỗi mạng không đồng
nghĩa bài không có TeX.

**M2 — Parsing:** hiểu cấu trúc LaTeX. Một bài có thể chia thành nhiều file;
phải tìm file gốc, theo input/include rồi dựng document → mục → câu/công
thức/hình. Giữ lời cảm ơn, phụ lục; tách danh mục tham khảo ra xử lý riêng.
Sau đó chuẩn hóa nội dung, hợp các mục BibTeX trùng và dùng chung Element
giống nhau giữa các Version. Không dùng LLM hay mô hình pretrained trong Parser.

**M3 — Matching:** lấy BibTeX của M2 ghép với references của M1, trong cùng
Publication. Tạo nhãn, chia train/validation/test theo bài, tạo đặc trưng,
huấn luyện mô hình và xếp hạng tối đa năm ứng viên. Đề dùng MRR@5: đáp án
đúng hạng 1 được 1 điểm, hạng 2 được 1/2, ngoài top 5 được 0.

## Trạng thái có bằng chứng

| Phần | Hiện trạng trên main `12ffdd9` | Còn cần |
|---|---|---|
| Hạ tầng | Có schema sáu bảng, cấu hình, công cụ HF, đo tài nguyên và kiểm dữ liệu | Tiếp tục kiểm bất biến liên bảng khi tích hợp |
| M1 | `src/crawl/` là Engine chung; có lệnh crawl, resume, kiểm corpus, báo cáo/benchmark | Chạy benchmark của từng thành viên và xử lý/giải thích dữ liệu thiếu |
| M2 Source | Có assembler và CLI; nhánh issue #30 bổ sung sửa lỗi và golden | Đo lại trên Range Bảo, review/merge thay đổi |
| M2 Structure/Leaves/BibTeX/Export | Đã có phân công và hợp đồng đề xuất; main chưa có các module này | Merge types, triển khai từng gói, chạy mẫu và tích hợp |
| M3 | README ghi chưa bắt đầu; chưa thấy module Matching trên main | Nhãn, đặc trưng, mô hình, đánh giá |

README dẫn snapshot lịch sử 25/10: **4.941/5.000 Publication của Range Bảo
hoàn chỉnh**, 59 còn thiếu. Đây là số đo trong tài liệu lịch sử, không phải
lượt kiểm lại dữ liệu hôm nay và không đại diện độ hoàn thành của cả nhóm.
Issue #30 ghi Source đạt 75,9% `ready` ở lượt 06/11; lần sửa này chưa đo lại
tỉ lệ trên Range đó. Code tồn tại, test đạt và corpus đạt tiêu chí là ba
loại bằng chứng khác nhau.

## Công việc của bạn nằm ở đâu?

Theo issue #30, bạn phụ trách đầu M2: **Source + Structure**.

1. Nhận thư mục của một Version đã được crawler xác minh.
2. Trả `SourceBundle`: văn bản gộp, file đã dùng, vị trí nguồn và cảnh báo.
3. Trả `StructureTree`: chương/mục và các Block chưa tách thành câu.
4. Trả `BibSource`: file BibTeX liên quan, bibitem và các key được trích dẫn.

Nghiêm nhận cây để tách câu/công thức/hình. Hải nhận BibSource để chuẩn hóa
và hợp BibTeX. Minh tích hợp, tạo ID, khử trùng lặp, xuất bảng và chạy batch.
Nếu Source ghép sai hoặc Structure nhận nhầm References, các bước sau sẽ
xử lý nhầm nội dung; vì vậy golden và ánh xạ vị trí nguồn rất quan trọng.

Trong lần làm này, bạn chọn **Source và golden trước**, chờ `types.py`
được merge. Chi tiết thay đổi và phần còn mở ở
[bàn giao issue #30](issue30-source-handoff.md).

## Sáu bảng cuối cùng

| Bảng | Trả lời câu hỏi |
|---|---|
| `papers` | Bài này tên gì, ai viết, nộp/sửa khi nào? |
| `references` | Bài này trích dẫn những bài có arXiv ID nào theo metadata thu thập? |
| `elements` | Các phần nội dung phân biệt của bài là gì? |
| `hierarchy` | Trong mỗi Version, phần nào thuộc phần nào? |
| `bibtex` | Các mục tài liệu tham khảo đã chuẩn hóa của bài là gì? |
| `predictions` | Mô hình dự đoán mục BibTeX tương ứng với những arXiv ID nào? |

Đích tiếp theo là nối được các gói M2 trên bộ mẫu 100 bài, kiểm dữ liệu và
đo chất lượng; sau đó mới mở rộng toàn Range, benchmark, và dùng kết quả
cho Matching. Lịch nhóm hiện đặt tích hợp mẫu vào 19/11, kiểm tiêu chí mẫu
22/11, toàn Range/benchmark 25/11 và viết M2 cho báo cáo 28/11. Đây là kế
hoạch, chưa phải các mốc đã đạt.

Nguồn: [README](../README.md), [hợp đồng dữ liệu](data-contract.md),
[phân công M2](m2-cong-viec.md), [snapshot M1](m1-standalone-trial.md),
[đề Crawling](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/),
[đề Parsing](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/parsing/),
[đề Matching](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/matching/).
