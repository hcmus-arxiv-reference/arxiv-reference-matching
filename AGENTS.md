# AGENTS.md: Kế hoạch cho agent (repo `arxiv-reference-matching`)

Tài liệu này dành cho agent lập trình làm việc **thay mặt Nguyễn Thành Bảo**, nhóm trưởng kiêm phụ trách **Parser** của nhóm 5 người. Đọc hết file trước khi viết code. Nếu một mục chưa rõ, **hỏi người dùng** thay vì đoán.

## 1. Bối cảnh

Đồ án môn Nhập môn Khoa học Dữ liệu (HCMUS, nhóm 3 KHDL24): thu thập bài arXiv, parse mã nguồn LaTeX thành cây phân cấp, rồi ghép BibTeX entry với Reference của Semantic Scholar bằng pipeline học máy.

- Đề bài: <https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/> (3 trang con `crawling/`, `parsing/`, `matching/`). Nếu công cụ web không đọc được, thử tải URL trực tiếp trước khi nhờ người dùng dán nội dung.
- Trạng thái hiện tại và cách chạy: `README.md`. Quyết định kiến trúc: `docs/adr/`. Kế hoạch merge và việc còn mở: `docs/handoff/`. Kiểm tra lại file thực tế; không tuyên bố tính năng "đã chạy" nếu chưa chạy kiểm thử thật.

### Quyết định đã chốt (không hỏi lại)

- Range của Bảo: `2508.02872`–`2508.07871`, gồm hai đầu (5.000 ID). Dữ liệu cục bộ ở `data/crawl-smoke/`, layout `src/crawl/`.
- `src/crawl/` là Engine duy nhất trên `main` (ADR 0001). Bản standalone của Liễu ở tag `lieu-standalone-final`; nhánh thành viên giữ làm case study, không merge.
- Đề Matching chỉ rõ **6 bảng**: `papers`, `references`, `elements`, `hierarchy`, `bibtex`, `predictions`. Hai bảng Crawling: `papers(arxiv_id, title, authors, submission_date, revised_dates, venue)` và `references(arxiv_id, ref_arxiv_id, ref_title, ref_authors, ref_submission_date, ref_s2_id)`.
- `papers.authors`, `papers.revised_dates`, `references.ref_authors` là list of strings (`pyarrow.list_(pyarrow.string())`).
- `ref_submission_date` lấy từ `publicationDate` của Semantic Scholar (giảng viên cho phép ngày 10/11/2026); giá trị thiếu hoặc không phải ngày ISO thì giữ null. Không tra thêm ngày v1 trên arXiv.
- Hugging Face (dataset private): file thô ở `raw/<member>/<publication key>/v<n>/`, bảng ở `tables/<member>/<tên bảng>.parquet`. `upload_dir` chỉ ghi dưới `raw/<MEMBER_NAME>/`; bảng dùng `upload_table`.
- Không yêu cầu người dùng gửi token trong chat; không ghi token hoặc cấu hình riêng vào tài liệu.
- Đường dẫn repo chứa dấu `:` nên virtualenv phải đặt ngoài repo.
- `metrics.peak_rss_mb` chỉ đo đỉnh của tiến trình hiện tại; `dir_size_mb` là ảnh chụp, không phải disk đỉnh.

## 2. Thuật ngữ

Dùng đúng thuật ngữ trong [`CONTEXT.md`](CONTEXT.md) (Publication, Version, Reference, BibTeX entry, Element, Range, Stage, Engine, Cách cài đặt Stage).

## 3. Phạm vi của agent

**Agent làm:** khung repo, schema chung, tiện ích Hugging Face, công cụ tải bộ mẫu để phát triển, **Parser** (bảng `elements`, `hierarchy`), công cụ kiểm tra chất lượng (QA), notebook thống kê cho báo cáo.

**Agent không làm thay (chỉ tạo stub hoặc mock khi cần để chạy thử):**
- Crawler hoàn chỉnh (thuộc thành viên Crawler).
- Lấy references từ Semantic Scholar (thành viên Semantic Scholar và metadata).
- Chuẩn hóa LaTeX và `\bibitem` sang BibTeX (thành viên Chuẩn hóa và BibTeX).
- Mô hình Matching (thành viên Matching).

## 4. Quy tắc bắt buộc

1. **Không commit dữ liệu.** `data/`, `*.parquet`, `*.tar.gz`, file `.tex` thô đều nằm trong `.gitignore`.
2. **Không commit bí mật.** Token Hugging Face và API key Semantic Scholar chỉ đọc từ biến môi trường hoặc `.env` (đã `.gitignore`). Chỉ commit `.env.example` không có giá trị thật.
3. **Tải từ arXiv phải lịch sự:** dùng `export.arxiv.org` (không dùng `arxiv.org`, sẽ bị 403), cách nhau **tối thiểu 3 giây** giữa các request, **một kết nối một lúc**, User-Agent mô tả rõ (có email liên hệ).
4. **Schema tường minh:** không object lồng nhau hoặc JSON blob trong cột Parquet. Ngoại lệ đã được người dùng chốt theo đề: `authors`, `revised_dates`, `ref_authors` ở các bảng Crawling dùng list of strings như mục 1 (Quyết định đã chốt); không chuyển các cột này thành chuỗi. Mọi thay đổi schema khác phải **hỏi người dùng trước**, vì cả nhóm phụ thuộc vào nó.
5. **Phiên bản không có TeX** (chỉ PDF, docx) vẫn phải có bản ghi rỗng, không được bỏ qua.
6. **Parser phải tái lập được:** sửa bằng code, không sửa tay từng dòng. Ngoại lệ phải ghi vào một file log.
7. **Commit nhỏ và thường xuyên**, thông điệp rõ ràng (ví dụ `feat(parse): resolve \input recursively`). Lịch sử commit là một phần điểm.
8. Mỗi module phải có **test** chạy được. Chỉ báo "đạt" sau khi đã chạy test thật.
9. Code có docstring và chú thích đủ rõ. Tài liệu online dùng để tham khảo phải ghi nguồn.
10. Không dùng LLM hay mô hình pretrained trong Parser. Phần Matching có quy tắc riêng, không thuộc phạm vi của agent.

## 5. Yêu cầu Parser (M2)

Làm từng lớp; mỗi lớp có code, test với fixture nhỏ tự viết, chạy trên bộ mẫu rồi mới sang lớp sau. Lớp gom source đã có (`src/parse/source.py`, `docs/milestone2-source.md`).

1. **Gom file:** chọn file `.tex` có `\documentclass`, theo `\input`/`\include` đệ quy; lệnh trong comment là text thường; chỉ gom file trên đường biên dịch.
2. **Khung mục:** `\section`, `\subsection`, `\paragraph` (kể cả bản `*`); **gồm** Acknowledgements và Appendices, **bỏ** References.
3. **Lá:** Sentence (không tách ở toán, lệnh, `i.e.`, `et al.`, `Fig. 1`, URL, số thập phân), Block formula, Figure (Table tính là Figure). Mỗi `\item` là con của nút `itemize`.
4. **Chuẩn hóa:** bỏ lệnh định dạng vô nghĩa (`\centering`, `[htpb]`, `\midrule`, ...); toán inline về `$...$`, toán khối về `\begin{equation}...\end{equation}`.
5. **Khử trùng lặp giữa các Version** sau chuẩn hóa: phần tử giống hệt dùng chung `element_id`.
6. Xuất `elements` và `hierarchy` đúng schema; một dòng `hierarchy` là một cạnh nút-cha của một Version; mọi `parent_id` trỏ tới `element_id` có thật.

Hợp đồng dữ liệu giữa các milestone: `docs/data-contract.md`. Khóa `hierarchy` đã chốt là `(arxiv_id, version, element_id, parent_id)` (C2). `element_id` băm theo cây con (C1); thứ tự anh em giữ ở dữ liệu trung gian của M2 (C3). Batch parse cần checkpoint/resume, log lỗi từng Version và số liệu cho báo cáo (tỉ lệ thành công, độ phủ Version, số phần tử trước/sau khử trùng lặp, thời gian, RAM, dung lượng).

## 6. Khi nào phải dừng lại và hỏi người dùng

- Muốn đổi schema hay quy ước đặt tên.
- Một quyết định về Parser ảnh hưởng đến bảng của thành viên khác (ví dụ định dạng `element_id`).
- Không truy cập được trang đề hoặc dữ liệu.
- Phát hiện dữ liệu của người khác bị lỗi.
- Có thao tác không thể hoàn tác (xóa dữ liệu trên Hugging Face, đổi lịch sử git).
