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

## Đã chốt vòng 2 (2026-11-02)

- **Q7 – Standalone:** không lên `main`. Tag `lieu-standalone-final` đặt tại `6941c1b`
  (commit cuối của Liễu; ở đó `src/milestone1_crawler.py` là bản standalone có đủ 3 commit
  sau). Bản standalone Bảo sửa (`src/lieu_standalone_crawler.py`) vẫn nằm trên nhánh backup.
  `src/milestone1_crawler.py` thành shim: export `BatchedDiscovery`, `LieuPipeline`, `main`,
  bỏ `--engine`, `main` gọi khung. Bỏ `arxiv`/`requests`, `tests/test_standalone_crawler.py`.
  `src/analyze_errors.py`, `src/diagnose_download.py`, `src/estimate_time.py` đi theo tag.
  `src/merge_benchmarks.py` **giữ lại**: nó gộp các đoạn benchmark bị ngắt của harness
  chung `src/benchmark.py`, cần cho Q4(b).
- **Q8 – ADR 0001:** sửa tại chỗ, giữ `accepted`; đã thêm "Bối cảnh bổ sung 2026-11-01"
  và lựa chọn "Standalone làm Engine".
- **Q9 – Liễu:** Bảo nhắn Liễu trước PR đầu tiên, kèm link ADR 0001; mời Liễu review PR
  chuyển cải tiến HTTP.
- **Q10 – Importer:** chỉ chuyển layout standalone → layout khung, chỉ đọc nguồn, kiểm
  checksum và chạy validator; tùy chọn. Bảo hỏi nhóm ai đang giữ dữ liệu layout standalone.
- **Q11 – Đặt tên:** theo kỹ thuật; `LieuPipeline` chỉ còn là alias, công ghi trong docstring
  và README. Thuật ngữ "Cách cài đặt Stage" đã thêm vào `CONTEXT.md`.

## Đã chốt vòng 3 (2026-11-02)

- **Q12 – Cải tiến HTTP:** chuyển vào `HttpClient` (a) tải tiếp bằng HTTP Range với
  `If-Range` ETag mạnh, (b) giới hạn tổng thời gian theo dung lượng, (c) bảng chờ
  15/30/60/120/240 s ±20% và tôn trọng `Retry-After` tới 900 s; mỗi mục có test. (d) tiến
  độ thành sự kiện trong `crawl.jsonl`. Không chuyển `estimate_time.py`. Chưa có bằng chứng
  (a) cứu được file nào.
- **Q13 – Cách đưa 9 commit lên `main`:** chia theo nhóm. Commit M2 dùng `cherry-pick -x`;
  phần M1 lấy theo file, commit message ghi hash gốc; merge commit và commit chỉ có tài liệu
  đã bị thay thế được ghi lý do bỏ trong bảng dưới. Nhánh backup giữ làm bản lưu đầy đủ.
- **Q14 – `make_stats`:** viết lại thành script thống kê riêng đọc `crawl.jsonl`, không gộp
  vào validator. Liễu review.

## Đã chốt vòng 4 (2026-11-03)

- **Q15 – Tiêu chí tích hợp từ nhánh thành viên:** chỉ đưa vào `main` các cách cài đặt
  Stage **đúng và có hướng phát triển tốt**. Phần sai bị bỏ qua hoàn toàn: không merge,
  không sửa hộ trên nhánh gốc, không viết lại để giữ cho bằng được. Phần sai gồm:
  vi phạm quy tắc AGENTS.md mục 4 (tải arXiv không lịch sự như proxy xoay IP hay nhiều
  kết nối; bí mật ghi trong code); vượt hạn mức dịch vụ (ví dụ nhiều API key S2 song
  song); sai đề hoặc sai schema chung; không có test hay không tái lập được. Phần đúng
  vẫn theo Q11: đặt tên theo kỹ thuật, ghi công người viết. Nhánh gốc giữ nguyên làm case
  study; lỗi tìm thấy ghi vào báo cáo và báo chủ nhánh, không tự sửa.

## Kế hoạch merge

Lệnh test chung (README): `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q`.
Mọi PR vào `main` qua PR (Q5), chạy lệnh test trên máy và dán số đạt/thất bại vào mô tả PR.
Lấy file từ nhánh backup bằng `git checkout origin/backup/local-2026-10-25 -- <đường dẫn>`
thay vì `git merge`, nên không phát sinh xung đột merge; xung đột chỉ là chọn nội dung,
ghi ở từng PR.

**PR 0 – `docs/merge-lieu-grilling-2026-11-01`** (đang draft). Dọn `.md`, sửa ADR 0001,
`CONTEXT.md`, handoff này. Điều kiện merge: đã bật branch protection (Q5), đã nhắn Liễu
(Q9), tag `lieu-standalone-final` → `6941c1b` đã push.
*Xong khi:* `git diff --stat origin/main` chỉ có file `.md`.

**PR 1 – `fix/m1-integrated-entrypoint`**. Sửa lỗi test collection trên `main`.
- Lấy từ backup: `src/crawl/lieu_pipeline.py`, `tests/test_lieu_crawler.py`,
  `scripts/crawl_range.py`, `tests/test_crawl_range.py`, `tests/test_merge_benchmarks.py`,
  `docs/m1-standalone-trial.md`.
- Viết mới `src/milestone1_crawler.py` thành shim: export `BatchedDiscovery`, `LieuPipeline`,
  `main`; `main` gọi `src.crawl.lieu_pipeline.main`; không có `--engine`.
- Sửa docstring `src/crawl/lieu_pipeline.py` dòng 3–10: bỏ `--engine integrated` và câu
  "standalone is now the default", trỏ tới ADR 0001.
- `tests/test_crawler_entrypoint.py` lấy từ backup rồi sửa: giữ test import và test
  `--help` có `--data-dir`, `--max-passes`, `--retry-delay`, `--discover-batch` (không còn
  `--engine`); bỏ test mặc định standalone.
- `docs/m1-standalone-trial.md`: thêm một dòng đầu file ghi rằng `scripts/trial_standalone.py`
  chỉ có trên nhánh backup.
- Xóa `src/analyze_errors.py`, `src/diagnose_download.py`, `src/estimate_time.py` (Q7).
- Không lấy: `src/lieu_standalone_crawler.py`, `tests/test_standalone_crawler.py`,
  `scripts/trial_standalone.py`, `tests/test_standalone_trial.py`, hai dòng `arxiv`/`requests`
  trong `requirements.txt`, bản `src/requirements.txt` của backup.
- `src/benchmark.py` không cần sửa: ví dụ `--ids-file`/`--id` vẫn đúng với entry point khung.
*Xong khi:* lệnh test chung qua bước collection và đạt hết;
`python -m src.milestone1_crawler --help` có `--max-passes`; `grep -rn "import arxiv" src scripts`
không ra gì.

**PR 2 – `fix/schema-m2-types`** (Q3). `git cherry-pick -x 6db45ed`
(`src/common/schema.py`, `tests/test_schema.py`). `schema.py` trên `main` chưa đổi từ lúc
tách nhánh nên cherry-pick sạch.
*Xong khi:* `tests/test_schema.py`, `tests/test_crawl_validation.py`,
`tests/test_crawl_publish.py` và lệnh test chung đều đạt.

**PR 3 – `feat/http-resume`** (Q12). Reviewer: Liễu. Nguồn tham chiếu: `6d435fd`, `1b45e47`
(xem bằng `git show lieu-standalone-final:src/milestone1_crawler.py`). Phạm vi:
`src/crawl/http_client.py`, `src/crawl/source.py`, test mới với transport giả, không gọi mạng.
Test tối thiểu: tải tiếp từ byte đã có khi nhận 206; tải lại từ 0 khi server trả 200; không
gửi `If-Range` với ETag yếu; dừng khi quá giới hạn tổng; chờ đúng `Retry-After` ≤ 900 s và bỏ
khi > 900 s; có sự kiện tiến độ trong `crawl.jsonl`.
*Xong khi:* các test trên và lệnh test chung đạt; `min_interval` 3 s giữa các request arXiv
giữ nguyên.

**PR 4 – `refactor/stage-implementations`** (Q11). Đưa `BatchedDiscovery` vào Stage
Discovery và chiến lược Runner tải references song song (đặt tên theo kỹ thuật) thành mặc
định của `CrawlPipeline`; `LieuPipeline` thành alias; ghi công Liễu trong docstring/README.
*Xong khi:* `tests/test_lieu_crawler.py` không sửa vẫn đạt; lệnh test chung đạt; resume
trên `data/crawl-smoke/` không tải lại Version đã xác minh (chạy thử với `--limit 20`).

**PR 5 – `feat/make-stats-crawl-jsonl`** (Q14). Reviewer: Liễu. `src/make_stats.py` đọc
`manifests/crawl.jsonl`; giữ `load_last_per_id` cho test cũ hoặc sửa test cùng PR.
*Xong khi:* có test đọc một `crawl.jsonl` mẫu; lệnh test chung đạt.

**PR 6 – `docs/cleanup-wave-2`**. `README.md`: giữ hướng dẫn chạy, trạng thái thật và link
đề, bỏ mục 1–12 cũ, sửa link hỏng. `AGENTS.md`: mục 2 thành link tới `CONTEXT.md`, bỏ mục 1
và 5 đã cũ, giữ mục 3, 4, 6.
*Xong khi:* `grep -rn "docs/.*\.md\|leader.md" README.md AGENTS.md` chỉ ra file còn tồn tại.

**PR 7 – `feat/m2-source-assembly`** (Q3). `git cherry-pick -x d58289a`; khi xung đột, bỏ
mọi thay đổi ở `leader.md`, `AGENTS.md`, `README.md`, giữ `src/parse/`,
`scripts/assemble_source.py`, `docs/milestone2-source.md` và hai file test.
*Xong khi:* `tests/test_parse_source.py`, `tests/test_assemble_source_cli.py` và lệnh test
chung đạt.

**PR 8 – Range nhiều Đoạn** (Q2). Bảo áp `range-segments-2026-11-01.patch` lên nhánh mới
từ `main` sau PR 7; cần giá trị của Minh và Nghiêm (Q6).
*Xong khi:* test validator trong patch và lệnh test chung đạt.

**PR 9 – importer, tùy chọn** (Q10). Chỉ làm khi có thành viên giữ dữ liệu layout standalone.

### Đối chiếu commit

| Commit | Nội dung | Đi đâu |
|---|---|---|
| `34881fd` | M2 kickoff, chỉ sửa `leader.md` | Không port: `leader.md` đã xóa ở PR 0; xem `git show 34881fd` |
| `6db45ed` | Kiểu cột M2 trong schema | PR 2, `cherry-pick -x` |
| `d58289a` | Lắp source Version cho M2 | PR 7, `cherry-pick -x`, bỏ hunk tài liệu cũ |
| `5a9aefd` | Merge `origin/main` (code standalone của Liễu) | Không port: nội dung đã có trên `main`, đi theo tag |
| `0068a74` | Giữ resume khi thay entry point | PR 1 (`lieu_pipeline.py`, `crawl_range.py`, test); phần standalone ở lại backup |
| `7504f68` | Tài liệu kiểm tra restart | Không port: chỉ sửa `AGENTS.md`/`lieu-integration.md`, đã thay thế |
| `37513ed` | Merge `e5be40e` (benchmark) | PR 1 (`lieu_pipeline.py`, `tests/test_merge_benchmarks.py`); `src/benchmark.py`, `src/merge_benchmarks.py` đã giống `main` |
| `14303c4` | Chọn standalone làm mặc định, thêm lượt thử | PR 1 lấy phần `lieu_pipeline.py`/test; dispatcher, standalone, trial ở lại backup (Q7) |
| `2e89b20` | Ghi kết quả lượt thử, quy trình M1 mới | PR 1 lấy `docs/m1-standalone-trial.md`; tài liệu khác không port |
| `6d435fd` (Liễu) | Giới hạn thời gian, tiến độ, `estimate_time.py` | PR 3 (HTTP); `estimate_time.py` xóa ở PR 1, còn ở tag |
| `1b45e47` (Liễu) | Bảng chờ, `Retry-After`, ETag yếu | PR 3 |
| `6941c1b` (Liễu) | Tài liệu kỹ thuật | Đã xóa ở PR 0, còn ở tag `lieu-standalone-final` |

Phiên này không chạy được test (sandbox không tải được gói từ PyPI); mọi số liệu test phải
lấy từ máy Bảo hoặc Colab.

## Tiến độ thực hiện (2026-11-02)

- `main` local đã lệch khỏi `origin/main` (ahead 9 / behind 11); 9 commit lệch trùng
  `origin/backup/local-2026-10-25` nên `main` local đã được đặt lại về `origin/main`.
- Đã làm trên máy Bảo, xếp chồng theo thứ tự (mỗi nhánh dựa trên nhánh trước), chưa push:
  PR 1 `fix/m1-integrated-entrypoint` → PR 2 `fix/schema-m2-types` →
  PR 7 `feat/m2-source-assembly` → PR 6 `docs/cleanup-wave-2`.
  PR 7 làm trước PR 6 vì chỉ là cherry-pick; PR 6 mô tả cả lớp gom source M2.
- Lệnh test chung trên nhánh cuối: xem mô tả commit từng nhánh.
- Phát hiện mới: `src/benchmark.py` đếm `*/done.json` (layout standalone), nên
  `done_papers_*` bằng 0 trên layout `src/crawl/`. Nhận định "không cần sửa" ở PR 1 là sai
  về trường này; cần sửa cùng PR 5 hoặc PR riêng.
- PR 3 `feat/http-resume` (dựa trên PR 6): Bảo tự review, báo Liễu sau.
  **Q12(d) đổi:** sự kiện tiến độ ghi vào `manifests/http-events.jsonl`, không ghi vào
  `crawl.jsonl`. Lý do: `crawl.jsonl` là Manifest, nạp bằng `TaskRecord(**json)`, và
  validator (`src/crawl/validation.py`) chỉ nhận 3 kind; ghi sự kiện vào đó làm hỏng
  validator dùng chung. Đổi kèm theo: 429/5xx trên mọi host (gồm S2) chờ theo bảng mới
  thay vì 1/2/4 s; `Retry-After` tối đa 900 s thay vì 60 s.
- Còn lại: PR 4 (Stage implementations), PR 5 (`make_stats`),
  PR 8 (Range nhiều Đoạn, chờ patch và giá trị của Minh/Nghiêm).

## Tiến độ thực hiện (2026-11-03)

- PR #7–#11 đã merge vào nhánh nền sau khi #6 vào `main`, nên chưa tới `main`;
  PR #13 `chore/land-stacked-prs` đưa chúng lên `main`.
- PR 4 → PR #14 `refactor/stage-implementations` (dựa trên #13): `BatchedDiscovery` ở
  `src/crawl/discovery.py`, S2 song song trong `CrawlPipeline._crawl`, `LieuPipeline` là
  alias. Resume `--limit 20` trên `data/crawl-smoke/` không gửi request nào.
- PR 5 → `feat/make-stats-crawl-jsonl` (dựa trên #14): `src/make_stats.py` đọc
  `crawl.jsonl`, giữ `load_last_per_id`; `src/benchmark.py` đếm `done_papers_*` trên cả
  hai layout. Trên `data/crawl-smoke/`: 4.941/5.000 `done`, khớp `range-run.json`.
- Còn lại: PR 8 (Range nhiều Đoạn), PR 9 (importer, tùy chọn).
