# Bối cảnh triển khai

## Thuật ngữ

- **Publication:** bài arXiv có ID gốc, không kèm hậu tố version.
- **Version:** một phiên bản của Publication (`v1`, `v2`, …).
- **Reference:** bản ghi Semantic Scholar của bài được trích dẫn có arXiv ID.
- **BibTeX entry:** mục trích dẫn sau chuẩn hóa và khử trùng lặp.
- **Element:** nút của cây phân cấp tài liệu.
- **Range:** dải arXiv ID giao cho một thành viên.

## Phạm vi Nguyễn Thành Bảo

Người dùng cung cấp: tháng **2025-08**, số thứ tự **2872–7871**.
Range bao gồm hai đầu: **`2508.02872`–`2508.07871`**, tương ứng
**5.000 ID Publication được giao**; chưa xác minh số Publication tải được.
Mỗi Publication cần thu thập mọi Version. Hiện chưa có file `.tex` mẫu.

## Trạng thái

Người dùng đã xác nhận `papers.authors`, `papers.revised_dates`,
`references.ref_authors` dùng **list of strings** theo đề Crawling
(`pyarrow.list_(pyarrow.string())`). Không chuyển thành chuỗi/JSON blob.
Người dùng cho phép cập nhật AGENTS.md để lưu thông tin dài hạn.
Email liên hệ cho User-Agent đã có trong `.env`, chỉ lưu cấu hình thật cục bộ.
Đã thêm biến còn thiếu vào `.env`, giữ nguyên giá trị đã có. Hiện thiếu
`HF_TOKEN` và `HF_REPO_ID`; `scripts.check_hf` báo thiếu cấu hình trước khi
gọi mạng. Chạy lại bằng `.venv/bin/python -m scripts.check_hf` khi đã điền.
Người dùng đã chốt đường dẫn Hugging Face `raw/<member>/<publication key>/v<n>/`
và `tables/<member>/<tên bảng>.parquet`; `upload_dir` chỉ ghi vào raw của mình.

Đang ở giai đoạn 0 của `AGENTS.md`, bắt đầu đối chiếu trang Crawling theo
yêu cầu người dùng. Bốn module hạ tầng đã đặt tại
`src/common/{schema,config,hf_io,metrics}.py`, có `.env.example` và dependencies.
Đã chạy `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q`:
54 test đạt, 15 subtest, trên PyArrow 23.0.1 và pytest 9.1.1.
Hugging Face dùng mock, chưa thử kết nối/upload/download thật.
Xem [review hạ tầng](docs/infrastructure-review.md) để biết giới hạn metrics
và phần schema chưa chốt.
Cập nhật 2026-10-19: đã có source crawler và manifest JSONL theo Version,
CLI `scripts/crawl.py`, cùng ba test crawl. Kết quả test offline: 57 đạt, 9 xfail (lỗi còn mở),
15 subtest đạt trên Python 3.14.7; chưa chạy crawl thật hoặc xác minh resume trên
corpus thật. [Review crawler](docs/crawl-review.md) ghi các lỗi đã tái hiện;
chưa đánh dấu Crawling hoàn thành. Parser chưa triển khai, schema toàn dự án
chưa đóng băng. Đã đọc cả ba trang đề; Matching hiện quy định sáu bảng,
danh sách bảy bảng trong README cũ đã được đánh dấu lỗi thời.
Cách biểu diễn lần xuất hiện trong hierarchy vẫn cần chốt theo
[docs/schema-review.md](docs/schema-review.md).

Chi tiết đối chiếu: [docs/crawling-requirements.md](docs/crawling-requirements.md).

Kiểm tra Hugging Face ngày 2026-10-19: sau khi người dùng điền `.env`,
`scripts.check_hf` gọi API thật thành công (exit code 0), tạo hoặc xác minh
dataset private. Chưa upload dữ liệu và chưa kiểm thử upload/download thật.
Các ghi nhận thiếu cấu hình phía trên là trạng thái lịch sử ngày 2026-10-16.
