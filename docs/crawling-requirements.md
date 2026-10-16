# Đối chiếu đề Milestone 1 — Crawling

Nguồn: https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/

Đọc ngày 2026-10-16. Đây là ghi nhận yêu cầu, không phải kết quả thực nghiệm.
Người dùng yêu cầu bắt đầu với Crawling; Parsing và Matching chưa được đối chiếu.

## Hai bảng được quy định trong trang Crawling

### `papers`

| Cột | Kiểu theo đề | Ràng buộc ghi rõ trong đề |
| --- | --- | --- |
| `arxiv_id` | string | non-null |
| `title` | string | |
| `authors` | list of strings | |
| `submission_date` | ISO string | |
| `revised_dates` | list of strings | |
| `venue` | string | nullable |

### `references`

Mỗi dòng là một reference có arXiv ID và Publication trích dẫn nó.

| Cột | Kiểu theo đề | Ràng buộc ghi rõ trong đề |
| --- | --- | --- |
| `arxiv_id` | string | non-null; bài trích dẫn |
| `ref_arxiv_id` | string | non-null; bài được trích dẫn |
| `ref_title` | string | |
| `ref_authors` | list of strings | |
| `ref_submission_date` | string | |
| `ref_s2_id` | string | |

Không tự bổ sung quy định non-null cho những cột đề không nói rõ.
Giữ nguyên định danh arXiv cũ như `hep-th/9901001`.

## Yêu cầu thu thập

- Resolve ID được giao để xác định metadata và số Version. Theo đề, hậu tố
  Version mới nhất từ API quyết định danh sách `v1` đến `vN` cần tải.
- Tải riêng từng Version qua `https://export.arxiv.org/src/{arxiv_id}v{n}`.
- Một kết nối một lúc, cách tối thiểu 3 giây giữa các request arXiv,
  User-Agent mô tả dự án kèm địa chỉ liên hệ theo AGENTS.md.
- Nhận diện định dạng source; chỉ trích xuất `.tex` và `.bib`, không sửa nội
  dung của chúng. Giữ lệnh hình/bảng trong TeX, bỏ file ảnh.
- Version chỉ có PDF/docx hoặc không có TeX vẫn giữ bản ghi rỗng.
- Lấy reference metadata bằng Semantic Scholar ở cấp Publication. Giữ tất
  cả reference cục bộ; khi xuất bảng `references`, chỉ giữ mục có arXiv ID.
- Corpus là đầu vào cho các milestone sau; Milestone 1 không nộp dữ liệu.

## Báo cáo và đo lường

Jupyter Book ở repo riêng, public và host GitHub Pages. Bảng và hình sinh
khi compile. Báo cáo gồm số bài thành công, tỉ lệ thành công, dung lượng
trước/sau bỏ ảnh, số reference trung bình, tỉ lệ lấy reference metadata,
thời gian mỗi bài/trung bình/end-to-end và discovery, RAM tối đa/trung bình,
disk tối đa và dung lượng đầu ra. Benchmark cuối trên Colab CPU.

## Quyết định đã chốt và các điểm còn mở

1. `AGENTS.md` nói 6 bảng; README hiện nói 7 bảng với tên khác. Trang
   Crawling chỉ xác nhận hai bảng ở trên, chưa đủ kết luận schema toàn dự án.
2. **Đã được người dùng xác nhận ngày 2026-10-16:** giữ đúng list of strings
   cho `papers.authors`, `papers.revised_dates`, `references.ref_authors`
   (`pyarrow.list_(pyarrow.string())`), không chuyển thành chuỗi hoặc JSON blob.
   AGENTS.md đã được cập nhật cho phép ba cột list này.
3. Chưa có `CONTACT_EMAIL` cho User-Agent; chưa gửi request tới arXiv.
   Đây là email cá nhân, sinh viên hoặc email chung của nhóm có người theo
   dõi, dùng để arXiv liên hệ người vận hành. Không cần thông tin đăng nhập
   hay quyền truy cập hộp thư. Địa chỉ thật chỉ cấu hình cục bộ qua môi trường
   hoặc `.env` được gitignore; `.env.example` chỉ chứa `CONTACT_EMAIL=`.
4. Chưa chọn hoặc tải bộ mẫu. Có thể bắt đầu kiểm tra 5 ID đầu range:
   `2508.02872`–`2508.02876`; đây mới là ứng viên, chưa xác minh source hoặc
   tính đa dạng về Version/cấu trúc.
5. Chưa đối chiếu trang Parsing và Matching, chưa đạt DoD giai đoạn 0.

Phạm vi agent theo AGENTS.md vẫn là hạ tầng và Parser; crawler hoàn chỉnh
và Semantic Scholar thuộc thành viên khác. Công cụ tải mẫu nằm trong phạm vi.
