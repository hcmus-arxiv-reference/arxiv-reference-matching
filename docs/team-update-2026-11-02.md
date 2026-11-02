# Cập nhật cho nhóm 02/11/2026: ghép 5 pipeline crawl

**Tóm tắt.** Không bản crawl nào của mọi người bị bỏ. `main` là khung chung, phần tốt
nhất của từng người được ghép vào khung đó theo từng bước. Nhánh của mỗi bạn giữ
nguyên để làm case study trong báo cáo. Việc cần làm và hạn **Thứ Năm 05/11/2026**
ở [mục 6](#6-việc-của-từng-bạn-hạn-thứ-năm-05112026).

Thuật ngữ (Stage, Engine, Cách cài đặt Stage) theo [`CONTEXT.md`](../CONTEXT.md).

## 1. Vì sao phải ghép

- **Vấn đề:** 5 bản crawl đều chạy được, nhưng không có interface chung giữa các bước.
  Vì vậy chưa so được bản nào tốt hơn ở bước nào, và cũng chưa ghép được.
- **Hướng đi:** lấy `src/crawl/` trên `main` làm khung (Engine duy nhất). Mỗi bước
  (Stage: Discovery, Source fetch, References, Manifest, Export, Runner) chọn một cách
  cài đặt tốt nhất trong 5 bản. Quyết định và lý do:
  [ADR 0001](adr/0001-src-crawl-la-khung-duy-nhat.md).
- **Cách so:** theo đúng tiêu chí chấm, chạy cả 5 bản trên cùng một tập ID mẫu, trên
  Colab CPU (mục 4).
- **Bản cuối:** một codebase chạy cho toàn bộ Range của nhóm.

## 2. Năm cách cài đặt đang có

| Người | Ở đâu | Điểm nổi bật | Trạng thái |
|---|---|---|---|
| Bảo | `main`, `src/crawl/` | Receipt checksum cho từng Version, Manifest để resume, validator, upload Hugging Face | Khung chung |
| Liễu | tag `lieu-standalone-final` | Discovery theo lô 50 ID, S2 chạy song song với tải source, tải tiếp bằng HTTP Range, bảng chờ khi bị 429/5xx | Lô và S2 song song đã ghép (PR #6); phần HTTP ở PR #11 |
| Hải | nhánh `Hai` | Kho làm việc SQLite, notebook Kaggle, xuất Parquet/ZIP | Case study, chờ so |
| Minh | nhánh `feat/Minh-crawler` | Notebook arXiv, SQLite, S2 bất đồng bộ nhiều worker | Case study, chờ so |
| Nghiêm | nhánh `feat/nghiem-crawler` | Lô 50 ID, giãn cách 3,1 s, receipt kèm số đo, tách trạng thái source và S2, bổ sung ngày (`enrich_dates`) | Case study, chờ so |

Phần nào thắng ở bước so sẽ được chuyển vào khung qua PR, ghi công người viết trong code
và README. Nhánh gốc không bị sửa hay xóa.

## 3. Bảo đã làm tuần này

Đã giải xung đột giữa bản local của Bảo và các commit của Liễu trên `main`, và dọn
các tài liệu cũ. Mọi thay đổi đi qua PR; lịch sử cũ vẫn giữ ở nhánh
`backup/local-2026-10-25` và tag `lieu-standalone-final`.

| PR | Nội dung |
|---|---|
| #6 | Sửa `main` để bộ test chạy lại được; `python -m src.milestone1_crawler` chạy trên khung chung |
| #7 | Kiểu cột cho Milestone 2 trong schema chung |
| #8 | Bước đầu M2: gom source của một Version |
| #9 | Viết lại README và AGENTS theo trạng thái thật |
| #10 | Script thống kê M1 từ cache đã xác minh |
| #11 | Chuyển cải tiến HTTP của Liễu vào khung: tải tiếp file bị cắt, giới hạn thời gian, bảng chờ |

## 4. Cách so

Theo [docs/benchmark/README.md](benchmark/README.md), gồm hai giai đoạn:

1. **Sàng lọc:** mỗi bạn nộp `benchmark.json` cho lượt crawl đã chạy trên Range của
   mình. Giai đoạn này chủ yếu xem **chất lượng dữ liệu**. Số thời gian và RAM chỉ để
   tham khảo, vì mỗi người chạy trên máy và mạng khác nhau.
2. **Đối chứng:** các bản ứng viên chạy trên cùng tập ID mẫu, cùng Colab CPU, cùng
   harness đo. Số hiệu năng dùng để chọn lấy từ giai đoạn này.

Lưu ý: validator hiện chỉ đọc được layout của `src/crawl/`. Output lưu theo cách khác
(SQLite, thư mục riêng…) **không bị coi là sai**. Bảo sẽ chuyển layout hoặc so ở giai
đoạn đối chứng. Còn cách chạy benchmark cuối (một Colab cho cả 25.000 ID, hay mỗi người
chạy Range của mình rồi cộng lại) thì Bảo đang hỏi giảng viên.

## 5. Sắp tới

- Đưa discovery theo lô và S2 song song thành cách cài đặt mặc định trong khung.
- Script thống kê đọc Manifest của khung.
- Cấu hình Range nhiều Đoạn, để một lệnh chạy được Range của cả nhóm.

## 6. Việc của từng bạn (hạn Thứ Năm 05/11/2026)

- **Mọi người:**
  - Nộp `benchmarks/<github-username>.json` theo mẫu
    [benchmark.template.json](benchmark/benchmark.template.json), commit lên nhánh của
    mình. Gửi Bảo đường dẫn tới thư mục output đã crawl.
  - Trường nào không có số đo thật thì để `null`, không ước lượng.
- **Mọi người:**
  - Giữ nguyên nhánh cũ, không sửa, không xóa.
  - Thay đổi crawler mới thì mở PR vào `src/crawl/` trên `main`.
- **Liễu:** xem PR #11. Đây là cải tiến HTTP của bạn đã chuyển vào khung (Bảo đã review);
  góp ý nếu có chỗ chưa đúng ý bạn.
- **Minh:** xác nhận `last_september_id` thật cho Range của bạn.
- **Nghiêm:** xác nhận GitHub username.

Có thắc mắc thì nhắn Bảo. Tài liệu liên quan: [`CONTEXT.md`](../CONTEXT.md),
[`docs/adr/`](adr/), [docs/benchmark/README.md](benchmark/README.md).
