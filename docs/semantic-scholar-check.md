# Kiểm tra API references của Semantic Scholar

Ngày kiểm tra: 2026-10-16.
Nguồn chính thức: https://api.semanticscholar.org/graph/v1/swagger.json
(được trang https://api.semanticscholar.org/api-docs/graph sử dụng).

## Đã thử thực tế

Một request không dùng API key tới
`/graph/v1/paper/ARXIV:1706.03762/references`, với
`fields=paperId,externalIds,title,authors,publicationDate`, `offset=0`,
`limit=5`, trả **HTTP 200**, 5 phần tử, `offset=0`, `next=5`.
Mỗi `data[i].citedPaper` có đủ năm trường yêu cầu. Đây là thử một trang,
không phải kiểm thử crawl hết reference, hạn mức hoặc range của người dùng.
Không lưu response thật vào repo.

## Hợp đồng cần giữ khi triển khai

- Với endpoint `/paper/{id}/references`, dữ liệu bài được trích dẫn nằm trong
  `data[i].citedPaper`. Trường yêu cầu là `title,authors,...`, không thêm tiền
  tố `references.` hay `citedPaper.`. Endpoint lấy chi tiết một paper có cách
  yêu cầu trường references khác; không dùng lẫn hai dạng response.
- Đọc arXiv ID qua `(citedPaper.externalIds or {}).get('ArXiv')` và giữ ID
  dạng chuỗi. Mẫu hiện tại dùng ID không kèm Version; vẫn phải validate đầu
  vào, không suy ra API luôn bảo đảm mọi ID hợp lệ từ một mẫu.
- Năm reference của mẫu này đều có ArXiv ID. Mẫu không chứng minh tỉ lệ
  reference thiếu ArXiv trong toàn corpus. Khi gặp mục không có ArXiv thì
  chỉ loại khỏi bảng xuất `references`, vẫn giữ metadata thô cục bộ theo đề.
- Xử lý an toàn khi `citedPaper`, `externalIds` hoặc `authors` null/thiếu;
  không biến lỗi HTTP/JSON thành kết quả không có reference.
- `ref_authors` lấy từ tên của tác giả **trong citedPaper**, không lấy authors
  trong `citingPaperInfo` của bài đang truy vấn.
- Theo OpenAPI, `limit` mặc định 100, tối đa **1000** cho endpoint references.
  Không được giả định luôn một trang. Khi response có `next`, dùng đúng giá
  trị này làm `offset` lần sau; dừng khi thiếu `next` (hoặc null được xử lý
  phòng thủ). Đừng dừng vì trang sau lọc còn 0 reference có ArXiv.
- `paperId` đã xuất hiện trong mẫu ban đầu dù không xin rõ. Bộ fields xin
  rõ `paperId,externalIds,title,authors,publicationDate` đã thử thành công.

## Ánh xạ vào schema hiện tại

| Cột references | Nguồn |
| --- | --- |
| `arxiv_id` | ID Publication đang truy vấn; mẫu thử `1706.03762` |
| `ref_arxiv_id` | `citedPaper.externalIds.ArXiv` |
| `ref_title` | `citedPaper.title` |
| `ref_authors` | Danh sách `name` từ `citedPaper.authors` |
| `ref_s2_id` | `citedPaper.paperId` |
| `ref_submission_date` | Ngày nộp v1 từ metadata arXiv đã xác minh; null nếu chưa có |

OpenAPI định nghĩa `publicationDate` là ngày xuất bản theo Semantic Scholar,
không cam kết là ngày nộp arXiv. Ví dụ trong response vừa thử,
`ref_arxiv_id=1703.10722` có `publicationDate=2017-02-17`; không thể mặc nhiên
coi đó là ngày nộp arXiv của ID tháng 2017-03.

Vì vậy không tự gán `publicationDate` vào `ref_submission_date`. Giữ trường
đó trong metadata thô, cache metadata arXiv theo ID và bổ sung ngày v1 khi
có nguồn xác minh; nếu nhóm muốn nghĩa khác thì cần chốt lại hợp đồng.
Không tự dựng ngày từ `year` và không tự thêm cột vào schema đã chốt.
