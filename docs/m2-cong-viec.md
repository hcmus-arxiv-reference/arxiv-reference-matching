# M2: công việc của nhóm

Tài liệu cho Minh, Hải, Liễu, Nghiêm. Mỗi người một gói việc. Đọc mục 1–3 trước khi bắt đầu,
rồi đọc thẻ của mình ở mục 4.

Tài liệu đi kèm:
- Đề: [Parsing](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/parsing/)
- Kiểu dữ liệu ở các điểm giao, bất biến, ví dụ chạy qua cả pipeline: [`m2-interfaces.md`](m2-interfaces.md)
- Hợp đồng dữ liệu giữa các milestone (C1–C9): [`data-contract.md`](data-contract.md)
- Cách dùng Git/GitHub, mở PR, lấy dữ liệu: [`CONTRIBUTING.md`](../CONTRIBUTING.md)
- Thuật ngữ (Publication, Version, Element, BibTeX entry, …): [`CONTEXT.md`](../CONTEXT.md)

## 1. M2 phải làm gì (tóm tắt đề)

Từ `.tex/.bib` của mọi Version đã crawl ở M1, dựng cây tài liệu cho từng Version, chuẩn hóa,
khử trùng lặp giữa các Version, rồi xuất ba bảng `elements`, `hierarchy`, `bibtex`
(schema có sẵn trong `src/common/schema.py`, **không tự ý sửa**).

## 2. Ai làm gì

```
Liễu: Source + Structure   Nghiêm: Leaves    Hải: Normalize + BibTeX   Minh: Integration
M2.1 (sửa) + M2.2          M2.3              M2.4a + M2.4b              M2.5 + batch + số liệu

[A] SourceBundle ──► [B] StructureTree ──► [C] LeafTree ──┐
                     [B'] BibSource ────► [D] BibResult ──┼──► [E] 3 bảng + log + metrics
                                          normalize() ────┘
```

| Người | Gói | Nhận từ | Giao cho |
|---|---|---|---|
| **Liễu** | Source + Structure | thư mục Version | Nghiêm ([B]), Hải ([B']) |
| **Nghiêm** | Leaves | Liễu ([B]) | Minh ([C]) |
| **Hải** | Normalize + BibTeX | Liễu ([B']) | Minh ([D], `normalize`) |
| **Minh** | Integration | Nghiêm, Hải | ba bảng cuối, số liệu báo cáo |

**Không ai phải chờ ai.** Mỗi người test trên golden fixture (mục 3.2): đọc output mẫu của người
trước, so với output mẫu của người sau. Người trước làm xong lúc nào cũng được.

## 3. Quy tắc chung

### 3.1 Bắt buộc
1. **Không dùng LLM hay mô hình pretrained trong Parser.** Chỉ dùng code, regex, thư viện parse
   thông thường. Vi phạm là trừ điểm cả nhóm.
2. **Tất định:** cùng input phải ra cùng output từng byte. Không phụ thuộc thứ tự file trên đĩa,
   giờ chạy hay `set`/`dict` không sắp xếp.
3. **Không sửa tay dữ liệu.** Trường hợp không xử lý được thì ghi vào log kèm mã lỗi, không bỏ qua im lặng.
4. **Test chạy offline**, không cần mạng, không cần corpus, dưới 30 giây.
5. **Không commit dữ liệu** (`data/`, `*.parquet`, `.tex` thật) và **không commit token**.
6. **Không sửa `types.py` hay `schema.py` trong PR của gói mình.** Cần đổi thì mở PR riêng, ghi lý do.
7. Mỗi module có hằng số `<TÊN>_VERSION`, tăng khi đổi hành vi (dùng cho checkpoint).
8. Tài liệu online tham khảo thì ghi link trong docstring.

### 3.2 Golden fixture: cách test độc lập

Mỗi case nằm ở `tests/fixtures/m2/<case>/`, gồm input `.tex` tự viết và output mong đợi tại từng
điểm giao (`A.v1.json`, `B.v1.json`, …). Test của bạn:
1. nạp file golden của điểm giao **trước** gói mình;
2. chạy code của bạn;
3. so với file golden của điểm giao **sau** gói mình;
4. gọi `validate_<điểm giao>()` trên output.

Ví dụ, test của Nghiêm nạp `B.v1.json`, chạy `build_leaves()`, so với `C.v1.json`. Golden viết
bằng tay và được review trước khi viết code: golden sai thì test xanh cũng vô nghĩa.

### 3.3 Số liệu
Mỗi gói có một lệnh chạy trên bộ mẫu 100 bài, ghi `metrics/<gói>.json`. Đây là nguồn số liệu
cho báo cáo, nên phải chạy lại được và ghi commit, seed.

## 4. Thẻ công việc

### 4.1 Liễu: Source + Structure (M2.1 sửa lỗi, M2.2)

**Mục tiêu:** từ thư mục Version, gom đúng source và dựng khung mục của tài liệu.

| | |
|---|---|
| Input | thư mục Version đã xác minh `raw/<key>/v<n>/` |
| Output | [A] `SourceBundle` (đã có), [B] `StructureTree`, [B'] `BibSource` (định nghĩa: `m2-interfaces.md` mục 3) |
| File | `src/parse/source.py` (sửa), `src/parse/structure.py` (mới), `tests/test_parse_structure.py` |

**Việc cần làm, theo thứ tự**
1. Sửa lỗi M2.1 (số liệu chạy toàn Range Bảo ngày 06/11: 75,9% `ready`). Mỗi lỗi sửa kèm một fixture:
   - `\iff` bị nhận nhầm là lệnh điều kiện (nó là ký hiệu toán). Đây là nguyên nhân chính của
     lỗi "điều kiện chưa đóng".
   - `\AtBeginDocument` chỉ cảnh báo khi bên trong có `\input`/`\include`.
   - `\input{*.bbl}` không có file: hạ thành cảnh báo (`.bbl` không được crawl, theo đề).
   - Nhiều file có `\documentclass` (204 Version): viết quy tắc chọn tự động và tất định, ví dụ
     file có `\begin{document}` và không bị file khác include.
   - `\newif\ifxxx` do tác giả định nghĩa, `\ifmmode` trong thân macro.
2. Dựng `StructureTree` từ `SourceBundle.text`:
   - Bỏ comment (thay bằng khoảng trắng để giữ vị trí), chỉ lấy thân `\begin{document}…\end{document}`.
   - Nhận diện `\chapter`, `\section`, `\subsection`, `\subsubsection`, `\paragraph`, kể cả bản `*`.
   - **Cấp tương đối:** cấp con luôn sâu hơn cấp cha. Bài không có `\section` nhưng có
     `\subsection` thì `subsection` là con của `document`.
   - Bỏ References/Bibliography (theo tiêu đề và môi trường `thebibliography`); giữ
     Acknowledgements, Appendix (kể cả sau `\appendix`).
   - Phần thân giữa các heading cắt thành `Block`: đoạn văn, môi trường (`figure`, `table`,
     `itemize`, `equation`, …), toán khối. Không tách bên trong Block, đó là việc của Nghiêm.
3. Tách `BibSource`: tên `.bib` được `\bibliography{}`/`\addbibresource{}` gọi, nội dung các
   `\bibitem`, danh sách key trong `\cite*{...}`.

**Cách làm gợi ý**
- `source.py` đã có bộ quét (`_scan`, `_control`, `_group`) xử lý lệnh, ngoặc, comment, verbatim.
  Tách nó thành tokenizer dùng chung, thay vì viết regex mới cho từng trường hợp.
- Có thể so với thư viện `pylatexenc` (`LatexWalker`, không phải mô hình học máy) trên 100 bài mẫu
  về tốc độ và độ đúng, rồi chọn một. Ghi kết quả so sánh trong PR.

**Xong khi**
- [ ] `ready` ≥ 95% số Version TeX của Range Bảo.
- [ ] Cấp mục đúng ≥ 95% số heading trên 30 bài gán nhãn tay.
- [ ] Không bài nào lọt Section References vào cây.
- [ ] Golden đạt: `multi-file-input`, `comments-and-verbatim`, `levels-skip`, `appendix-ack-refs`.

**Số liệu** (`metrics/structure.json`): số Version theo trạng thái M2.1, số lần gặp từng mã lỗi,
số heading theo loại, số bài không có `\section`, thời gian.

### 4.2 Nghiêm: Leaves (M2.3)

**Mục tiêu:** tách mỗi Block thành các lá đúng loại.

| | |
|---|---|
| Input | [B] `StructureTree` |
| Output | [C] `LeafTree`: lá `sentence`, `formula`, `figure`; node `itemize` → `item` |
| File | `src/parse/leaves.py`, `src/parse/sentences.py`, `tests/test_parse_leaves.py` |

**Việc cần làm, theo thứ tự**
1. Viết bộ **40 câu khó** trước khi code: mỗi dòng gồm input và kết quả tách mong đợi.
2. Tách câu:
   - **Không tách** bên trong `$…$`, `\(…\)`, đối số `{…}` của lệnh, URL, số thập phân (`3.14`),
     sau `i.e.`, `e.g.`, `et al.`, `etc.`, `Fig.`, `Eq.`, `Sec.`, `Tab.`, `vs.`, `cf.`.
   - Chỉ tách ở dấu chấm (và `?`, `!`) kết câu.
3. Toán khối → `formula`: `equation`, `equation*`, `$$…$$`, `\[…\]`, cùng `align`, `gather`, …
   (một hay nhiều `formula`: theo quyết định chung ngày 10/11).
4. `figure` và `table` (kể cả `figure*`, `table*`) → một lá `figure`, giữ nguyên cả môi trường.
5. `itemize`/`enumerate`/`description` → node `itemize`; mỗi `\item` → node `item`; câu trong
   item là con của item; danh sách lồng nhau giữ đúng cấp.

**Cách làm gợi ý**
- Che (mask) các vùng không được tách: thay toán, lệnh, URL, chữ viết tắt bằng ký tự giữ chỗ
  cùng độ dài. Tách trên chuỗi đã che, rồi cắt chuỗi gốc ở cùng vị trí. Nhờ vậy offset (`span`)
  giữ đúng và phép kiểm "không mất chữ" dễ đạt.
- Danh sách chữ viết tắt đặt thành một hằng số duy nhất.

**Xong khi**
- [ ] 40 câu khó đạt 100%.
- [ ] Kiểm "không mất chữ": nối `raw` các lá của một Block (bỏ khoảng trắng) bằng đúng Block đó.
- [ ] Ranh giới câu đúng ≥ 95% trên 30 bài gán nhãn tay.
- [ ] Golden đạt: `hard-sentences`, `lists-figures-math`.

**Số liệu** (`metrics/leaves.json`): số lá theo loại, độ dài câu trung bình và trung vị, số Block
không tách được, thời gian.

### 4.3 Hải: Normalize + BibTeX (M2.4a, M2.4b)

**Mục tiêu:** chuẩn hóa nội dung để so sánh được giữa các Version; gom danh mục tham khảo thành
BibTeX entry duy nhất.

| | |
|---|---|
| Input | chuỗi `raw` của từng node; [B'] `BibSource` của **mọi** Version một Publication |
| Output | `normalize(kind, raw) -> str`; [D] `BibResult` (`entries`, `key_map`, log) |
| File | `src/parse/normalize.py`, `src/parse/bibtex.py`, `tests/test_parse_normalize.py`, `tests/test_parse_bibtex.py` |

**Việc cần làm, theo thứ tự**
1. `normalize`:
   - Bỏ lệnh định dạng vô nghĩa: `\centering`, `[htpb]`/`[!t]`, `\toprule`, `\midrule`,
     `\bottomrule`, `\hline`, `\vspace{…}`, `\small`, `\noindent`, … Đặt hết vào **một bảng hằng số
     có ghi nguồn**.
   - Toán inline (`\(…\)`, `\begin{math}`) → `$…$`.
   - Toán khối (`$$…$$`, `\[…\]`, `equation*`, `displaymath`, …) → `\begin{equation}…\end{equation}`.
   - Gom khoảng trắng. **Không** đổi `\cite` (việc của Minh, làm trước khi gọi `normalize`).
2. BibTeX:
   - Đọc `.bib` (được dùng `bibtexparser` hoặc tự viết; xử lý `@string`, `crossref`).
   - `\bibitem` → entry bằng regex: năm `(19|20)\d{2}`, DOI, URL, arXiv ID; tiêu đề trong ngoặc
     kép, `\emph{}`, `\textit{}` hoặc đoạn sau danh sách tác giả.
   - Khử trùng lặp giữa các Version: hai entry là một khi trùng DOI, hoặc arXiv ID, hoặc tiêu đề đã
     chuẩn hóa + năm. Hợp các trường, không bỏ thông tin; xung đột ghi vào log.
   - Chọn key tất định (C6): key của Version mới nhất có entry; hòa thì lấy key nhỏ nhất theo thứ tự từ điển.
   - Sinh `key_map[version][key gốc] = key đã chọn` cho mọi key trong `cite_keys_used`.

**Xong khi**
- [ ] `normalize(k, normalize(k, x)) == normalize(k, x)` trên mọi fixture.
- [ ] Hai chuỗi chỉ khác khoảng trắng hoặc lệnh định dạng cho cùng output.
- [ ] Mọi key được `\cite` có trong `key_map`; mọi giá trị của `key_map` có trong `entries`.
- [ ] Năm không đọc được thì `year = null`, chuỗi gốc vào log.
- [ ] Trích được tiêu đề ≥ 90% `\bibitem` (kiểm tay 50 mục trong bộ mẫu).
- [ ] Golden đạt: phần [D] của `two-versions-cite-rename`; case `.bib` có `@string`/`crossref`;
      case `\bibitem` không có năm.

**Số liệu** (`metrics/bibtex.json`): số entry trước/sau khử trùng lặp (đề bắt buộc), số entry từ
`.bib` và từ `\bibitem`, số key không có entry, số xung đột trường, số Version không có danh mục
tham khảo.

### 4.4 Minh: Integration (M2.5, chạy batch, số liệu báo cáo)

**Mục tiêu:** ghép các gói thành pipeline chạy cả Range, xuất ba bảng đúng schema, có số liệu
cho báo cáo.

| | |
|---|---|
| Input | [C] `LeafTree` mọi Version, [D] `BibResult`, `normalize()` |
| Output | [E] `elements`, `hierarchy`, `bibtex` (Parquet); log Version; metrics; benchmark |
| File | `src/parse/types.py`, `src/parse/export.py`, `src/parse/pipeline.py`, `scripts/parse_range.py`, `tests/test_parse_export.py` |

**Việc cần làm, theo thứ tự**
1. **Trước 10/11:** viết `src/parse/types.py` theo `m2-interfaces.md` mục 3: các dataclass và
   hàm `validate_A/B/B'/C/D()`. Mở PR sớm để ba bạn review. Đây là việc chặn cả nhóm.
2. Tạo bộ mẫu phát triển: plan 100 Publication lấy ngẫu nhiên có seed từ Range Bảo, kèm lệnh
   tải từ HF (`download_dir` trong `src/common/hf_io.py`).
3. Pipeline cho một Publication, **đúng thứ tự**:
   1. đổi `\cite{k}` theo `key_map`;
   2. `normalize` từng node;
   3. băm từ lá lên gốc (C1): `element_id = <key>#<kind>-<16 hex đầu sha256>`;
   4. hợp Element của mọi Version;
   5. sinh cạnh `hierarchy` (C2), gộp cạnh trùng dưới cùng cha và đếm.
4. Log Version `data/parse/log/versions.jsonl` theo C4: `parsed`, `empty_non_tex`, `failed`, `missing`.
5. Checkpoint/resume: bỏ qua Publication khi sha256 input và phiên bản mọi module không đổi.
6. Kiểm 9 bất biến I1–I9 (`m2-interfaces.md` mục 4) trước khi ghi bảng.
7. Benchmark trên Colab CPU bằng `src.benchmark`: thời gian tổng và trung bình mỗi bài, RAM đỉnh,
   dung lượng đầu ra.

**Xong khi**
- [ ] I1–I9 đạt trên mọi golden và trên bộ mẫu.
- [ ] Chạy hai lần cho ra file giống hệt từng byte.
- [ ] Ngắt giữa chừng rồi chạy lại: không làm lại Publication đã xong.
- [ ] Số dòng log = số Version theo metadata.
- [ ] Ba bảng qua `validate()` của `schema.py`.
- [ ] Golden đạt: phần [E] của `two-versions-cite-rename`, `non-tex-version`.

**Số liệu** (`metrics/export.json`, benchmark): tỉ lệ parse thành công, độ phủ Version, số Element
và entry trước/sau khử trùng lặp, thời gian, RAM, dung lượng. Đây đúng là danh sách đề bắt buộc.

## 5. Việc chung

| Việc | Ai | Hạn |
|---|---|---|
| Review `types.py` | Liễu, Nghiêm, Hải | 10/11 |
| 8 golden case (`m2-interfaces.md` mục 7) | mỗi người viết case của gói mình; Minh viết `two-versions-cite-rename` và `non-tex-version` | 11/11 |
| Gán nhãn tay 30 bài (cấp mục, ranh giới câu) | Liễu 15, Nghiêm 15, rồi đổi chéo kiểm tra | 12/11 |
| Mục M2 trong Jupyter Book | mỗi người viết phần phương pháp của gói mình; Minh viết phần số liệu và hiệu năng | 28/11 |

30 bài lấy ngẫu nhiên có seed (Minh tạo danh sách). Nhãn lưu ở `tests/fixtures/m2/labels/` dạng
JSON: chỉ ID và nhãn, không chép nội dung `.tex`.

## 6. Lịch

| Ngày | Phải có |
|---|---|
| 10/11 | `types.py` đã merge; mỗi người có nhánh và một PR nháp |
| 12/11 | golden và 30 bài gán nhãn đã merge |
| 16/11 | gói của mình đạt tiêu chí trên golden (test xanh) |
| 19/11 | Minh ghép đủ 4 gói, chạy được 100 bài mẫu |
| 22/11 | gói của mình đạt tiêu chí trên bộ mẫu |
| 25/11 | chạy cả Range, benchmark Colab |
| 28/11 | mục M2 trong Jupyter Book, README có cách chạy |

Trễ mốc thì ghi lý do và ngày dự kiến vào issue của mình **trước** ngày mốc, không phải sau.

## 7. Quyết định chung ngày 10/11

Cả nhóm chốt cùng lúc review `types.py`:
1. `enumerate`/`description` dùng chung `kind = "itemize"`?
2. Abstract đặt ở đâu trong cây?
3. `align` nhiều dòng là một hay nhiều `formula`?
4. Quy tắc gộp trường BibTeX khi hai bản có giá trị khác nhau.
5. Tên các trường trong `types.py`.
