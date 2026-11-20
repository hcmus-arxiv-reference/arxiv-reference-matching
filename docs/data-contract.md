# Hợp đồng dữ liệu giữa các milestone

Ngày 2026-11-05. Nhóm trưởng Nguyễn Thành Bảo đã duyệt C1–C7 và C9 cùng ngày; C8 còn mở
(mục 6).
Tài liệu này ghi lại những gì một milestone giao cho milestone sau: dữ liệu nào, ở đâu,
khi nào được coi là dùng được, và bất biến nào phải giữ. Schema cột nằm trong code
(`src/common/schema.py`); tài liệu này không chép lại kiểu cột mà ghi phần code không
diễn đạt được.

Nguồn đề:
[tổng quan](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/),
[Crawling](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/crawling/),
[Parsing](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/parsing/),
[Matching](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/matching/).
Thuật ngữ theo `CONTEXT.md`.

Ký hiệu: **[Đề]** là yêu cầu của đề, không bàn lại. **[Đã chốt]** là quyết định của nhóm
đã ghi trong `AGENTS.md`, ADR hoặc `schema.py`. **[Mở Cn]** là quyết định chưa chốt, xem
mục 6.

## 1. Luồng dữ liệu

```
M1 Crawling          H1          M2 Parsing            H2         M3 Matching
Range ─▶ corpus thô ─────▶ elements, hierarchy, bibtex ─────▶ nhãn, feature, mô hình
        papers, references                                         predictions
                    \___________________________ H3 ___________________________/
                         dataset Hugging Face cuối: 6 bảng, public, Parquet shard
```

- **H1** (M1 → M2): corpus thô của mọi Range và hai bảng Crawling.
- **H2** (M2 → M3): ba bảng Parsing; M3 còn đọc `references` của M1.
- **H3** (cả ba → nộp cuối): 6 bảng gộp từ mọi Range.

Không có lần nộp dữ liệu trung gian **[Đề]**; H1 và H2 là chuyển giao nội bộ nhóm.

## 2. Quy ước chung

- `arxiv_id`: ID gốc, không hậu tố Version; giữ dạng cũ như `hep-th/9901001` **[Đề]**.
- Publication key: `publication_key()`: `/` và `.` đổi thành `-` (`2508.02872` → `2508-02872`)
  **[Đã chốt]**. Dùng cho tên thư mục và tiền tố `element_id`.
- Version: số nguyên ≥ 1; Publication chỉ có một lần nộp vẫn là `v1` **[Đề]**.
- Cột phẳng, kiểu nguyên thủy; chỉ cho phép list string một cấp; không struct, không JSON
  trong cột **[Đề]**. List: `null` là chưa biết, `[]` là rỗng đã biết **[Đã chốt]**.
- Ngày: chuỗi ISO-8601 **[Đã chốt]**.
- Mọi bảng được tạo qua `from_records()` và kiểm bằng `validate()`. `validate()` chỉ kiểm
  một bảng; bất biến liên bảng ở mục 5.3.

## 3. H1: corpus M1 → M2

### 3.1 Vị trí

| Nơi | Đường dẫn | Nội dung |
|---|---|---|
| Máy crawl | `data/raw/<key>/v<n>/` | `.tex`/`.bib` giữ đường dẫn tương đối gốc, `source.json` (receipt) |
| Máy crawl | `data/metadata/<key>.json` | metadata Publication (`format: 1`) |
| Máy crawl | `data/references/<key>.json` | dòng S2 **thô**, gồm cả reference không có arXiv ID **[Đề]** |
| Máy crawl | `data/manifests/crawl.jsonl` | Manifest, chỉ để resume |
| HF (private) | `raw/<member>/<key>/v<n>/` | `.tex`/`.bib`, `source.json`, `metadata.json`, `references.json` (hai file sau lặp lại ở mỗi Version) |
| HF (private) | `tables/<member>/{papers,references}.parquet` | bảng Crawling của một Range |

Manifest **không** được upload. Mọi thứ M2 và M3 cần phải suy ra được từ file, không từ
Manifest (ADR 0002: file là nguồn gốc).

### 3.2 Khi nào một Version dùng được

Một thư mục Version là **Version đã xác minh** khi `verified_source()` chấp nhận nó:

- `source.json` có `format: 1`, `arxiv_id` và `version` khớp tên thư mục;
- `status` là `success` hoặc `non_tex`;
- danh sách `.tex`/`.bib` trên đĩa khớp đúng danh sách trong receipt, checksum từng file khớp,
  không symlink, không đường dẫn thoát thư mục;
- `success` khi và chỉ khi có ít nhất một `.tex`.

Version `non_tex` (chỉ PDF, docx) là Version đã xác minh nhưng không có TeX. M2 vẫn phải ghi
nhận nó như một bản ghi rỗng **[Đề]**. Vì root không có dòng `hierarchy`, Version rỗng không
có dòng nào trong các bảng; bản ghi rỗng nằm trong log parse theo từng Version, với `status`
∈ {`parsed`, `empty_non_tex`, `failed`, `missing`}. Báo cáo độ phủ Version đọc từ log này
**[Đã chốt C4, 2026-11-05]**.

Lúc crawl, Runner và Export kiểm thêm: Manifest có bản ghi Version đó với cùng `status` và
cùng `checksum`. Phép kiểm này chỉ có trên máy crawl.

### 3.3 Khi nào một Publication hoàn chỉnh

Publication **hoàn chỉnh** khi:

1. metadata hợp lệ: `arxiv_id` khớp, `versions ≥ 1`, `len(revised_dates) == versions − 1`,
   dòng `papers` qua `validate()`;
2. mọi Version `v1..v<versions>` đều là Version đã xác minh;
3. file references hợp lệ: `format: 1`, `arxiv_id` khớp, ánh xạ sang dòng `references` không lỗi.

Chỉ Publication hoàn chỉnh mới được Export ghi vào `papers`/`references` và được upload.
Ngoại lệ: chế độ `references=False` của `run_crawl` bỏ điều kiện 3 và không xuất bảng
`references`. Publication thiếu Version vẫn nằm trên máy crawl để thử lại.

### 3.4 Cam kết của M2 với dữ liệu H1

- Chỉ đọc; không sửa, không xóa file raw **[Đã chốt]**.
- Từ chối Version có receipt sai; không tự hạ mức kiểm tra.
- Độ phủ Version **[Đề]** tính trên `versions` trong metadata, không trên số thư mục tìm thấy.
- Parser chỉ nhận thư mục Version và metadata trên đĩa, bất kể lấy từ máy crawl hay tải từ HF,
  và chỉ kiểm bằng file theo 3.2–3.3; không đọc Manifest **[Đã chốt C9, 2026-11-05]**.

## 4. H2: bảng Parsing → M3

### 4.1 `elements`, `hierarchy`

- Một dòng `elements` cho mỗi Element **phân biệt** trên mọi Version của một Publication;
  Element giống hệt nhau sau chuẩn hóa dùng chung một `element_id` **[Đề]**.
- `element_id` = `<publication key>#<discriminant>`, discriminant duy nhất trong Publication
  **[Đề]**. Phải tất định: chạy lại Parser trên cùng input cho cùng ID (yêu cầu tái lập của
  `AGENTS.md`). Discriminant là `<kind>-<16 hex đầu của sha256>`, băm theo cây con
  **[Đã chốt C1, 2026-11-05]**:
  - lá (Sentence, Block formula, Figure): băm `(kind, content)`;
  - nút cấu trúc (Section…, `item`, `itemize`, `document`): băm `(kind, content, danh sách ID
    con theo thứ tự)`.

  Hệ quả: câu giống hệt dùng chung ID ở mọi nơi; Section không đổi giữa hai Version dùng
  chung ID, Section bị sửa nhận ID mới nhưng câu không đổi bên trong giữ ID cũ; hai heading
  trùng tên nhưng khác nội dung (ví dụ nhiều `\paragraph{Proof.}`) có ID khác nhau.
- Một dòng `hierarchy` là một cạnh nút → cha trong một Version **[Đề]**; `parent_id` không null,
  nên root chỉ nằm trong `elements` **[Đã chốt]**.
- Khóa `hierarchy` là `(arxiv_id, version, element_id, parent_id)`: Element dùng chung có thể
  có nhiều cha trong một Version (cùng câu dưới hai Section). Hai bản giống hệt dưới **cùng**
  một cha gộp thành một cạnh; Parser ghi số trường hợp này vào log
  **[Đã chốt C2, 2026-11-05]**.
- Thứ tự anh em không có cột trong bảng. Thứ tự chính thức nằm trong dữ liệu trung gian của M2
  theo từng Publication. Parser ghi dòng `hierarchy` theo thứ tự đọc của tài liệu, nhưng thứ tự
  dòng chỉ là best-effort, không bảo đảm sau khi gộp shard **[Đã chốt C3, 2026-11-05]**.
- `kind` thuộc `ELEMENT_KINDS` hiện tại, giữ cả `chapter` và `subsubsection`. `content` của
  Section, Subsection, Paragraph là tiêu đề đã chuẩn hóa; `item` là nút chứa các Sentence;
  `document` và `itemize` có `content` rỗng và **không** khử trùng lặp theo nội dung (nếu
  không, mọi `itemize` của một Publication sẽ thành một Element) **[Đã chốt C5, 2026-11-05]**.
- Có Section References thì bỏ; giữ Acknowledgements, Appendices kể cả `\section*` **[Đề]**.

### 4.2 `bibtex`

- Một dòng cho mỗi BibTeX entry sau khi đổi `\bibitem` và khử trùng lặp giữa các Version;
  hợp các trường của entry trùng, không bỏ thông tin **[Đề]**.
- `\cite` dùng key bị bỏ phải được đổi sang key đã chọn **[Đề]**, nên khử trùng lặp BibTeX
  phải xong **trước** khi chốt `content` của Element chứa `\cite`.
- `citation_key` là khóa nối nhãn của M3. Quy tắc chọn key phải tất định, nếu không nhãn tay
  sẽ trỏ sai sau mỗi lần chạy lại. Hợp đồng chỉ yêu cầu quy tắc tất định và có ghi tài liệu;
  thành viên BibTeX chọn quy tắc. Gợi ý mặc định: lấy key ở Version mới nhất có entry, hòa thì
  lấy key nhỏ nhất theo thứ tự từ điển **[Đã chốt C6, 2026-11-05]**.
- `year` không đọc được: `null`, giá trị thô ghi vào log của bộ trích BibTeX **[Đã chốt]**.

### 4.3 M3 dùng gì

- Ứng viên cho một BibTeX entry là các dòng `references` **cùng `arxiv_id`** **[Đề]**.
  Mỗi entry có tối đa một Reference đúng.
- `references` chỉ chứa Reference có arXiv ID, đã gộp trùng theo `ref_arxiv_id` (từ Danh sách
  trích dẫn S2, `CitationList`);
  `ref_submission_date` là `publicationDate` của Semantic Scholar, `null` khi S2 không có
  ngày ISO hợp lệ **[Đã chốt 10/11/2026, giảng viên cho phép]**. Đây là ngày xuất bản theo
  S2, có thể khác ngày nộp v1 trên arXiv.
- M3 có thể dùng `hierarchy` làm feature **[Đề]**.

## 5. H3: M3 và dataset cuối

### 5.1 `predictions` và nhãn

- Một dòng cho mỗi BibTeX entry của mỗi Publication thuộc train, valid hoặc test **[Đề]**.
- `cand_1..cand_5` lấy từ `references.ref_arxiv_id` của cùng Publication; `groundtruth_arxiv_id`
  null khi không có Reference đúng hoặc chưa biết.
- Định dạng file nhãn tay/tự động do nhóm chọn nhưng phải ghi tài liệu **[Đề]**; khóa nhãn là
  `(arxiv_id, citation_key)` **[Đã chốt]**; định dạng và nơi lưu **[Mở C8]**.

### 5.2 Dataset nộp cuối

**[Đề]**: dataset Hugging Face **public**; Parquet chia shard; một schema tường minh thống nhất;
`README.md` (dataset card) có YAML config ánh xạ mỗi bảng tới `data/<table>/*.parquet`;
không loading script.

Layout hiện tại (`tables/<member>/…`, `raw/<member>/…`, private) là nơi chứa tạm theo Range.
Bảo làm bước gộp một lần, sau khi mọi Range xong và trước khi nộp M3: hợp các Range, kiểm khóa
chính trên toàn bộ shard, kiểm bất biến 5.3, ghi ra `data/<table>/` của dataset public.
`raw/` **không** nằm trong dataset public: đề chỉ yêu cầu 6 bảng, và `.tex` gốc chịu license
của từng bài arXiv **[Đã chốt C7, 2026-11-05]**.

### 5.3 Bất biến liên bảng (QA trước khi nộp)

| Bất biến | Bảng |
|---|---|
| `references.arxiv_id` ∈ `papers.arxiv_id` | references |
| `elements.arxiv_id` ∈ `papers.arxiv_id`; tiền tố `element_id` = `publication_key(arxiv_id)` | elements |
| `element_id`, `parent_id` ∈ `elements` cùng `arxiv_id`; `version` ≤ số Version của Publication | hierarchy |
| mỗi Version: không chu trình, đúng một root, mọi Element đi tới được root (Element dùng chung có thể có nhiều cha, C2) | hierarchy |
| `bibtex.arxiv_id` ∈ `papers.arxiv_id` | bibtex |
| `(arxiv_id, citation_key)` ∈ `bibtex`; `cand_*` ∈ `references` cùng `arxiv_id` | predictions |
| khóa chính duy nhất trên toàn bộ shard, không chỉ từng file | cả 6 |

## 6. Quyết định còn mở

| # | Câu hỏi | Ảnh hưởng | Người quyết |
|---|---|---|---|
| C8 | Định dạng và nơi lưu file nhãn | M3, README | Thành viên Matching |

## 7. Thay đổi hợp đồng

- Đổi cột, kiểu, khóa hoặc enum: sửa `src/common/schema.py` và mục tương ứng ở đây trong
  cùng một commit, sau khi nhóm trưởng duyệt (`AGENTS.md` mục 4.4).
- Khi một mục **[Mở]** được chốt: chuyển sang **[Đã chốt]**, ghi ngày, xóa dòng ở mục 6.
