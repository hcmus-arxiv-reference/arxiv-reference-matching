---
title: Đặc trưng, mô hình xếp hạng và MRR@5
kernelspec:
  name: python3
  display_name: Python 3
---

# Từ một BibTeX entry đến năm Reference ứng viên

Mỗi truy vấn là một cặp `(arxiv_id, citation_key)`. Ta lấy các Reference cùng Publication từ M1 để tạo tập ứng viên. Hai bài có thể dùng cùng một citation key, vì vậy phải giữ cả hai thành phần của khóa.

## Đặc trưng và mô hình đối chứng

Để đo mức thông tin có sẵn trong tiêu đề, chúng tôi chạy một mô hình đối chứng trên 5 Publication đã có nhãn của Liệu. Với mỗi ứng viên, lấy tập từ riêng biệt $T$ của tiêu đề Reference và tập từ $E$ của toàn bộ entry nguồn. Điểm là $|T \\cap E|/|T|$, bằng 0 nếu thiếu tiêu đề. Hai văn bản được chuẩn hóa Unicode NFKC, chuyển về chữ thường và tách thành các cụm chữ hoặc số. Sắp theo điểm giảm dần, hòa thì lấy arXiv ID theo thứ tự từ điển. Một tiêu đề ngắn có thể đạt điểm tuyệt đối chỉ nhờ vài từ chung xuất hiện trong entry. Đây là lý do cần kiểm tra thêm tác giả và ngữ cảnh trích dẫn.

Mô hình đối chứng dùng một đặc trưng và không cần huấn luyện. Trong thiết kế mô hình học có giám sát của M3, mỗi cặp entry–Reference tạo một mẫu. Ví dụ, năm xuất bản lệch một năm có thể phản ánh khoảng cách giữa preprint và bản hội nghị. Mức trùng họ tác giả giúp phân biệt hai tiêu đề gần nhau. Đặc trưng ngữ cảnh phải nối vị trí trích dẫn với cây `hierarchy` của đúng Publication và Version trên dữ liệu M2 mới. Số lần một entry được cite là hằng số giữa các ứng viên của chính entry đó. Để khai thác ngữ cảnh cho xếp hạng, có thể so từ ở câu chứa citation với tiêu đề từng Reference.

Tập train dùng để học điểm của cặp, valid dùng để chọn cấu hình, rồi xếp hạng trên test theo Publication. Đặc trưng hierarchy thực tế và cấu hình mô hình cuối thuộc [#69](https://github.com/hcmus-arxiv-reference/arxiv-reference-matching/issues/69) và [#68](https://github.com/hcmus-arxiv-reference/arxiv-reference-matching/issues/68). Chương sẽ ghi kết quả valid và test khi có bảng dự đoán của lần chạy đó.

## Đánh giá theo entry

Nếu đáp án xuất hiện tại vị trí $r$ trong top 5, entry đóng góp $1/r$. Đáp án ngoài top 5 hoặc nhãn rỗng đóng góp 0. Mẫu số gồm mọi entry được gán nhãn trong tập đánh giá. Ví dụ, ba entry lần lượt có đáp án ở hạng 2, ngoài top 5 và rỗng cho MRR@5 bằng $(1/2+0+0)/3=1/6$. Cách tính theo [đề M3, mục Model Evaluation](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/matching/).

### Kết quả đối chứng trên 5 Publication của Liệu

Bảng dưới được tính khi build từ số đếm theo hạng. Dòng tổng cộng gộp theo entry, nên bài có nhiều entry đóng góp nhiều hơn. Đây là phép đo mô tả trên mẫu 5 bài. Tỉ lệ entry có đáp án cho biết mức MRR@5 tối đa trên chính mẫu này.

```{code-cell} python
:tags: [remove-input]
import json
from pathlib import Path
import pandas as pd

root = next(p for p in (Path.cwd(), *Path.cwd().parents) if (p / "myst.yml").is_file())
counts = json.loads((root / "data/m3/lieu-baseline.json").read_text(encoding="utf-8"))
records = []
for pid, item in counts.items():
    ranks = item["ranks"]
    records.append([pid, sum(ranks) + item["missed"] + item["empty"],
                    item["empty"], *ranks, item["missed"],
                    sum(n / rank for rank, n in enumerate(ranks, 1))])
df = pd.DataFrame(records, columns=["Publication", "Entry", "Rỗng", "H1", "H2", "H3",
                                    "H4", "H5", "Ngoài top 5", "Tổng RR"]).set_index("Publication")
df.loc["Tổng"] = df.sum()
df["MRR@5"] = df.pop("Tổng RR") / df["Entry"]
df["Trần MRR@5"] = 1 - df["Rỗng"] / df["Entry"]
df.round(4)
```

Trong 156 entry có đáp án, 151 đáp án đứng đầu, một đứng thứ hai, một đứng thứ tư và ba nằm ngoài top 5. Cả năm trường hợp không đứng đầu đều thuộc Publication `2410.11155`. Tập nhỏ và gợi ý khi gán nhãn cũng dựa vào tiêu đề nên điểm đối chứng có thể lạc quan khi áp dụng cho bài mới.

Có thể tái lập số đếm bằng `python m3/measure_baseline.py LABELS SHEET REFERENCES.parquet data/m3/lieu-baseline.json`, với file nhãn của Liệu, phiếu gán nhãn có cột entry và bảng Reference của cùng Range. Script chỉ dùng nhãn để tính điểm đánh giá sau khi đã xác định quy tắc xếp hạng.
