# M3: hướng dẫn gán nhãn

Bản 1, ngày 20/11/2026. Thuật ngữ theo `CONTEXT.md`. Tài liệu này chốt quyết định còn mở C8 trong
`docs/data-contract.md` mục 6: định dạng file nhãn và nơi lưu.

Nguồn yêu cầu: đề M3, mục *Data Labelling* và *Data Modeling*
(<https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/matching/>).

## 1. Cần gán bao nhiêu (nhóm 5 người)

| Loại | Yêu cầu của đề | Chia cho mỗi người |
|---|---|---|
| Gán tay | ≥ 25 Publication; mỗi bài ≥ 20 BibTeX entry được gán; tổng ≥ 500 entry | Liễu, Nghiêm, Minh mỗi người 5 bài; Bảo 10 bài (gán thay Hải, vì Hải dồn sức cho bảng `bibtex`) |
| Gán tự động | ≥ 10% số Publication ngoài pool gán tay, và ≥ 10 bài | Matcher chung, Nghiêm phụ trách (mục 7) |
| Test | 5 bài gán tay + 5 bài gán tự động | xem mục 8 |
| Valid | 5 bài gán tay + 5 bài gán tự động | xem mục 8 |
| Train | phần còn lại | |

Hạn: chọn bài xong **21/11**, gán xong **tối 23/11**, kiểm chéo xong **24/11**.

## 2. Gán cái gì

Một nhãn trả lời câu hỏi: *BibTeX entry này của Publication P ứng với Reference nào của chính P?*

- **Khóa nhãn:** `(arxiv_id, citation_key)`. Đây là quyết định đã chốt trong `docs/data-contract.md`
  mục 5.1.
- **Ứng viên:** chỉ các dòng của bảng `references` có **cùng `arxiv_id`**. Không tìm ở bài khác,
  không tra Google để thêm ứng viên.
- **Đáp án:** đúng một `ref_arxiv_id` trong số các ứng viên, hoặc **rỗng** khi không ứng viên nào
  đúng. Rỗng là một nhãn hợp lệ, không phải "bỏ qua". Nhiều entry rỗng là chuyện bình thường, vì
  `references` chỉ giữ các bài có arXiv ID.

### `citation_key` lấy ở đâu

Lấy key **giống hệt** trong file nguồn của Version mới nhất có entry đó:

- `.bib`: lấy tên ngay sau `@article{`, `@inproceedings{`, …
- `\bibitem`: lấy phần trong ngoặc nhọn của `\bibitem[...]{key}`.

Đây cũng là quy tắc C6 mà bảng `bibtex` dùng: lấy key ở Version mới nhất có entry, hòa thì lấy key
nhỏ nhất theo thứ tự từ điển. Không sửa chữ hoa/thường, không bỏ ký tự. Nếu bảng `bibtex` sau
khi khử trùng lặp gộp hai key thành một, script kiểm tra (mục 6) sẽ đổi key cũ sang key được
giữ thông qua `key_map`.

### Gán những entry nào

Gán **mọi entry thật sự được trích dẫn** (`\cite`, `\citep`, `\citet`, …) trong văn bản của bài.
Không gán entry chỉ nằm trong `.bib` mà không được cite. Nhiều bài dùng chung một file `.bib`
lớn của cả lab: trên bộ mẫu 100 bài, M2 đếm được 155.529 entry sau khử trùng lặp, trung bình
khoảng 1.500 entry mỗi bài, phần lớn không được cite.

Đã chọn bài nào thì gán **hết** các entry được cite của bài đó, không gán dở 20 entry rồi dừng.
Lý do: bảng `predictions` có một dòng cho mỗi entry, và MRR trên tập test phải tính trên cả bài.

## 3. Chọn bài

Chọn trong Range của mình (Bảo chọn thêm 5 bài trong Range của Hải), từ các Publication thỏa đủ:

1. Là Publication hoàn chỉnh (có trong `tables/<member>/papers.parquet`).
2. Version mới nhất có `.bib` hoặc `\bibitem`, với **20 đến 60** entry được cite. Từ 20 trở lên
   là yêu cầu của đề; tối đa 60 để mỗi bài gán hết trong khoảng một giờ.
3. Có **ít nhất 10** dòng trong `references`. Bài quá ít ứng viên thì gần như mọi nhãn đều rỗng,
   không giúp gì cho việc huấn luyện.

Trong danh sách thỏa điều kiện, **chọn ngẫu nhiên với seed `20261120`**, lấy 5 bài và thêm 1 bài
dự phòng. Không được tự chọn bài dễ: tập test phải đại diện cho dữ liệu thật, và báo cáo phải nói
được là bài được chọn thế nào. Nếu một bài hóa ra có lỗi nguồn (ví dụ `\bibitem` viết tay, không
tách được entry) thì thay bằng bài dự phòng và ghi lý do vào cột `note`.

### Tạo file nhãn

`scripts/m3_label_sheet.py` lọc theo các điều kiện trên, xáo thứ tự với seed cố định, rồi tạo sẵn
file nhãn cho 5 bài được chọn:

```bash
# Range đã có trên HF (token đọc từ .env); chỉ tải thư mục raw của các bài được thử
python scripts/m3_label_sheet.py --hf-member <range> --labeler <tên mình> --out labels-work
# hoặc corpus cục bộ theo layout src/crawl
python scripts/m3_label_sheet.py --data-dir data/crawl-smoke --labeler bao --out labels-work
```

Kết quả nằm trong `labels-work/`:

- `labels-<labeler>-<range>.csv`: file để gán. Mỗi entry được cite là một dòng, gồm 6 cột nhãn
  (mục 5), cột `entry` chứa đoạn entry gốc, và 3 gợi ý `hint_i` / `score_i` / `hint_title_i`.
  Gợi ý được xếp theo hai tiêu chí: arXiv ID ghi sẵn trong entry thì được 1,0; còn lại theo tỉ lệ từ
  trong tiêu đề ứng viên xuất hiện trong entry. **Gợi ý chỉ để tham khảo, có thể sai. Phải tự đối
  chiếu từng dòng.**
- `candidates/<key>.csv`: toàn bộ ứng viên của từng bài (ID, tiêu đề, tác giả, ngày).
- `selection-<labeler>-<range>.json`: seed, điều kiện lọc, các bài đã chọn, bài dự phòng, và lý do
  loại từng bài đã thử. Đây là bằng chứng "chọn ngẫu nhiên" để đưa vào báo cáo.

Bạn chỉ điền `ref_arxiv_id` và `confidence`. `confidence` để trống nghĩa là dòng đó chưa gán.

**Thay bài:** ghi ID cần thay vào một file text, rồi chạy lại với `--exclude <file>`. Thứ tự xáo
không đổi, nên bài dự phòng được đẩy lên.

Chạy thử trên Range Bảo ngày 20/11: chọn được 5 bài, ra 198 entry, mất khoảng 3 giây. 104/198 dòng
có gợi ý từ 0,8 trở lên.

## 4. Quy tắc quyết định

Một entry **khớp** với một Reference khi cả hai chỉ **cùng một công trình**.

| Tình huống | Nhãn |
|---|---|
| Tiêu đề giống nhau sau khi bỏ chữ hoa/thường, dấu câu, lệnh LaTeX (`{}`, `\emph`, `--`); họ tác giả đầu trùng | Khớp |
| Năm lệch 1 (bản arXiv năm trước, bản hội nghị năm sau), hoặc entry không có năm | Vẫn khớp nếu tiêu đề và tác giả khớp |
| Entry là bản hội nghị hoặc tạp chí, Reference là bản arXiv của cùng bài | Khớp (S2 gộp về một bài) |
| Entry ghi arXiv ID (`eprint`, `journal = {arXiv:2301.00001}`, URL `arxiv.org/abs/…`) trùng `ref_arxiv_id` (bỏ hậu tố `vN`) | Khớp |
| Entry ghi arXiv ID nhưng ID đó không có trong ứng viên | Rỗng |
| Tiêu đề hơi sai chính tả, bị cắt hoặc viết tắt, nhưng tác giả và năm khớp | Khớp, `confidence = unsure` |
| Cùng tác giả, tiêu đề khác (bản mở rộng, bài khác cùng nhóm) | Rỗng |
| Sách, website, phần mềm, dataset, luận văn không phải bài arXiv | Rỗng, trừ khi ứng viên chính là tài liệu đó |
| Một `\bibitem` chứa nhiều tài liệu | Chọn tài liệu đầu tiên, `note = multi` |
| Hai ứng viên đều có vẻ đúng | Chọn ứng viên khớp cả tiêu đề lẫn năm, `confidence = unsure`, ghi cả hai ID vào `note` |

Được mở `https://arxiv.org/abs/<ref_arxiv_id>` bằng trình duyệt để xem tiêu đề, tác giả và năm
đầy đủ. Không viết script tải hàng loạt từ arxiv.org.

Không chắc thì vẫn **điền đáp án tốt nhất**, đặt `confidence = unsure` và ghi lý do. Liễu (phụ
trách M3) xem lại toàn bộ dòng `unsure`.

## 5. Định dạng file nhãn (chốt C8)

**Nơi lưu:** dataset Hugging Face của nhóm (private), thư mục `labels/`. Nhãn là dữ liệu, không
commit vào repo code (AGENTS.md quy tắc 1). Repo chỉ chứa tài liệu này và các script.

```
labels/
├── manual/<member>.csv        # nhãn tay, mỗi người một file
├── crosscheck/<member>.csv    # nhãn kiểm chéo (mục 6)
├── auto/<run>.csv             # nhãn của matcher tự động (mục 7)
└── splits.csv                 # chia tập (mục 8)
```

**File nhãn** là CSV UTF-8, phân cách bằng dấu phẩy, có dòng tiêu đề. Mỗi dòng là một entry.

| Cột | Bắt buộc | Nội dung |
|---|---|---|
| `arxiv_id` | có | Publication chứa entry, không có hậu tố version (`2508.03014`) |
| `citation_key` | có | Key theo mục 2 |
| `ref_arxiv_id` | không | Đáp án: một `ref_arxiv_id` trong `references` cùng `arxiv_id`, không có hậu tố `vN`, không có tiền tố `arXiv:`. **Để trống** khi không khớp |
| `confidence` | có | `sure` hoặc `unsure` |
| `labeler` | có | Người gán (`bao`, `lieu`, `minh`, `nghiem`); với nhãn tự động là `matcher@<commit>` |
| `note` | không | Lý do, đặc biệt khi `unsure`, `multi` hoặc thay bài |

Ví dụ:

```csv
arxiv_id,citation_key,ref_arxiv_id,confidence,labeler,note
2508.03014,vaswani2017attention,1706.03762,sure,bao,
2508.03014,he2016deep,1512.03385,sure,bao,bản CVPR của bài arXiv
2508.03014,pytorch,,sure,bao,phần mềm
2508.03014,smith2021survey,2104.01234,unsure,bao,tiêu đề bị cắt; tác giả và năm khớp
```

Upload (token đọc từ `.env`, không dán token vào chat hay code):

```python
from huggingface_hub import HfApi
from src.common.config import get_settings

s = get_settings()
HfApi(token=s.hf_token).upload_file(
    path_or_fileobj="bao.csv", path_in_repo="labels/manual/bao.csv",
    repo_id=s.hf_repo_id, repo_type="dataset", commit_message="labels: manual (bao)")
```

## 6. Tự kiểm và kiểm chéo

**Tự kiểm trước khi upload:**

```bash
python scripts/m3_check_labels.py labels-work/labels-bao-hai.csv --hf-member hai --out bao.csv
```

Script kiểm:

- đủ cột; `confidence` hợp lệ;
- mỗi `(arxiv_id, citation_key)` xuất hiện đúng một lần;
- mọi `ref_arxiv_id` khác rỗng có trong `references` của cùng `arxiv_id`;
- mỗi bài có ≥ 20 dòng, và mọi dòng đã có `confidence`; vì file nhãn đã có sẵn mọi entry được
  cite, điều này nghĩa là đã gán hết;
- in tổng số entry, số khớp, số rỗng, số `unsure` để báo trong nhóm.

Không còn lỗi thì `--out` ghi ra file sạch chỉ gồm 6 cột nhãn. File này là file để upload.

**Kiểm chéo:** mỗi người gán lại, độc lập, **1 bài** của người kế tiếp theo vòng
Bảo → Liễu → Nghiêm → Minh → Bảo. Không xem nhãn gốc trước khi gán. Ghi vào
`labels/crosscheck/<member>.csv`, cùng định dạng. Kết quả dùng cho hai việc:

- Tính **tỉ lệ đồng thuận** giữa hai người gán (4 bài, khoảng 100–300 entry). Đây là số liệu cho
  báo cáo và poster: nó cho thấy nhãn tay đáng tin tới đâu.
- Chỗ hai người gán khác nhau thì Liễu quyết, rồi sửa trong `labels/manual/`.

## 7. Nhãn tự động

Nghiêm phụ trách. Matcher dùng công cụ cổ điển như đề yêu cầu: regex arXiv ID, chuẩn hóa tiêu
đề, độ giống chuỗi tiêu đề và tác giả, so năm. Không dùng LLM hay mô hình pretrained.

- Cùng định dạng ở mục 5, `labeler = matcher@<commit>`. Có thể thêm cột `score` (độ tin của
  matcher). Cột thêm không làm hỏng file.
- Áp dụng cho **mọi** entry được cite của mỗi bài được chọn.
- Chọn ngẫu nhiên (seed `20261120`) **ít nhất 10%** số Publication ngoài pool gán tay. Không chọn
  lại bài đã gán tay.
- **Đo matcher trên nhãn tay** trước khi dùng nó gán hàng loạt, báo precision và recall. Nhãn tự
  động sai nhiều thì mô hình học theo cái sai, và test trên bài tự động cũng mất ý nghĩa.

## 8. Chia tập

`labels/splits.csv`, cột `arxiv_id,pool,partition`, trong đó `pool` là `manual` hoặc `auto`, và
`partition` là `train`, `valid` hoặc `test`.

- Gán tay: chọn ngẫu nhiên (seed `20261120`) mỗi Range đúng 1 bài vào test và 1 bài vào valid,
  để mỗi tập phủ đủ 5 Range; 15 bài còn lại vào train.
- Gán tự động: 5 bài vào test, 5 bài vào valid, còn lại vào train.
- **Chia theo Publication, không chia theo entry**: mọi entry của một bài nằm cùng một tập. Đề
  quy định như vậy, và nó tránh rò thông tin giữa các entry của cùng một bài.
- Chốt `splits.csv` **trước** khi làm đặc trưng. Sau đó không xem tập test cho đến lần đánh giá
  cuối.

## 9. Ước lượng công sức

Mỗi entry mất khoảng 1–2 phút khi có file nhãn tạo sẵn. Với 5 bài × 20–60 entry, tổng cộng
khoảng **2–4 giờ** mỗi người, cộng 30 phút kiểm chéo. Nên chia làm 2 buổi và gán xong từng bài
một, đừng để dở nhiều bài cùng lúc.
