# Review schema cho Crawling → Parser

Review ngày 2026-10-16. Phạm vi: `schema.py` và hợp đồng bàn giao dữ liệu,
không triển khai crawler hoàn chỉnh. Nguồn yêu cầu:
https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/

Cập nhật sau khi tích hợp hạ tầng: module hiện nằm ở
`src/common/schema.py`, import qua `src.common.schema`. Kết quả 14 test bên
dưới là lần review ban đầu; kết quả toàn bộ test mới ở `infrastructure-review.md`.

## Kết luận

Tách schema tường minh, validation, khóa chính và Parquet I/O là nền tảng
phù hợp. Tuy nhiên schema bảng xuất cuối chưa thay thế được trạng thái tải
theo Version. Chỉ tối ưu Parquet chưa đủ để tải đúng, resume và cung cấp
đầu vào đầy đủ cho Parser.

## Lỗi đã tái hiện và sửa

| Mức | Phát hiện trên bản ban đầu | Khắc phục |
| --- | --- | --- |
| Cao | Ba cột Crawling lưu chuỗi, trái quyết định list; `split_list(join_list(['Group; Collaboration', 'B']))` làm đổi số tác giả | Dùng list<string> cho `papers.authors`, `papers.revised_dates`, `references.ref_authors`; helper cũ từ chối chuỗi không thể phục hồi |
| Cao | `from_records` bỏ trường lạ âm thầm: `titel` biến mất và `title` thành null | Báo lỗi trường lạ kèm chỉ số dòng; validate ngay sau tạo bảng |
| Cao | Ngày `2025-02-30junk` và `2025-99-99; invalid` vẫn qua validation | Kiểm tra toàn chuỗi, lịch thực và từng ngày trong list, kể cả phần tử thứ hai trở đi |
| Vừa | Cột `title` trùng được validator chấp nhận | Phát hiện tên cột trùng trước các kiểm tra khác |
| Cao | Ghi đè trực tiếp có thể làm hỏng Parquet cũ nếu ghi thất bại | Ghi file tạm cùng thư mục, flush/fsync rồi `os.replace`; dọn file tạm khi có exception |
| Vừa | Đọc một file bằng API dataset có thể suy diễn thêm partition từ thư mục `owner=...` | Dùng `ParquetFile.read()` cho hợp đồng đọc đúng một file |

`from_records` nay từ chối ngay bản ghi không hợp lệ. Crawler cần bắt lỗi
theo tác vụ/Version và lưu nguyên nhân; không để một exception làm mất cả lượt.
API response thô phải được ánh xạ thành các trường đã khai báo trước khi gọi.
`None` và `[]` của list vẫn khác nhau: chưa biết và danh sách rỗng.
Không tự chuyển metadata thiếu thành ngày giả hoặc chuỗi rỗng.

Đã thêm `.gitignore` vì `.env` trước đó xuất hiện trong file chưa được theo
dõi bởi Git. Không đọc hoặc chép giá trị bí mật để làm review.

## Phần còn thiếu trước khi chạy trên toàn range

### 1. Theo dõi đủ Version để Parser không bỏ sót

**Đề xuất, chưa thêm bảng/cột:** có manifest nội bộ theo `(arxiv_id, version)`
tách khỏi hai bảng xuất `papers`/`references`. Các trường đề xuất:

| Nhóm | Trường |
| --- | --- |
| Định danh | `arxiv_id`, `version`, `assigned_owner` |
| Nguồn | `source_url`, `fetched_at`, `local_path`, `checksum` |
| Trạng thái | `status`, `attempts`, `http_status`, `error_reason` |

Từ discovery phải biết danh sách Version dự kiến. Mỗi Version dự kiến có
một dòng ngay cả khi chưa tải được hoặc không có TeX. Phân biệt `pending`,
`success`, `retryable_error`, `unavailable`, `non_tex`; lỗi mạng không được
đổi thành `non_tex`. `success` chỉ sau khi file nguồn đã lưu và kiểm tra.
Resume kiểm tra checkpoint cùng file/checksum thực tế, không chỉ nhìn thư
mục có tồn tại hay không. Version `non_tex` được bàn giao rõ để Parser ghi
nhận kết quả rỗng thay vì bỏ qua.

Không suy ra số Version từ `len(revised_dates)` khi metadata ngày còn thiếu.
Không dùng `papers.venue` hoặc một bảng rỗng làm cờ tải thành công.

### 2. Giữ cấu trúc nguồn cho Parser

Giữ đường dẫn tương đối của từng `.tex`/`.bib` trong archive: `main.tex`
gọi `sections/intro.tex` phải còn resolve được. Không gom mọi file vào một
thư mục phẳng, không sửa nội dung nguồn. Khi trích xuất cần chặn đường dẫn
thoát thư mục và liên kết nguy hiểm, đồng thời giới hạn dung lượng giải nén.
Nhận diện tar/gzip/TeX/PDF bằng nội dung; không chỉ tin phần mở rộng hoặc
HTTP 200. Đường dẫn raw có/không có tên thành viên chưa chốt theo AGENTS.md.

### 3. Khóa hierarchy hiện có rủi ro mất thông tin

Khóa hiện tại `(arxiv_id, version, element_id)` cho phép một Element chỉ
có một dòng trong một Version. Ví dụ cùng câu `We conclude.` nằm ở hai
section: deduplicate content cho chung `element_id` nhưng cần hai parent.
Validator hiện tại sẽ từ chối hai cạnh này.

**Chưa thay khóa:** cần đối chiếu đề Parser và chốt cách biểu diễn lần xuất
hiện, thứ tự anh em và quan hệ cha trước khi viết Parser. Thêm `parent_id`
vào khóa chỉ giải quyết một phần, vẫn chưa giữ được hai lần xuất hiện giống
hệt dưới cùng parent hoặc thứ tự đọc. Cũng cần QA liên bảng cho parent tồn
tại, cùng Publication/Version và cây không có chu trình; `validate()` hiện
chỉ kiểm tra riêng bảng, chưa bảo đảm các tính chất đó.

### 4. Schema ngoài Crawling vẫn là dự thảo

`elements`, `hierarchy`, `bibtex`, `predictions`, enum Element/partition và
quy ước Element ID chưa được đối chiếu với đề tương ứng. Không coi 14 test
đạt là xác nhận bốn schema này đúng đề. Chưa đổi tên bảng, cột hoặc khóa.
`bibtex.authors` hiện giữ nguyên string dự thảo; quyết định list đã xác nhận
chỉ áp dụng cho ba cột Crawling.

## Cách tối ưu nên áp dụng ở crawler

- Resolve metadata bằng các batch ID phù hợp, cache kết quả và lưu danh
  sách Version trước khi tải source. arXiv vẫn một kết nối, cách tối thiểu
  3 giây giữa các request; tăng luồng tải không phù hợp quy tắc hiện tại.
- Cache Semantic Scholar theo Publication thay vì gọi lại cho từng Version;
  theo dõi trạng thái references riêng. Danh sách rỗng do API lỗi phải khác
  danh sách rỗng đã xác minh thành công.
- Ghi theo batch/shard, tránh mỗi bài đọc và ghi lại toàn bộ Parquet. Dùng
  checkpoint vận hành phù hợp rồi xuất Parquet cho Parser/QA. Không nạp cả
  corpus hoặc archive giải nén vào RAM chỉ để xử lý một Version.
- Schema dùng Arrow và Zstandard đã phù hợp. Validation hiện kiểm tra ngày
  duy nhất, tránh parse lại ngày lặp. Kiểm tra unique key chỉ trong từng
  bảng đầu vào; QA tổng hợp phải phát hiện trùng giữa các shard.
- Chưa benchmark trên range thật; chưa thể kết luận tốc độ/RAM tối ưu.

## Xác minh đã chạy

Môi trường: Python 3.14.3, PyArrow 23.0.1. Chạy từ root repo:

```sh
python3 -m unittest discover -s tests -v
```

Kết quả: **14 test đạt**, dữ liệu tổng hợp và file tạm. Bao gồm list round
trip, ngày sai, field lạ, cột thiếu/sai kiểu/trùng, null/khóa trùng, ID kèm
version, Parquet trong thư mục partition, lỗi ghi giữa chừng và giữ file cũ.
Đây chưa phải kiểm thử tải thật, resume thật hoặc benchmark Colab.
