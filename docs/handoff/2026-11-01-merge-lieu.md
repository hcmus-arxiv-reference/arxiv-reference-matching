# Handoff 2026-11-01: ghép nhánh Liễu và bản local của Bảo vào `main`

Tài liệu cho phiên mới (agent bất kỳ) tiếp nhận việc phân tích và lên kế hoạch merge.
Đọc kèm `AGENTS.md`, `CONTEXT.md`, `docs/adr/` và
`docs/handoff/2026-10-31-architecture-grilling.md` (quyết định Q1–Q16).

## Việc của phiên này

1. **Grill trước khi code.** Hỏi Bảo từng vòng, có đề xuất kèm theo. Chỉ lên kế hoạch
   merge sau khi Bảo xác nhận đã thống nhất. Câu hỏi đầu tiên là **Mâu thuẫn quyết
   định** bên dưới, vì mọi bước merge phụ thuộc vào nó.
   *Xong khi:* mâu thuẫn được chốt và ghi lại (sửa hoặc thay ADR 0001), và mỗi mục
   "Còn mở" có quyết định hoặc người chịu trách nhiệm.
2. **Lập kế hoạch merge.** Kết quả là danh sách PR theo thứ tự. Mỗi PR có phạm vi file,
   cách xử lý xung đột và lệnh test chứng minh xong.
   *Xong khi:* có kế hoạch cho cả 9 commit của `backup/local-2026-10-25` và 3 commit
   của Liễu chỉ có trên `main`, không bỏ sót commit nào.

## Sự thật đã kiểm tra (ngày 2026-11-01)

**Hai lịch sử tách nhau từ `e5be40e`** (Liễu, 25/10 20:33):

- `origin/backup/local-2026-10-25` gồm 9 commit chỉ có ở máy Bảo, vừa push để giữ lại.
  - `src/milestone1_crawler.py` còn 25 dòng: chỉ là dispatcher `--engine standalone|integrated`,
    mặc định `standalone`.
  - Bản tích hợp (`LieuPipeline`, `BatchedDiscovery`) chuyển sang `src/crawl/lieu_pipeline.py`.
  - Bản standalone của Liễu chuyển sang `src/lieu_standalone_crawler.py` (946 dòng).
  - Có **code Milestone 2 chưa từng lên `main`**: `src/parse/source.py`,
    `scripts/assemble_source.py`, đổi `src/common/schema.py` (kiểu cột M2 đã duyệt) cùng test.
  - Tổng cộng 29 file, +2.936/−754 dòng so với `main`.
- `origin/main` có 3 commit của Liễu, làm sau lúc tách nhánh:
  - `6d435fd` (25/10 23:31): `src/estimate_time.py`, sửa `src/milestone1_crawler.py`.
  - `1b45e47` (26/10 00:08): retry HTTP trong `src/milestone1_crawler.py`.
  - `6941c1b` (26/10 10:42): `docs/milestone1_technical_guide.md`.

  Hai commit đầu sửa file mà nhánh backup đã đổi thành dispatcher. Phần thay đổi đó
  thực chất phải đưa vào `src/lieu_standalone_crawler.py`.
- `main` còn có PR #2 (ADR, benchmark) và PR #3 (validator), cả hai đều chưa có trên nhánh backup.
- Test suite trên `main` hiện lỗi ngay ở bước collection: `tests/test_lieu_crawler.py` cần
  `BatchedDiscovery`/`LieuPipeline`, và `requirements.txt` thiếu `arxiv`.
  Nhánh backup có cả hai thứ.

**Mâu thuẫn quyết định.** `docs/m1-standalone-trial.md` trên nhánh backup ghi rằng ngày
25/10 *nhóm chọn cấu trúc standalone của Liễu làm hướng phát triển M1*. ADR 0001
(31/10) lại chọn `src/crawl/` làm Engine duy nhất. Lúc chốt ADR 0001, chưa ai xét tới
quyết định 25/10. Cần Bảo chọn một trong hai hoặc kết hợp, rồi cập nhật ADR. Liễu đang
hiểu standalone là hướng chính.

**Dữ liệu Range của Bảo** nằm ở `data/crawl-smoke/`, theo layout `src/crawl/`, dung lượng
2,2 GB. Manifest có 20.787 dòng. Theo lần kiểm tra 25/10: 4.941/5.000 Publication hoàn chỉnh,
7.763/7.811 Version đã xác minh (484 Version non-TeX), references có ở 4.985 Publication.
Lần thử bản standalone trên 59 Publication còn thiếu không phục hồi được bài nào
(phần lớn trả HTTP 404). Chi tiết ở `docs/m1-standalone-trial.md` trên nhánh backup.

**Ước tính benchmark cuối cho 25.000 ID**, suy từ số trên với trung bình khoảng 1,56
Version/Publication: khoảng 39.000 request source arXiv, mỗi request cách nhau ít nhất 3,1 giây,
tức khoảng 34 giờ trên một máy. Dung lượng output khoảng 11 GB.

## Còn mở (chuyển tiếp)

- Patch `range-segments-2026-11-01.patch` (Range nhiều Đoạn, `configs/ranges.toml`) đã gửi
  Bảo, có thể chưa áp. Test validator trong patch chưa được chạy. Hỏi Bảo trạng thái.
- Minh: `last_september_id` thật (hiện điền tạm `2409.20569`, `verified = false`).
  Nghiêm: xác nhận GitHub username.
- Benchmark cuối: (a) một Colab chạy tuần tự 25.000 ID, hay (b) mỗi người một Colab trên
  Range của mình rồi cộng lại. Cần hỏi giảng viên.
- Branch protection cho `main`: Bảo tự bật.
- Importer (bước 4 của Q16) phụ thuộc vào quyết định ở mục Mâu thuẫn: layout chuẩn là
  layout nào thì importer chuyển về layout đó.

## Đã chốt trong buổi grill 2026-11-01

- **Q1 – Engine chuẩn:** chọn (C). `src/crawl/` là Engine chuẩn (layout, manifest,
  Export, validator). Discovery theo lô và S2 chạy song song của Liễu là cách cài đặt
  mặc định của Stage Discovery/Runner qua `LieuPipeline`; cải tiến HTTP trong 3 commit
  sau của Liễu được chuyển vào khung. ADR 0001 phải ghi rõ quyết định 25/10 và lý do
  chọn lại. Căn cứ: dữ liệu 2,2 GB, validator (`src/crawl/validation.py:62`) và Export
  đều theo layout khung; lượt thử standalone phục hồi 0/59.
- **Q2 – Patch Range nhiều Đoạn:** đi **sau** các PR merge M1, là PR riêng có chạy test
  validator. (Chưa có `configs/ranges.toml` trên nhánh remote nào.)
- **Q3 – Code M2:** tách PR riêng, merge sau khi M1 ổn trên `main`; phần đổi
  `src/common/schema.py` đi trước trong một PR nhỏ.
- **Q4 – Benchmark cuối:** Bảo hỏi giảng viên trong tuần, kèm ước tính ~34 giờ cho (a).
  Trong lúc chờ, lên kế hoạch theo (b).
- **Q5 – Branch protection:** Bảo bật ngay trước PR merge đầu tiên: bắt buộc PR, cấm
  force-push, cấm xóa nhánh. Chưa bắt buộc review hay CI xanh.
- **Q6 – Minh/Nghiêm:** không chặn merge. Bảo đôn đốc; hạn là trước khi merge PR Range
  nhiều Đoạn. Giá trị của Minh giữ `verified = false` tới khi xác nhận.

## Dọn tài liệu (2026-11-02)

Theo yêu cầu của Bảo, đã xóa các file `.md` không liên quan tới quyết định Q1–Q6:
`leader.md`, `docs/{crawl-review,infrastructure-review,team-lead-checklist,crawling-requirements,semantic-scholar-check,schema-review,full-range-crawl,lieu-integration,benchmark_resume_guide,milestone1_technical_guide}.md`.
`CONTEXT.md` chỉ còn mục Thuật ngữ. Nội dung cũ xem lại bằng `git show 062ba29:<đường dẫn>`.

- Còn mở cho M2: các mục G0 trong `docs/schema-review.md` (Element ID, khóa hierarchy)
  chưa chốt; xem `git show 062ba29:docs/schema-review.md`.
- Khi merge nhánh backup: 7 file trên bị nhánh backup sửa (`AGENTS.md`, `README.md`,
  `leader.md` và 4 file trong `docs/`). Xung đột sửa/xóa giải bằng cách **giữ xóa**,
  trừ `AGENTS.md`/`README.md` (chưa xóa). `docs/m1-standalone-trial.md` (bằng chứng 0/59
  cho ADR 0001) và `docs/milestone2-source.md` (Q3) chỉ có trên backup, đưa vào cùng PR tương ứng.
- `README.md` và `AGENTS.md` còn link tới các file đã xóa; sửa trong PR dọn đợt 2.
