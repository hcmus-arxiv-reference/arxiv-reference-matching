# M2: output của từng module và liên kết giữa các module

Ngày 06/11/2026. Tài liệu này giúp nhóm trưởng kiểm tra công việc của từng thành viên M2.
Mỗi module có đúng một input, một output và một bộ tiêu chí đạt. Một module được coi là
xong khi output của nó qua được các phép kiểm ở đây, không phụ thuộc module khác đã xong
hay chưa.

Nguồn:
- Đề: [Parsing](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/parsing/).
- Hợp đồng giữa các milestone: [`data-contract.md`](data-contract.md). Các mã C1–C9 dẫn từ đó.
- Schema ba bảng: `src/common/schema.py`.
- Thuật ngữ: [`CONTEXT.md`](../CONTEXT.md).

**Trạng thái:** M2.1 đã có code (`src/parse/source.py`). Các kiểu dữ liệu của M2.2–M2.5
dưới đây là **bản đề xuất**, sẽ chốt vào `src/parse/types.py` ngày 10/11 (Minh viết, cả nhóm review). Sau khi chốt,
muốn đổi một trường phải mở PR riêng và được nhóm trưởng duyệt, vì module sau phụ thuộc vào nó.
Không có thay đổi nào với schema ba bảng Parquet.

## 1. Sơ đồ

```
                 thư mục Version (raw/<key>/v<n>/, đã xác minh)
                                   │
                    ┌──────────────▼──────────────┐
                    │ M2.1 Source Assembly        │  assemble_source()
                    └──────────────┬──────────────┘
                       [A] SourceBundle (mỗi Version)
                    ┌──────────────▼──────────────┐
                    │ M2.2 Structure              │  build_structure()
                    └──────┬───────────────┬──────┘
           [B] StructureTree│               │[B'] BibSource (mỗi Version)
                    ┌──────▼──────┐  ┌─────▼──────────────────────┐
                    │ M2.3 Leaves │  │ M2.4b BibTeX               │  merge_bibtex()
                    └──────┬──────┘  │ (gom mọi Version của bài)  │
              [C] LeafTree │         └─────┬──────────────────────┘
                           │   [D] BibResult: entries + key_map (mỗi Publication)
                           │               │
      M2.4a normalize() ───┼───────────────┤  (hàm thuần, M2.5 gọi)
                    ┌──────▼───────────────▼──────┐
                    │ M2.5 IDs, Export, QA        │  parse_publication()
                    └──────────────┬──────────────┘
                [E] elements, hierarchy, bibtex (Parquet) + log Version + metrics
```

Mỗi mũi tên là một **điểm giao** có tên ([A]–[E]). Trong quá trình kiểm tra, câu hỏi luôn là:
"output của module này có đúng định nghĩa ở điểm giao không?". Câu hỏi không phải là "toàn bộ
pipeline có chạy không".

## 2. Kiểm tra độc lập bằng bộ golden chung

Mỗi điểm giao có một bộ ví dụ mẫu (golden) đặt ở `tests/fixtures/m2/<case>/`. Người phụ trách
từng gói viết bộ này bằng tay; nhóm trưởng review trước khi viết code.

```
tests/fixtures/m2/<case>/
  v1/main.tex, v1/refs.bib, v1/source.json   input thô (fixture, không phải corpus thật)
  v2/...
  A.v1.json   SourceBundle mong đợi      (M2.1 sinh ra, M2.2 đọc vào)
  B.v1.json   StructureTree mong đợi     (M2.2 sinh ra, M2.3 đọc vào)
  B'.v1.json  BibSource mong đợi         (M2.2 sinh ra, M2.4b đọc vào)
  C.v1.json   LeafTree mong đợi          (M2.3 sinh ra, M2.5 đọc vào)
  D.json      BibResult mong đợi         (M2.4b sinh ra, M2.5 đọc vào)
  E/          3 bảng mong đợi dạng CSV   (M2.5 sinh ra)
```

Quy tắc test:
- **Module N đọc golden của điểm giao trước nó, so output với golden của điểm giao sau nó.**
  Ví dụ test M2.3 nạp `B.v1.json` và so kết quả với `C.v1.json`. Test này không gọi code M2.2,
  nên M2.3 làm được ngay khi M2.2 chưa xong.
- Mỗi điểm giao có một hàm `validate_<điểm giao>()` trong `src/parse/types.py`. Hàm này kiểm
  các bất biến ở mục 3, và mọi module phải gọi nó trên output của chính mình trong test.
- Test không cần mạng, không cần corpus, chạy dưới 30 giây.
- Tối thiểu 8 case dùng chung (mục 7). Mỗi module tự thêm case cho phần việc riêng.

## 3. Định nghĩa từng điểm giao

Các kiểu viết dạng dataclass Python. Mọi offset là vị trí ký tự nửa mở `[start, end)` trong
`SourceBundle.text`. Nhờ vậy mọi node đều chỉ ngược về được dòng gốc qua `SourceBundle.spans`.

### [A] `SourceBundle`: M2.1 → M2.2 (đã có trong code)

| Trường | Ý nghĩa |
|---|---|
| `status` | `ready`, `needs_review`, `error`, `empty_non_tex` |
| `root` | file `.tex` gốc (có `\documentclass`) |
| `text` | nguồn đã gộp theo đường biên dịch, **chưa** bỏ comment, chưa chuẩn hóa |
| `files`, `unused_tex_files`, `checksums` | file đã dùng và chưa dùng; sha256 |
| `spans` | ánh xạ đoạn trong `text` về `(file, vị trí, dòng)` gốc |
| `includes`, `issues` | từng lần `\input`/`\include`; chẩn đoán (mã, mức độ, file, dòng) |
| `assembler_version` | phiên bản M2.1, dùng cho checkpoint |

Bất biến:
- `empty_non_tex` thì `text == ""` và không sinh node nào ở bước sau. Version vẫn có dòng trong
  log (C4).
- `error` thì không đi tiếp. M2.5 ghi `failed` vào log kèm mã lỗi.
- `needs_review` vẫn đi tiếp, nhưng mã cảnh báo được chép vào log Version.
- Gom lại cùng thư mục cho ra cùng `text` từng byte.

### [B] `StructureTree`: M2.2 → M2.3

```python
@dataclass
class Section:                       # node cấu trúc
    kind: str                        # document | chapter | section | subsection | subsubsection | paragraph
    title_raw: str                   # tiêu đề thô, chưa chuẩn hóa ("" với document)
    starred: bool                    # \section* ...
    span: tuple[int, int]            # cả node, kể cả lệnh tiêu đề
    children: list["Section | Block"]

@dataclass
class Block:                         # đoạn chưa tách lá
    type: str                        # text | env | display_math
    env: str | None                  # tên môi trường nếu type == env (figure, table, itemize, equation, ...)
    raw: str                         # đúng chuỗi con text[span], comment đã thay bằng khoảng trắng
    span: tuple[int, int]

@dataclass
class StructureTree:
    arxiv_id: str
    version: int
    root: Section                    # kind == "document"
    dropped: list[dict]              # phần bị bỏ: {"reason": "references" | "preamble" | ..., "span": ...}
    issues: list[dict]
    structure_version: str
```

Bất biến:
- Root là `document`. Chỉ thân `\begin{document}…\end{document}` đi vào cây; preamble nằm ở `dropped`.
- **Cấp tương đối:** cấp của node con luôn sâu hơn cấp của node cha. Bài không có `\section`
  nhưng có `\subsection` thì `subsection` là con trực tiếp của `document`. Không tạo node rỗng
  để lấp chỗ trống.
- Section References/Bibliography (theo tiêu đề hoặc môi trường `thebibliography`) **không** có
  trong cây. Nó nằm ở `dropped` với `reason = "references"`, và nội dung chuyển sang [B'].
- Acknowledgements, Appendix (kể cả sau `\appendix` và `\section*`) **có** trong cây.
- Comment không bao giờ thành nội dung. Lệnh nằm trong comment không mở node.
- Các `Block` con của một node không chồng lấn nhau và nằm theo thứ tự đọc.
- `itemize`/`enumerate`, `figure`/`table`, `equation`/`align`/…, `$$…$$`, `\[…\]` là `Block`
  nguyên khối. M2.2 không tách bên trong chúng.

### [B'] `BibSource`: M2.2 → M2.4b

```python
@dataclass
class BibSource:
    arxiv_id: str
    version: int
    bib_files: dict[str, str]        # tên file .bib được \bibliography/\addbibresource gọi → nội dung
    missing_bib: list[str]           # được gọi nhưng không có trong Version (ví dụ chỉ có .bbl)
    bibitems_raw: list[str]          # mỗi \bibitem trong thebibliography, nguyên văn
    cite_keys_used: list[str]        # mọi key trong \cite*{...} của thân bài, theo thứ tự xuất hiện
```

Bất biến:
- `bib_files` chỉ chứa file trong receipt của Version.
- `cite_keys_used` gồm mọi biến thể `\cite`, `\citep`, `\citet`, `\citeauthor`, … và tách đúng
  danh sách nhiều key (`\cite{a,b}`).
- Version không có `.bib` lẫn `\bibitem`: hai trường đều rỗng, và M2.5 ghi `no_bibliography`
  vào log. Đây không phải lỗi.

### [C] `LeafTree`: M2.3 → M2.5

Cùng hình dạng với [B], nhưng mọi `Block` đã được thay bằng node lá hoặc node danh sách:

```python
@dataclass
class Leaf:
    kind: str                        # sentence | formula | figure
    raw: str                         # chưa chuẩn hóa, \cite vẫn giữ key gốc
    span: tuple[int, int]

@dataclass
class ListNode:
    kind: str                        # itemize | item
    span: tuple[int, int]
    children: list["ListNode | Leaf"]   # itemize → item; item → sentence/formula/figure/itemize lồng
```

Bất biến:
- Sau M2.3 không còn `Block` nào.
- `sentence` không bao giờ bị cắt bên trong toán, bên trong đối số lệnh, sau `i.e.`, `e.g.`,
  `et al.`, `Fig.`/`Eq.`/`Sec.` + số, trong URL, hay giữa số thập phân.
- `figure` gồm cả `table`. `raw` là toàn bộ môi trường, kể cả `\caption` và `\includegraphics`.
- `formula` chỉ dành cho toán khối. Toán inline nằm trong `sentence`.
- `itemize` chỉ có con là `item`. `enumerate` và `description` cũng dùng `kind = "itemize"`,
  vì `ELEMENT_KINDS` không có loại riêng. **Cần chốt ngày 10/11.**
- Nối `raw` của các lá trong một Block (bỏ khoảng trắng) phải cho lại đúng Block đó. Đây là
  phép kiểm "không mất chữ".

### [D] `BibResult`: M2.4b → M2.5 (mỗi Publication một lần)

```python
@dataclass
class BibResult:
    arxiv_id: str
    entries: list[dict]              # đúng cột bảng bibtex: citation_key, entry_type, title,
                                     # authors (list), year (int | None), doi, journal, url
    key_map: dict[str, dict[str, str]]  # {"<version>": {key gốc: key đã chọn}}
    raw_years: dict[str, str]        # year không đọc được: key → chuỗi gốc (log, không vào bảng)
    stats: dict                      # entry_before, entry_after, from_bib, from_bibitem, ...
    bibtex_version: str
```

Bất biến:
- Mọi key trong `cite_keys_used` của mọi Version đều có trong `key_map` của Version đó. Key
  không có entry nào ánh xạ về chính nó và được đếm vào `stats.unresolved`.
- Giá trị của `key_map` luôn là một `citation_key` có trong `entries`.
- Quy tắc chọn key tất định (C6). Mặc định: lấy key của Version mới nhất có entry đó; nếu hòa,
  lấy key nhỏ nhất theo thứ tự từ điển.
- Gộp trường: không bỏ thông tin. Trường có ở một bản thì giữ. Hai bản khác giá trị thì giữ theo
  quy tắc đã ghi trong docstring, và ghi xung đột vào log.
- `year` không phải số 4 chữ số hợp lệ thì để `None`, chuỗi gốc lưu ở `raw_years`.

### M2.4a `normalize(kind, raw) -> str` (hàm thuần, không có điểm giao riêng)

| `kind` | Output |
|---|---|
| `sentence` | bỏ lệnh định dạng vô nghĩa; toán inline (`\(…\)`, `$…$`, `\begin{math}`) về `$…$`; gom khoảng trắng |
| `formula` | `\begin{equation}…\end{equation}`, áp dụng cho `$$…$$`, `\[…\]`, `equation*`, `align`, … (xem mục 8) |
| `figure` | môi trường đã bỏ `\centering`, `[htpb]`, `\midrule`, `\toprule`, …; giữ `\caption`, `\label`, `\includegraphics` |
| tiêu đề Section | như `sentence` nhưng không thêm dấu câu |

Bất biến:
- **Idempotent:** `normalize(k, normalize(k, x)) == normalize(k, x)`.
- Hai chuỗi chỉ khác khoảng trắng hoặc khác lệnh định dạng cho cùng output.
- Không đổi `\cite`. Việc đổi key là của M2.5, làm **trước** khi gọi `normalize`.
- Danh sách lệnh bị bỏ nằm ở một bảng hằng số có ghi nguồn, không rải rác trong code.

### [E] Output cuối: M2.5

**Thứ tự xử lý một Publication** (bắt buộc):
1. Với từng Version: đổi `\cite{k}` trong `raw` theo `key_map[version]`.
2. Chuẩn hóa từng node bằng `normalize`.
3. Băm từ lá lên gốc (C1):
   - lá: `sha256(kind, content)`;
   - node cấu trúc: `sha256(kind, content, [id con theo thứ tự])`;
   - `element_id = <publication key>#<kind>-<16 hex đầu>`.
4. Hợp các Element của mọi Version, mỗi `element_id` giữ một dòng.
5. Sinh cạnh `hierarchy`: một dòng `(arxiv_id, version, element_id, parent_id)` cho mỗi cạnh.
   Hai bản giống hệt dưới cùng cha gộp thành một cạnh và được đếm vào log (C2).

**Ba bảng** (schema trong `src/common/schema.py`, không đổi):

| Bảng | Một dòng là | Khóa chính |
|---|---|---|
| `elements` | một Element phân biệt của một Publication; `content` là chuỗi đã chuẩn hóa (`""` với `document`, `itemize`, `item`) | `element_id` |
| `hierarchy` | một cạnh node → cha trong một Version; root không có dòng | `(arxiv_id, version, element_id, parent_id)` |
| `bibtex` | một BibTeX entry đã khử trùng lặp | `(arxiv_id, citation_key)` |

**Dữ liệu trung gian** (không phải bảng, không upload): `data/parse/<key>/order.json` lưu thứ
tự anh em của từng Version (C3).

**Log Version** `data/parse/log/versions.jsonl`, một dòng mỗi Version theo metadata:
```json
{"arxiv_id": "2508.02872", "version": 2, "status": "parsed",
 "issues": ["unsupported_conditional"], "elements": 214, "edges": 230,
 "duplicate_sibling_edges": 0, "no_bibliography": false, "seconds": 0.41}
```
`status` ∈ `parsed`, `empty_non_tex`, `failed`, `missing` (C4). Độ phủ Version trong báo cáo
đọc từ file này.

**Checkpoint:** mỗi Publication ghi `data/parse/<key>/done.json` gồm sha256 của input (các
receipt) và phiên bản của từng module. Chạy lại thì bỏ qua khi cả hai khớp, và làm lại khi một
trong hai đổi.

## 4. Bất biến liên module (M2.5 kiểm tự động trước khi xuất)

| # | Bất biến | Phát hiện lỗi của |
|---|---|---|
| I1 | Mọi `element_id`, `parent_id` trong `hierarchy` có trong `elements` cùng `arxiv_id` | M2.5 |
| I2 | Mỗi Version có đúng một root `document`, không chu trình, mọi node đi tới được root | M2.2, M2.5 |
| I3 | Không có Element nào có tiêu đề khớp References/Bibliography | M2.2 |
| I4 | `kind` của cha hợp lệ: `sentence` không phải cha; cha của `item` luôn là `itemize` | M2.3 |
| I5 | Mọi `\cite{k}` trong `elements.content` có `(arxiv_id, k)` trong `bibtex` | M2.4b, M2.5 |
| I6 | Hai Version giống hệt nhau cho cùng một tập cạnh, và không sinh Element mới | M2.4a, M2.5 |
| I7 | Chạy hai lần trên cùng input cho ra file giống hệt từng byte | mọi module |
| I8 | Số dòng log = tổng số Version theo metadata; mọi Version `non_tex` có log `empty_non_tex` | M2.5 |
| I9 | `validate()` của `schema.py` qua cả ba bảng | M2.5 |

Lỗi I5 là cách nhanh nhất để thấy key map hoặc thứ tự "đổi `\cite` trước, chuẩn hóa sau" bị sai.
Lỗi I6 là cách nhanh nhất để thấy `normalize` chưa ổn định.

## 5. Ví dụ chạy qua cả năm module

Publication giả `2508.02872`, hai Version. v2 sửa một chữ trong câu thứ hai và đổi key trích dẫn.

```latex
% v1/main.tex                              % v2/main.tex
\documentclass{article}                    \documentclass{article}
\begin{document}                           \begin{document}
\section{Intro}                            \section{Intro}
We follow Smith et al.~\cite{smith20}.     We follow Smith et al.~\cite{Smith2020}.
The loss is $L=\|x\|^2$ .                  The loss is $L = \|x\|^2$ here.
\section*{References}                      \bibliography{refs}
\begin{thebibliography}{1}                 \end{document}
\bibitem{smith20} J. Smith. Title. 2020.
\end{thebibliography}
\end{document}
```

| Điểm giao | v1 | v2 |
|---|---|---|
| [A] | `ready`, `text` = toàn bộ file | `ready` |
| [B] | document → section "Intro" → 1 Block text; References nằm ở `dropped` | document → section "Intro" → 1 Block text |
| [B'] | `bibitems_raw` = 1 mục, `cite_keys_used` = `["smith20"]` | `bib_files` = {`refs.bib`}, `cite_keys_used` = `["Smith2020"]` |
| [C] | section → 2 sentence | section → 2 sentence |
| [D] | 2 bản là một entry; chọn key `Smith2020` (Version mới nhất); `key_map = {"1": {"smith20": "Smith2020"}, "2": {"Smith2020": "Smith2020"}}` | |

Ở [E]:
- Câu 1 của hai Version giống hệt nhau sau bước 1 (đổi `\cite`). Câu 2 khác nhau ở chữ
  "here", nên là hai Element.
- Section "Intro" có danh sách con khác nhau giữa hai Version, nên cũng là hai Element.

`elements` (7 dòng: 3 sentence, 2 section, 2 document):

| element_id | kind | content |
|---|---|---|
| `2508-02872#sentence-aaaa…` | sentence | `We follow Smith et al.~\cite{Smith2020}.` |
| `2508-02872#sentence-bbbb…` | sentence | `The loss is $L=\|x\|^2$ .` |
| `2508-02872#sentence-cccc…` | sentence | `The loss is $L = \|x\|^2$ here.` |
| `2508-02872#section-dddd…` / `…eeee…` | section | `Intro` (hai dòng) |
| `2508-02872#document-…` / `…` | document | `""` (hai dòng) |

`hierarchy`: v1 có các cạnh `aaaa→dddd`, `bbbb→dddd`, `dddd→doc1`; v2 có các cạnh
`aaaa→eeee`, `cccc→eeee`, `eeee→doc2`. Element `aaaa` có mặt ở cả hai Version, với cha khác nhau.

`bibtex`: một dòng `(2508.02872, Smith2020, …)`, các trường được hợp từ `\bibitem` của v1 và
`refs.bib` của v2.

Ví dụ này nên là golden case đầu tiên (`tests/fixtures/m2/two-versions-cite-rename/`).

## 6. Bảng kiểm khi review từng module

Áp dụng cho mọi PR. Nhóm trưởng tích từng ô trước khi merge.

**Chung**
- [ ] Test chạy được offline và đạt trên `main` (dán output `pytest` vào PR).
- [ ] Output của module qua `validate_<điểm giao>()`.
- [ ] Chạy hai lần cho ra output giống hệt (I7).
- [ ] Có số phiên bản module, và tăng số khi đổi hành vi.
- [ ] Không LLM, không mô hình pretrained, không gọi mạng. Tài liệu tham khảo ghi nguồn trong docstring.
- [ ] Không commit `data/`, `*.parquet`, token.
- [ ] Ghi số liệu vào `metrics/<module>.json`: số đầu vào, số đầu ra, số lỗi theo mã, thời gian.

**Riêng từng module**

| Module | Phải chỉ ra được trong PR |
|---|---|
| M2.1 | Tỉ lệ `ready` trên Range Bảo trước và sau thay đổi; mỗi lỗi đã sửa có một fixture |
| M2.2 | Cấp mục đúng trên 30 bài gán nhãn tay; không bài nào lọt References; bài chỉ có `\subsection`; `\appendix`; `\section*{Acknowledgements}` |
| M2.3 | Bộ câu khó (≥ 40 câu) với kết quả tách mong đợi; phép kiểm "không mất chữ"; `itemize` lồng hai cấp; `table` thành `figure` |
| M2.4a | Bảng lệnh bị bỏ có nguồn; test idempotent trên mọi fixture; các dạng toán khối đều ra `equation` |
| M2.4b | Hai key khác nhau cho cùng một bài; `\bibitem` không có năm; `.bib` có `@string`/`crossref`; số entry trước/sau |
| M2.5 | I1–I9 đạt trên golden; resume bỏ qua Publication đã xong; log đủ Version; benchmark trên 100 bài |

## 7. Golden case tối thiểu (viết chung ngày 09–11/11)

| Case | Kiểm điều gì | Module chính |
|---|---|---|
| `two-versions-cite-rename` | ví dụ mục 5 | tất cả |
| `multi-file-input` | `\input` lồng, file không dùng | M2.1 |
| `comments-and-verbatim` | lệnh trong comment và trong verbatim không có tác dụng | M2.1, M2.2 |
| `levels-skip` | chỉ có `\subsection`, có `\paragraph` | M2.2 |
| `appendix-ack-refs` | giữ Appendix, Acknowledgements; bỏ References | M2.2 |
| `hard-sentences` | `et al.`, `i.e.`, `Fig. 1`, URL, `3.14`, toán có dấu chấm | M2.3 |
| `lists-figures-math` | `itemize` lồng, `table`, `$$…$$`, `align*` | M2.3, M2.4a |
| `non-tex-version` | v1 chỉ có PDF, v2 có TeX | M2.5 |

## 8. Cần chốt ngày 10/11

1. Tên trường trong `src/parse/types.py` như mục 3 (Minh viết, cả nhóm duyệt).
2. `enumerate` và `description` dùng `kind = "itemize"`? Nếu muốn loại riêng thì phải sửa
   `ELEMENT_KINDS`, tức là đổi schema chung.
3. Abstract (`\begin{abstract}`): làm `paragraph` có tiêu đề "Abstract", hay để câu là con trực
   tiếp của `document`?
4. `align`/`gather` có nhiều dòng: một `formula` cho cả khối, hay mỗi dòng một `formula`?
   Đề chỉ ghi `equation` và `$$…$$`.
5. Quy tắc gộp trường BibTeX khi hai bản khác giá trị (ví dụ hai tiêu đề khác nhau).
