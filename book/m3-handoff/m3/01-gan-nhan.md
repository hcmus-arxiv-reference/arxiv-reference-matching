---
title: Gán nhãn và chia tập theo Publication
kernelspec:
  name: python3
  display_name: Python 3
---

## Gán nhãn tay

Với mỗi BibTeX entry được trích dẫn, người gán nhãn đối chiếu mã arXiv, tiêu đề và tác giả với các Reference của cùng Publication. Cặp `(arxiv_id, citation_key)` xác định dòng cần gán. Người gán điền `ref_arxiv_id` khi tìm thấy Reference tương ứng, để trống khi không xác định được liên kết và đánh dấu mức chắc chắn ở `confidence`. Script kiểm tra khóa trùng, định dạng mã, số entry mỗi bài và tư cách ứng viên khi có bảng Reference.

Bảng sau tổng hợp phiếu của Nghiêm. Cột “Rỗng” đếm các entry có trường đích trống. Cột “Chưa chắc” đếm mức tin cậy và có thể giao với hai cột kết quả.

```{code-cell} python
:tags: [hide-input]
import json
from pathlib import Path
import pandas as pd
from IPython.display import display
root = next(p for p in (Path.cwd(), *Path.cwd().parents) if (p / "myst.yml").exists())
data = json.loads((root / "data/m3/labels-nghiem.json").read_text())
counts = pd.DataFrame.from_dict(data, orient="index").rename(
    columns={"rows": "Entry", "matched": "Khớp", "empty": "Rỗng", "unsure": "Chưa chắc"})
counts.index.name = "Publication"
counts.loc["Tổng"] = counts.sum()
display(counts)
```

Biểu đồ thể hiện số liên kết tìm được trong từng bài của phiếu Nghiêm. Chiều dài toàn bộ cột là số entry đã gán cho bài đó.

```{code-cell} python
:tags: [hide-input]
import plotly.express as px
papers = counts.drop(index="Tổng")
fig = px.bar(papers, x=papers.index, y=["Khớp", "Rỗng"], barmode="stack",
             labels={"value": "Số entry", "variable": "Nhãn", "index": "Publication"})
fig.update_xaxes(type="category")
fig.show()
```

## Matcher tự động

Matcher chỉ xét ứng viên trong bảng Reference của bài đang xử lý. Một mã arXiv tường minh trùng ứng viên tạo liên kết trực tiếp. Nếu không có mã, matcher chuẩn hóa tiêu đề rồi tính độ tương đồng Levenshtein, điều chỉnh điểm theo họ tác giả và năm. Ngưỡng độ giống tiêu đề là 0,90, ngưỡng điểm tổng là 0,93 và chênh lệch tối thiểu với ứng viên thứ hai là 0,035. Entry thiếu bằng chứng hoặc có nhiều ứng viên sát điểm được giữ với đích trống và lý do tương ứng.

Khi đánh giá trên nhãn tay của tập train, một dự đoán sai mã ở entry có đích được tính cả một dương tính giả và một âm tính giả. Precision đo tỷ lệ đúng trong số liên kết được dự đoán, recall đo tỷ lệ tìm lại được trong số liên kết có nhãn đích.

## Chia tập

Đơn vị chia là Publication. Mọi entry của cùng một bài thuộc cùng một tập để tránh rò rỉ thông tin. Với seed `20261120`, quy tắc giữ lại một bài tay cho valid và một bài tay cho test ở mỗi Range. Pool tự động lấy mẫu trong số bài có BibTeX, với kích thước tối thiểu bằng 10% số bài ngoài pool tay (làm tròn lên) và ít nhất 10 bài. Trong pool này, valid và test mỗi tập nhận 5 bài. Các bài đã gán nhãn còn lại thuộc train. Tệp `splits.csv` ghi lại từng quyết định để bước xây dựng đặc trưng và mô hình dùng cùng một cách chia.

[Nguồn phương pháp và quy ước gán nhãn của nhóm](https://github.com/hcmus-arxiv-reference/arxiv-reference-matching/blob/main/docs/m3-gan-nhan.md)
