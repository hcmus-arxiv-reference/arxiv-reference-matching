---
status: proposed
---

# Parser chạy song song với crawl, đọc corpus từ file

Đề xuất ngày 19/11/2026, chờ nhóm trưởng duyệt. Giữ nguyên ADR 0001 (một Engine `src/crawl/`),
ADR 0002 (file là nguồn gốc) và ADR 0003 (ranh giới Runner, CorpusReader, Export).

## Bối cảnh

Thầy trả lời câu 17 trong bảng hỏi đáp: không có cách chính thức nào để crawl nhanh hơn. Muốn
luồng chạy nhanh hơn thì nên "xử lý những dữ liệu đã lấy được trong khi chờ dữ liệu mới lấy về".

Số đo hiện có:

- Lượt thử Colab 15/11 (`m1-bench-v4`): 643,9 Publication mỗi giờ, khoảng 7,8 giờ cho một Range.
  Thời gian arXiv bận (mỗi request chiếm `max(3,1 s, độ trễ + byte / băng thông)`) cộng thời gian
  chờ S2 giải thích được **97% wall time** (`src/crawl/runtime_model.py`). 3% còn lại là giải
  nén và ghi đĩa.
- S2 đã chạy ở luồng riêng, chồng lên lượt tải arXiv (References theo lô, PR #49 và #50).
- Lượt chạy bù 59 Publication ngày 19/11 chỉ dùng 5% một CPU. Colab cho 2 CPU.
- Parser M2 xử lý theo Publication: khử trùng lặp Element và gộp BibTeX trên mọi Version của một
  bài (`docs/m2-interfaces.md` mục 3), và có checkpoint `data/parse/<key>/done.json` theo sha256
  của các receipt.

Tối ưu thêm bên trong crawl vì vậy lợi được không quá 3%. Phần còn lãng phí là CPU gần như rảnh
suốt 7–8 giờ chờ arXiv, trong khi M2 phải đợi crawl xong cả Range mới bắt đầu.

## Quyết định

Thêm một **tiến trình theo sau** (follower) cho Parser: `scripts/parse_range.py --follow`. Tiến
trình này chạy song song với Runner trên cùng thư mục dữ liệu và không import gì từ `src/crawl/`.

1. **Tín hiệu sẵn sàng là file, không phải Manifest.** Một Publication sẵn sàng cho M2 khi
   `FileCorpus.publication(id).sources_complete` đúng: metadata hợp lệ và mọi Version
   `v1..vN` có receipt `source.json` qua `verified_source` (`success`, `non_tex`, hoặc
   `unavailable` theo C11). Không cần references, vì M2 không đọc S2. Mọi file này đều được ghi
   nguyên tử (thư mục tạm rồi đổi tên), nên follower không bao giờ đọc phải bản ghi dở.
2. **Vòng lặp:** quét các ID của Range theo thứ tự; Publication nào đã sẵn sàng mà chưa có
   `done.json` khớp thì gọi `parse_publication`, ghi kết quả trung gian và `done.json`. Hết việc
   thì ngủ `--poll` giây (mặc định 30) rồi quét lại.
3. **Dừng:** khi `manifests/range-run.json` báo Runner đã dừng (`complete`, `incomplete`,
   `stopped` hoặc `failed`; không phải `running`, `retry_wait`, `settling_references`) và một lượt quét không còn Publication sẵn sàng nào chưa xử lý; hoặc khi có file
   `STOP_PARSE`. Sau đó follower gộp kết quả từng Publication thành ba bảng `elements`,
   `hierarchy`, `bibtex` (bước gộp của `run_batch`).
4. **Ưu tiên CPU cho crawl:** follower chạy với `os.nice(10)` và một tiến trình duy nhất, để
   luồng arXiv không bị chậm.
5. **Đo riêng hai milestone:** M2 vẫn ghi `seconds` theo từng Version trong
   `data/parse/log/versions.jsonl` và tổng thời gian CPU của follower. Báo cáo ghi cả thời gian
   M2 khi chạy riêng (batch) lẫn wall time chung của M1 + M2.
6. **Colab:** notebook benchmark khởi động follower bằng `subprocess.Popen` trước vòng crawl, ghi
   log ra file và dừng nó sau đoạn cuối. Checkpoint `.tar.gz` giữa hai đoạn có thể bắt được một
   Publication đang parse dở. Bản đó chưa có `done.json` nên sẽ được parse lại sau khi khôi phục.

Chạy batch như hiện nay (không `--follow`) vẫn giữ nguyên, dùng khi corpus đã có sẵn, ví dụ
dữ liệu tải từ Hugging Face.

## Considered Options

- **Gọi Parser ngay trong Runner** sau mỗi Publication hoàn chỉnh, qua một
  `ProcessPoolExecutor(1)`. Không cần quét file, nhưng M1 Engine phải phụ thuộc vào code M2.
  Khi đó một lỗi hoặc treo của Parser có thể làm dừng crawl, và tag benchmark M1 phải chứa code
  M2. Trái với ranh giới của ADR 0003.
- **Tách giải nén khỏi luồng tải** (luồng arXiv chỉ nhận byte, một worker giải nén và ghi
  receipt). Lợi tối đa khoảng 3% wall time theo số đo trên, trong khi phải đổi
  `ArxivSourceDownloader`, thứ tự ghi receipt và Manifest của Engine đã chạy ổn.
- **Hàng đợi tin nhắn hoặc cơ sở dữ liệu trạng thái chung** giữa crawl và parse. Thêm một nguồn
  sự thật thứ hai, trái ADR 0002, trong khi receipt nguyên tử đã đủ làm tín hiệu.
- **Giữ nguyên tuần tự** (crawl xong cả Range rồi mới parse). Đơn giản nhất, nhưng bỏ qua đúng
  hướng thầy gợi ý, và M2 không có kết quả nào trong suốt 7–8 giờ crawl.

## Consequences

- Wall time M1 + M2 trên một Range xấp xỉ wall time crawl cộng thời gian parse Publication cuối
  cùng và bước gộp bảng, thay vì cộng toàn bộ thời gian parse. Mức lợi thực tế phụ thuộc tốc độ
  của Parser thật. Số 0,06 giây mỗi Publication của Minh đo trên bản `fallback-*`, chưa phải
  Parser thật; cần đo lại khi đủ bốn gói.
- Lỗi M2 không làm dừng crawl, và ngược lại. Mỗi bên có log và checkpoint riêng.
- `parse_publication` phải tất định và chịu được chạy lại (I7). Đây vốn là yêu cầu của M2.
- Follower chỉ đọc `metadata/` và `raw/`, chỉ ghi dưới `data/parse/`. Runner không biết
  follower tồn tại.
- Việc cần làm (sau khi duyệt): thêm chế độ `--follow` vào `scripts/parse_range.py` (nhánh
  `feat/m2-types` của Minh, chưa có PR); kiểm thử bằng một Runner giả ghi receipt theo thời gian;
  thêm ô khởi động follower vào notebook Colab; mục "Tổ chức luồng chạy" trong báo cáo M2.
