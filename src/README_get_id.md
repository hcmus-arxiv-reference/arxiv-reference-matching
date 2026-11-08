# Hướng dẫn lấy danh sách arXiv ID & Metadata theo Range

Script `src/get_id_range_script.py` sinh danh sách arXiv ID trong khoảng `[start, end]` (hỗ trợ cả dải cùng tháng và vắt qua 2 tháng), sau đó gọi arXiv API theo từng batch 50 ID để lấy metadata và danh sách toàn bộ các phiên bản (`v1..vN`).

## 1. Cấu hình Proxy (tùy chọn)
Mở `src/get_id_range_script.py`:
- **Chạy trực tiếp (không proxy):** Đặt `PROXY_ENABLED = False`.
- **Chạy qua Webshare Rotating Proxy (tránh HTTP 429 khi cào nhiều range):** Đặt `PROXY_ENABLED = True` và điền `WEBSHARE_USERNAME`, `WEBSHARE_PASSWORD`.

## 2. Cách chạy
Đứng tại thư mục gốc của repo và chạy:

```bash
# Chạy 1 range (tự chuẩn hóa 5 chữ số sau dấu chấm)
python3 src/get_id_range_script.py --start 2410.08025 --end 2410.13024

# Hoặc chạy tuần tự nhiều range
python3 src/get_id_range_script.py --start 2508.02872 --end 2508.07871 \
  && python3 src/get_id_range_script.py --start 2410.08025 --end 2410.13024 \
  && python3 src/get_id_range_script.py --start 2412.08848 --end 2412.13847 \
  && python3 src/get_id_range_script.py --start 2409.08594 --end 2409.13593
```

## 3. Output & Checkpoint
- Mặc định mỗi range xuất ra 1 file riêng tại: `src/data/arxiv_metadata_<start>_<end>.json` (có thể đổi bằng `--output <path>`).
- **Tự động Resume:** Script lưu checkpoint sau mỗi batch 50 bài. Nếu bị ngắt giữa chừng, chạy lại đúng lệnh cũ để tiếp tục từ batch đang dở.
- **Kiểm tra tiến độ:** Xem trường `"total_papers"` trong khối `"range"` ở đầu file JSON (khi `"total_papers"` bằng `"total_ids"` là đã cào xong).
