# Hướng dẫn đóng góp

Cách làm việc chung với repo này: cài đặt, lấy dữ liệu, tạo nhánh, commit, mở PR, review.
Việc cụ thể của M2: [`docs/m2-cong-viec.md`](docs/m2-cong-viec.md).

## 1. Cài đặt lần đầu

```sh
git clone https://github.com/hcmus-arxiv-reference/arxiv-reference-matching.git
cd arxiv-reference-matching
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

Trên Windows (PowerShell), thay `.venv/bin/python` bằng `.venv\Scripts\python.exe`.
Nếu đường dẫn thư mục repo có dấu `:`, tạo virtualenv ở chỗ khác (xem `README.md`).

Copy `.env.example` thành `.env` rồi điền giá trị của bạn: `MEMBER_NAME`, `CONTACT_EMAIL`,
`HF_TOKEN` (token Hugging Face của chính bạn), `HF_REPO_ID`. File `.env` đã nằm trong
`.gitignore`. **Không commit `.env`, không gửi token qua chat.**

## 2. Lấy dữ liệu

Corpus M1 nằm trên dataset Hugging Face private của nhóm: `raw/<member>/<key>/v<n>/` cho file
thô, `tables/<member>/` cho bảng. Cần được mời vào organization trên Hugging Face mới đọc được.

- Viết code và test: **dùng golden fixture** trong `tests/fixtures/m2/`, không cần corpus.
- Đánh giá trên bộ mẫu 100 bài: tải theo plan mà Minh tạo (lệnh ghi trong `docs/m2-cong-viec.md`
  khi có).
- Dữ liệu tải về để trong `data/`. Thư mục này đã nằm trong `.gitignore`.

## 3. Nhánh

- Luôn tạo nhánh mới **từ `main` mới nhất**, không làm tiếp trên nhánh crawler cũ:
  ```sh
  git fetch origin
  git switch -c feat/m2-<gói> origin/main
  ```
  Tên gói: `structure` (Liễu), `leaves` (Nghiêm), `bibtex` (Hải), `export` (Minh).
  Việc nhỏ ngoài gói: `fix/<mô tả>`, `docs/<mô tả>`.
- Không push thẳng lên `main`. Mọi thay đổi vào `main` đi qua PR.
- Cập nhật nhánh với `main` ít nhất mỗi ngày làm việc:
  ```sh
  git fetch origin
  git merge origin/main
  ```
  Có xung đột thì sửa, chạy lại test rồi mới push.

## 4. Commit

- Nhỏ và thường xuyên: mỗi commit làm một việc, test vẫn xanh. Lịch sử commit là một phần điểm.
- Thông điệp theo dạng `<loại>(<phạm vi>): <mô tả>`, ví dụ:
  - `feat(parse): split sentences outside math and URLs`
  - `fix(parse): treat \iff as a math symbol, not a conditional`
  - `test(parse): add hard-sentences golden case`
  - `docs(m2): record decision on enumerate kind`

  Loại: `feat`, `fix`, `test`, `docs`, `refactor`, `chore`.
- Trước khi commit, kiểm tra không có file thừa:
  ```sh
  git status
  git diff --staged --stat
  ```
  Không bao giờ commit: `data/`, `*.parquet`, `.tex` thật lấy từ corpus, `.env`, token.

## 5. Pull request

1. Mở PR **sớm** ở dạng Draft ngay khi có commit đầu tiên, để nhóm thấy hướng làm.
2. Điền đủ mẫu PR. Nhóm trưởng không review PR thiếu mục:
   - output `pytest -q`;
   - ô "Xong khi" của gói đã đạt, kèm số đo;
   - `metrics/<gói>.json` trên bộ mẫu (từ mốc 19/11);
   - PR này không làm gì (phạm vi).
3. PR nhỏ: dưới khoảng 400 dòng code, không tính fixture. Lớn hơn thì tách.
4. Không sửa `src/parse/types.py` hay `src/common/schema.py` trong PR của gói. Cần đổi thì mở PR
   riêng, ghi lý do và ảnh hưởng tới gói khác.
5. Chuyển từ Draft sang Ready khi CI xanh. Gắn nhóm trưởng làm reviewer.
6. Sửa theo review bằng commit mới, không force-push lên nhánh đang review.
7. Nhóm trưởng merge sau khi duyệt. Merge xong thì xóa nhánh.

## 6. Issue và tiến độ

- Mỗi gói có một issue, checklist là mục "Xong khi" trong `docs/m2-cong-viec.md`.
- Tích ô khi PR chứng minh được ô đó đã merge, không tích trước.
- Trễ mốc: comment vào issue **trước** ngày mốc, ghi lý do và ngày dự kiến.
- Gặp vấn đề cần quyết định chung (đổi kiểu dữ liệu, thêm thư viện): mở issue riêng, gắn nhãn
  `decision`, không tự quyết trong PR.

## 7. Quy tắc riêng cho Parser (M2)

- Không dùng LLM hay mô hình pretrained.
- Output tất định: cùng input ra cùng output từng byte.
- Không sửa tay dữ liệu. Trường hợp không xử lý được thì ghi log kèm mã lỗi.
- Test chạy offline, không cần mạng hay corpus.
- Thêm thư viện vào `requirements.txt` phải ghi lý do trong PR.
- Tài liệu online dùng để tham khảo thì ghi link trong docstring.
