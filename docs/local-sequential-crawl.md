# Chạy local: arXiv trước, S2 sau

Mở repo trong VS Code. Giữ `.env` có `CONTACT_EMAIL`, `S2_API_KEY`; không đưa
key vào notebook. Dừng crawler cũ/Kaggle trước khi chạy luồng local.

## Một lệnh trong terminal tại repo

```powershell
.\.venv\Scripts\python.exe -X utf8 -u -m scripts.crawl_local
```

Mặc định Range 2412.08848–2412.13847, chạy một lượt arXiv, rồi một lượt S2,
rồi ghép cache và xuất hai bảng cuối. Không chờ retry 30 phút theo mặc định.
Một lượt có thể còn bài lỗi; chúng được ghi pending và thử lại khi chạy lại lệnh.
`--max-passes 3` bật nhiều lượt, `--retry-delay` chỉnh thời gian chờ giữa lượt.
Ngân sách mặc định 168 giờ cho mỗi dịch vụ, có thể đổi bằng `--max-hours`.

Tự tìm cache ở `data/crawl-*`, `data/kaggle-merged` và staging của bundle cũ;
chỉ chọn thư mục có `manifests/crawl.jsonl`, không quét đệ quy toàn repo.
Import kiểm tra checksum, giữ các cache đầu vào, chỉ tải phần thiếu/hỏng.
Không bắt đầu cứng ở bài thứ 2.500: có thể còn bài lỗi nằm trước mốc này.
Lần đầu copy/checksum có thể lâu và cần dung lượng cho bản cache mới.
Cache còn trên Kaggle chưa tải về không được tính là dữ liệu local.

## Notebook VS Code

Mở `notebooks/local_crawl.ipynb`, chọn kernel `.venv/Scripts/python.exe`,
cài `ipykernel` nếu VS Code yêu cầu, rồi Run All. Hai dịch vụ chạy tuần tự
trong cùng cell. Không có kaggle_secrets, không cần Save Version hoặc ZIP.

## Resume và output

Ctrl+C một lần trong terminal hoặc Interrupt cell để dừng có kiểm soát.
Nếu dừng arXiv, S2 không tự khởi chạy tiếp. Chờ export xong trước khi đóng.
Chạy lại cùng lệnh/Run All để tiếp tục. Không chạy terminal và notebook cùng lúc.

- `data/local-sequential/arxiv/`: checkpoint arXiv và `tables/papers.parquet`.
- `data/local-sequential/s2/`: checkpoint S2 và `tables/references.parquet`.
- `data/local-sequential/merged/`: cache ghép, `tables/papers.parquet` và
  `tables/references.parquet` theo schema/điều kiện hoàn tất cũ.
- `merged/manifests/merge-report.json`: bài còn thiếu; exit code 1 là còn pending.

Parquet của từng dịch vụ được xuất định kỳ. Bảng cuối chỉ chứa Publication đủ
cả arXiv và S2, được cập nhật sau khi cả hai lượt chạy kết thúc bình thường.
Nếu dừng giữa chừng, cache từng phần vẫn còn; bảng merged có thể là lần ghép trước.

Chỉ chạy riêng một dịch vụ khi cần:

```powershell
.\.venv\Scripts\python.exe -X utf8 -u -m scripts.crawl_local --stage arxiv
.\.venv\Scripts\python.exe -X utf8 -u -m scripts.crawl_local --stage s2
```

Chế độ riêng không ghép cuối; chạy lại lệnh mặc định để kiểm tra cả hai và ghép.
Không cần xóa cache hay chuyển mốc start để resume.

Kiểm chứng ngày 29/10/2026: 116 test và 28 subtest đạt; gồm luồng tuần tự,
resume không tải lại phần đã đủ, dừng arXiv không khởi chạy S2, và xuất bảng cuối.
Không khởi chạy crawl mạng trong lần sửa này.
