# Handoff 2026-10-31: chốt kiến trúc ghép crawler 5 nhánh

Tài liệu này dành cho agent (Codex) nhận việc review và push kết quả buổi trao đổi
ngày 2026-10-31 giữa nhóm trưởng (Bảo) và Claude. Nó cũng là điểm tiếp tục cho
buổi sau. Quy tắc chung của repo nằm trong `AGENTS.md`, áp dụng nguyên vẹn.

## Việc cần làm

1. **Áp patch** `grill-2026-10-31.patch` (Bảo cung cấp) lên một nhánh mới tách từ
   `origin/main`: `docs/architecture-grilling-2026-10-31`. Chạy
   `git apply --check` trước rồi mới `git apply`.
   *Xong khi:* `git status` liệt kê đúng 7 file: `README.md`, `CONTEXT.md` (sửa) và
   `docs/adr/0001-*.md`, `docs/adr/0002-*.md`, `docs/benchmark/README.md`,
   `docs/benchmark/benchmark.template.json`, file handoff này (mới). Không có file nào khác.

2. **Review đối chiếu code.** Mọi câu khẳng định *về sự thật* trong 7 file phải
   khớp với code trên `main`. Danh sách cần kiểm tra:
   - `src/milestone1_crawler.py` có `LieuPipeline`, `BatchedDiscovery`, và tổng độ dài
     khoảng 800 dòng.
   - `CrawlPipeline` (`src/crawl/pipeline.py`) và `LieuPipeline` cùng ghi
     `raw/<publication-key>/v<n>/` và cùng schema Parquet (`src/common/schema.py`).
   - `tests/test_lieu_crawler.py` tồn tại và import từ `src.milestone1_crawler`.
   - `src/benchmark.py`: mặc định lấy mẫu RSS cả cây tiến trình mỗi 1 giây,
     disk mỗi 5 giây; xuất `peak_rss_mb`, `avg_rss_mb`, `peak_disk_mb`.
   - `make_stats` đọc log gốc của Liễu, chưa đọc `crawl.jsonl`
     (đối chiếu `docs/lieu-integration.md`).
   - Mô tả nhánh khác trong ADR 0002: nhánh `Hai` dùng SQLite (`src/crawl/store.py`);
     nhánh `feat/Minh-crawler` có `src/Database/script.sql` với `authors TEXT`
     và một cột `revised_date`.
   - `benchmark.template.json` là JSON hợp lệ.

   Sửa trực tiếp những câu sai sự thật. **Các quyết định là của Bảo**: không đổi
   nội dung quyết định trong ADR, CONTEXT.md hay README. Thấy quyết định có vấn đề
   thì ghi vào mục "Ghi chú review" ở cuối file này.
   *Xong khi:* mỗi gạch đầu dòng ở trên được đánh dấu đúng/đã sửa, kèm `file:dòng`
   làm bằng chứng, trong mục "Ghi chú review".

3. **Chạy test** theo lệnh trong `README.md`.
   *Xong khi:* có số test đạt/thất bại thật. Patch chỉ đụng tài liệu, nên nếu có test
   thất bại thì ghi nguyên văn vào "Ghi chú review", không sửa code.

4. **Commit và push** nhánh `docs/architecture-grilling-2026-10-31`, rồi mở PR vào
   `main`. Mô tả PR tóm tắt các quyết định và link tới mục "Ghi chú review".
   Chỉ push thẳng `main` khi Bảo yêu cầu rõ.
   *Xong khi:* PR đã mở và Bảo có link.

## Trạng thái quyết định (tham chiếu)

Đã chốt. Nguồn chính là file được trỏ tới, không chép lại ở đây:

- Range là của từng thành viên; codebase chung nhận Range làm tham số → `CONTEXT.md`.
- Crawler được chia theo **Stage**: Discovery, Source fetch, References, Manifest,
  Export, Runner → `CONTEXT.md`.
- `src/crawl/` là Engine duy nhất; phần của Liễu chuyển vào khung → ADR 0001,
  lưu ý trong `README.md`.
- File trên đĩa là nguồn dữ liệu gốc; Parquet là bảng xuất ra → ADR 0002.
- So sánh giữa các thành viên làm 2 giai đoạn (sàng lọc theo chất lượng dữ liệu,
  rồi đối chứng hiệu năng trên Colab) → `docs/benchmark/README.md`.
  Bảo sẽ gửi tin nhắn cho nhóm sau khi tự kiểm tra mẫu benchmark.
- Deadline: còn khoảng 30 ngày tính từ 2026-10-31.

Còn mở, sẽ tiếp tục ở buổi sau:

- **Q7**: tập ID đối chứng. Đề xuất: 100 ID, 20 ID từ Range của mỗi người, chọn ngẫu
  nhiên với seed cố định. Còn một mâu thuẫn chưa giải: Bảo nói tổng khoảng 2.500,
  nhưng repo ghi mỗi người được giao 5.000 ID.
- **Q9**: ai viết validator cho giai đoạn sàng lọc (`scripts/validate_crawl.py`).
  Đề xuất: Claude viết, kèm test.
- Sau khi chốt Q7 và Q9: Bảo chạy `/improve-codebase-architecture` trên `main` để
  thiết kế interface cho từng Stage trước khi ghép.

## Ghi chú review

### Kiểm tra code và kết quả test

- [x] **Standalone / batch discovery:** `src/milestone1_crawler.py` dài 799 dòng; có `discover_many(..., batch_size=50)`, không khai báo `BatchedDiscovery` hay `LieuPipeline`. Đã sửa mô tả ở [README.md](../../README.md:68) và [ADR 0001](../adr/0001-src-crawl-la-khung-duy-nhat.md:7). Bằng chứng: `src/milestone1_crawler.py:548`, `src/milestone1_crawler.py:726`.
- [x] **Cache / schema:** nhận định hai triển khai có cùng layout và cùng luồng Parquet là sai. Standalone dùng `data/<safe-id>/v<n>/`; khung dùng `data/raw/<publication-key>/v<n>/` và xuất `papers`/`references` Parquet. Đã sửa README/ADR và ghi rõ migration chưa được kiểm chứng. Bằng chứng: `src/milestone1_crawler.py:47`, `src/milestone1_crawler.py:557`, `src/crawl/source.py:138-146`, `src/crawl/pipeline.py:178-184`, `src/common/schema.py:107-127`.
- [x] **Test Lieu:** `tests/test_lieu_crawler.py` tồn tại và import hai tên dự kiến ở dòng 15, nhưng các tên đó không được khai báo trong `src/milestone1_crawler.py`. Test collection hiện dừng sớm hơn vì thiếu dependency `arxiv`; lỗi thực tế ở mục bên dưới. Đã sửa trạng thái trong [README.md](../../README.md:86). Bằng chứng: `tests/test_lieu_crawler.py:15`, `src/milestone1_crawler.py:31`, `src/milestone1_crawler.py:548` (không có class `BatchedDiscovery`/`LieuPipeline`).
- [x] **Benchmark:** xác nhận sampler duyệt process con đệ quy; mặc định RSS 1 giây, disk 5 giây; xuất `peak_rss_mb`, `avg_rss_mb`, `peak_disk_mb`. Đã sửa `measured_by` trong mẫu vì harness đếm disk bằng `os.walk`, không gọi `du -sb`. Bằng chứng: `src/benchmark.py:46-55`, `src/benchmark.py:67-70`, `src/benchmark.py:129-132`, `docs/benchmark/benchmark.template.json:14`.
- [x] **make_stats:** đọc log gốc `logs/run_log.jsonl`, chưa đọc `crawl.jsonl`; khớp với tài liệu tích hợp. Bằng chứng: `src/make_stats.py:44-51`, `docs/lieu-integration.md:59-61`.
- [x] **Nhánh khác trong ADR 0002:** xác nhận SQLite ở `origin/Hai:src/crawl/store.py:1-14`; xác nhận `authors TEXT` và một cột `revised_date DATE` ở `origin/feat/Minh-crawler:src/Database/script.sql:1-8`.
- [x] **JSON mẫu:** `python3 -m json.tool docs/benchmark/benchmark.template.json` thành công.

**Test theo README:** đã cài `requirements.txt` vào virtualenv tạm `/private/tmp/arxiv-reference-venv`, sau đó chạy `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 /private/tmp/arxiv-reference-venv/bin/python -m pytest -q`. Collection thất bại (exit code 2); nguyên văn:

```text
==================================== ERRORS ====================================
_________________ ERROR collecting tests/test_lieu_crawler.py __________________
ImportError while importing test module '/private/tmp/arxiv-architecture-grilling/tests/test_lieu_crawler.py'.
Traceback (most recent call last):
/opt/homebrew/Cellar/python@3.14/3.14.7/Frameworks/Python.framework/Versions/3.14/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_lieu_crawler.py:15: in <module>
    from src.milestone1_crawler import BatchedDiscovery, LieuPipeline
src/milestone1_crawler.py:31: in <module>
    import arxiv
E   ModuleNotFoundError: No module named 'arxiv'
=========================== short test summary info ============================
ERROR tests/test_lieu_crawler.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 5.00s
```

`arxiv` được import bởi script standalone nhưng không được khai báo trong `requirements.txt`; theo phạm vi bước 3, không sửa code/dependencies ở lượt review tài liệu này.
