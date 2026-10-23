# Kế hoạch nhóm trưởng — Milestone 2

**Dự án:** arXiv Reference Matching — nhóm 3 KHDL24, 5 thành viên.

**Nhóm trưởng, phụ trách Parser:** Nguyễn Thành Bảo.

**Ngày soạn:** 23/10/2026.

**Trạng thái:** kế hoạch đề xuất để nhóm chốt; chưa phải báo cáo kết quả hoặc quyết định đóng băng schema.

## 1. Mục tiêu và điểm xuất phát

Milestone 2 biến source LaTeX của Milestone 1 thành cấu trúc có thể kiểm tra, chuẩn hóa và tái sử dụng cho Matching. Nhóm cần có một pipeline chung, chạy được trên dữ liệu của từng thành viên, cùng báo cáo giải thích kết quả và giới hạn.

Tại thời điểm lập kế hoạch:

- Repo đã có `src/common`, crawler, checkpoint, kiểm tra checksum và tiện ích Hugging Face.
- Range của Bảo là `2508.02872`–`2508.07871`, gồm 5.000 ID được giao; lượt crawl toàn Range vẫn chưa hoàn tất. Số liệu mới nhất nằm trong `data/crawl-smoke/manifests/range-run.json`.
- Chưa có `src/parse/`, `src/bibtex/`, `scripts/run_parse.py` hoặc `scripts/validate_tables.py` trên local `main`.
- Schema ngoài Crawling còn là dự thảo. Test hạ tầng/crawler đạt không chứng minh Parser đã đúng.
- Phân công đủ năm người và deadline chính thức chưa được xác nhận trong repo. Không suy ra người phụ trách Milestone 2 từ tên nhánh crawler.

**Thứ tự ưu tiên:** tiếp tục crawl local theo yêu cầu hiện tại; chuẩn bị hợp đồng và kế hoạch bàn giao; chỉ triển khai các bước tiếp theo khi điều kiện bắt đầu tương ứng đã đạt. Việc soạn tài liệu này không dừng crawler hoặc thay đổi schema.

## 2. Sản phẩm phải bàn giao

### 2.1. Code và dữ liệu làm việc

1. Parser tìm file gốc, gom file trên đường biên dịch, tạo cây theo Version, chuẩn hóa và khử trùng lặp Element.
2. Bộ xử lý BibTeX entry, thống nhất citation key và bàn giao nội dung trích dẫn cho Parser.
3. Ba bảng làm việc `elements`, `hierarchy`, `bibtex` theo hợp đồng được duyệt; giữ liên kết với `papers` và `references` của Milestone 1.
4. Manifest Parser, log lỗi/ngoại lệ, số liệu chất lượng và benchmark đủ để tái lập báo cáo.
5. CLI chạy mẫu và chạy toàn Range, có checkpoint/resume; README có lệnh thật sau khi triển khai.

Toàn dự án có sáu bảng: `papers`, `references`, `elements`, `hierarchy`, `bibtex`, `predictions`. Milestone 2 chưa huấn luyện Matching hoặc sinh `predictions`. Danh sách bảy bảng cũ trong README không dùng để triển khai. [Nguồn: đề Matching](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/matching/).

### 2.2. Báo cáo và nộp bài

Bổ sung chương Milestone 2 vào Jupyter Book của nhóm, xuất bản GitHub Pages; nộp link code và báo cáo theo hướng dẫn lớp. M2 chưa yêu cầu nộp dataset trung gian. Benchmark cuối chạy trên Colab CPU: đo thời gian toàn pipeline, trung bình/Publication, RAM tối đa và dung lượng đầu ra. [Nguồn: phần Submission Format của đề Parsing](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/parsing/).

Hugging Face private hiện có là nơi làm việc nội bộ. Không tự đổi quyền hoặc coi upload private là hoàn tất yêu cầu xuất bản dataset cuối Milestone 3.

## 3. Phân công đề xuất cho năm người

Chốt tên thật cho bốn vai trò còn trống trong buổi họp đầu. Một vai trò có một người chịu trách nhiệm chính và một người review; mỗi thành viên vẫn chịu trách nhiệm kiểm tra đầu ra của Range mình.

| Vai trò | Người phụ trách | Công việc chính | Bàn giao cho |
| --- | --- | --- | --- |
| Nhóm trưởng / Parser | **Nguyễn Thành Bảo — đã xác nhận** | Hợp đồng dữ liệu, gom file, dựng cây, tích hợp, review và nghiệm thu | Cả nhóm |
| Chuẩn hóa LaTeX | Chưa chốt | Quy tắc cleanup, chuẩn hóa toán, fixture biên, phối hợp dedup Element | Bảo và QA |
| BibTeX | Chưa chốt | Trích entry, khử trùng lặp, hợp nhất trường, ánh xạ citation key | Parser và người phụ trách Matching |
| QA / vận hành | Chưa chốt | Kiểm tra đầu vào, runner/resume, validator liên bảng, kiểm tra các Range | Nhóm trưởng |
| Báo cáo / benchmark | Chưa chốt | Notebook thống kê, Colab CPU, Jupyter Book và tái lập môi trường | Nhóm trưởng |

Người sở hữu Crawler/S2 hiện tại tiếp tục giải quyết lỗi đầu vào thuộc phần mình. Khi QA phát hiện dữ liệu của thành viên khác sai, báo đúng Publication/Version và chủ sở hữu; không tự sửa dữ liệu của họ.

## 4. Các quyết định phải chốt trước khi code Parser

**Cổng G0 — hợp đồng dữ liệu:** nhóm trưởng duyệt bằng văn bản, lưu phiên bản hợp đồng và ví dụ nhỏ. Tài liệu này chỉ nêu vấn đề và phương án; không tự thay `src/common/schema.py`.

### 4.1. Đối chiếu schema hiện tại

| Nội dung | Code hiện có | Việc phải chốt |
| --- | --- | --- |
| `bibtex.authors` | `string` | Đề ghi `list of strings`; duyệt thay kiểu và test round-trip |
| `bibtex.year` | `string` | Đề ghi `int`, nullable; chốt xử lý năm không đọc được, giữ giá trị thô trong log |
| `hierarchy.parent_id` | Cho phép null để ghi root | Đề ghi non-null; duyệt cách biểu diễn root, ví dụ root chỉ ở `elements`, không có cạnh lên cha |
| `elements.kind`, `bibtex.entry_type` | String và quy tắc kiểm tra hiện có | Đối chiếu yêu cầu dictionary/categorical, thống nhất biểu diễn Arrow/Parquet và tập giá trị |
| Các trường chưa ghi rõ non-null | Một số trường đang bắt buộc trong code | Ghi rõ nullability đã duyệt; không tự siết thêm chỉ để validator dễ viết |
| Khóa `hierarchy` | `(arxiv_id, version, element_id)` | Chưa biểu diễn được mọi trường hợp một Element xuất hiện nhiều chỗ trong một Version |

Nguồn đối chiếu kiểu: [bảng dữ liệu của đề Parsing](https://hcmus-cs-ta.github.io/lab-book/intro-ds/statement/parsing/). Rủi ro khóa đã được ghi tại [review schema](docs/schema-review.md).

### 4.2. Quyết định về định danh và lần xuất hiện

- Chốt `arxiv_id` gốc, khóa Publication an toàn cho đường dẫn, dạng `element_id` và cách cấp ID ổn định giữa các lần chạy.
- Phân biệt **Element có nội dung dùng chung** với **một lần xuất hiện trong cây của Version**. Cần giữ thứ tự và vị trí khi cùng câu lặp lại; không xóa nút chỉ vì văn bản giống nhau.
- Thống nhất root, heading giống chữ nhưng khác vị trí, cùng nội dung nhưng khác `kind`, và cùng câu dưới cùng cha hoặc khác cha. Chốt bằng fixture có đầu ra mong đợi.
- Cấu trúc cây nội bộ có thể lưu vị trí/thứ tự để Parser làm việc; cách ánh xạ ra các cột chính thức phải được duyệt riêng. Không tự thêm cột hoặc bảng xuất cuối để giải quyết khó khăn.
- Nếu hợp đồng trong đề chưa giải quyết được trường hợp lặp, ghi câu hỏi cụ thể để nhóm trưởng hỏi giảng viên trước khi đóng băng cách xuất dữ liệu.

### 4.3. Quyết định về BibTeX và chuẩn hóa

- Chọn citation key chuẩn một cách xác định; thống nhất cách xử lý hai entry khác nội dung nhưng trùng key.
- Khi gộp entry trùng, giữ hợp nhất các trường; khi hai giá trị mâu thuẫn, áp dụng quy tắc đã duyệt và ghi dấu vết. Không lấy ngẫu nhiên theo thứ tự đọc file.
- Ánh xạ key phải áp dụng vào các lệnh trích dẫn của bản nội dung đã xử lý trước khi tính định danh/dedup Element. Không sửa file raw.
- Chốt quy tắc escape, khoảng trắng, Unicode, comment và toán; cùng input/cấu hình phải cho cùng kết quả.

**Bằng chứng đóng G0:** schema đã duyệt, mẫu ba bảng, fixture về root/lặp/citation key, phiên bản normalization và người xác nhận. Chỉ sau đó mới cập nhật schema/test dùng chung.

## 5. Bàn giao Milestone 1 sang Milestone 2

**Cổng G1 — đầu vào được xác minh:** mỗi thành viên bàn giao snapshot, không chỉ một thư mục có tên giống arXiv ID.

Checklist bàn giao:

- [ ] Danh sách ID được giao, Publication có metadata, danh sách Version dự kiến và trạng thái từng Version.
- [ ] Source giữ đúng đường dẫn tương đối `.tex`/`.bib`; receipt/checksum khớp file.
- [ ] Tách rõ `success`, `non_tex`, `unavailable`, lỗi tải và chưa thử; không biến HTTP lỗi thành Version rỗng hợp lệ.
- [ ] Ghi commit crawler, thời điểm snapshot, người sở hữu, cấu hình không chứa bí mật.
- [ ] Chọn 3–5 Publication để nghiệm thu đầu vào, có nhiều Version, nhiều file và trường hợp không TeX; xác minh resume.
- [ ] Khi bàn giao corpus cuối, đối soát toàn Range và công bố danh sách thiếu/lỗi. Không dùng số ID được giao làm số Publication đã tải thành công.

Với Bảo, dùng cache `data/crawl-smoke/` theo [hướng dẫn crawl toàn Range](docs/full-range-crawl.md). Hai bảng Parquet có thể chưa phản ánh toàn bộ cache khi lượt crawl chưa kết thúc; kiểm tra manifest/receipt để lập inventory. Không đọc archive hoặc file đang ghi dở làm mẫu chính thức.

Chọn bộ phát triển 10–20 Publication sau khi G0 và G1 đạt, bao phủ nhiều kiểu tài liệu; đây là mục tiêu nội bộ, không phải số lượng bắt buộc của đề. Chốt snapshot mẫu để các thành viên chạy cùng đầu vào. Dữ liệu tải về tiếp tục nằm ngoài Git.

## 6. Thứ tự triển khai và nghiệm thu

Các quy tắc Parser bên dưới kế thừa [AGENTS.md](AGENTS.md), mục 4–6. Mỗi bước có test với fixture tự viết và chạy trên bộ mẫu; bước trước chưa đạt thì chưa nghiệm thu bước phụ thuộc.

### Bước 1 — Tìm root và gom source

**Chủ trì:** Bảo.

- Tìm file chứa `\documentclass`; theo `\input`/`\include` đệ quy và đúng đường dẫn tương đối.
- Bỏ qua include trong comment; phát hiện vòng lặp, thiếu file, đường dẫn thoát thư mục và trường hợp nhiều root.
- Ghi danh sách file đã dùng và nguồn gốc đoạn nội dung để truy lỗi. File ngoài đường biên dịch không đi vào cây.
- Các cấu trúc điều kiện/macro chưa hỗ trợ phải có trạng thái hoặc cảnh báo cụ thể; không đánh dấu thành công bằng cách âm thầm bỏ nội dung.

**Nghiệm thu:** fixture một file, nhiều file, include lồng, comment, vòng lặp và nhiều root cho kết quả mong đợi; trên mẫu thật có thể giải thích vì sao từng file được giữ/bỏ.

### Bước 2 — Cây phân cấp và các loại nút

**Chủ trì:** Bảo; QA review.

- Dựng root Document, các cấp heading và phiên bản có `*`; giữ Acknowledgements và Appendices, loại phần References khỏi hierarchy.
- Phân biệt Sentence, Block formula, Figure; Table được xử lý như Figure. `itemize` có các `item` con.
- Tách câu có nhận biết ngữ cảnh để không cắt trong toán, lệnh, viết tắt, URL, số thập phân hoặc `Fig. 1`.
- Giữ thứ tự đọc và quan hệ cha của các lần xuất hiện trong cấu trúc nội bộ đã chốt ở G0.

**Nghiệm thu:** cây mẫu đúng loại nút/cha/thứ tự, không chu trình; không mất phần cuối tài liệu khi References nằm trước phụ lục.

### Bước 3 — Chuẩn hóa LaTeX

**Chủ trì:** vai trò Chuẩn hóa; Bảo review giao diện.

- Tách quy tắc bỏ định dạng không mang nghĩa khỏi quy tắc biến đổi nội dung.
- Thống nhất toán inline về `$...$`, toán khối về `\begin{equation}...\end{equation}`; không làm mất nội dung công thức.
- Kiểm thử tính lặp ổn định: chuẩn hóa đầu ra thêm một lần không thay đổi kết quả.
- Mỗi quy tắc có ví dụ trước/sau và ca không được thay đổi; tránh regex thay toàn văn bản mà không biết ngữ cảnh.

**Nghiệm thu:** khác biệt thuần định dạng cho cùng kết quả; khác biệt nội dung thực vẫn được giữ. Chốt phiên bản quy tắc trước khi tạo corpus chính thức.

### Bước 4 — BibTeX và citation key

**Chủ trì:** vai trò BibTeX; phối hợp người phụ trách Matching về hợp đồng đầu ra.

- Đọc `.bib` và trích `\bibitem` trên nội dung liên quan; giữ dấu vết trường chưa đọc được.
- Tạo entry chuẩn, hợp nhất entry trùng trong/giữa các Version và ánh xạ key về key chuẩn.
- Kiểm tra hợp nhất trường bằng fixture: một Version có `year`, Version khác bổ sung `doi`; không làm mất thông tin đã có.
- Sửa các lệnh trích dẫn trong bản nội dung xử lý theo ánh xạ; bibliography không trở lại hierarchy chỉ để giữ key.
- Source chỉ còn lời gọi bibliography nhưng thiếu dữ liệu entry cần được ghi thiếu đầu vào. Không bịa title/authors hoặc tự bổ sung từ S2 để che lỗi Parser.

**Nghiệm thu:** key ổn định, không có key mơ hồ chưa được xử lý, các citation trong phạm vi hỗ trợ được đối soát; entry thiếu tiêu đề được liệt kê cho QA, không xóa âm thầm.

### Bước 5 — Khử trùng lặp Element và xuất ba bảng

**Chủ trì:** Bảo; QA kiểm tra liên bảng.

- Dùng nội dung sau chuẩn hóa và sau thống nhất citation key để so khớp.
- Khử trùng lặp trong phạm vi Publication theo hợp đồng G0; không gộp ID giữa hai Publication.
- Bảo toàn các cạnh/lần xuất hiện theo Version; hai Version chia sẻ Element không có nghĩa chia sẻ toàn bộ cây.
- Version `non_tex` có kết quả rỗng và trạng thái rõ ràng; lỗi parse không được biến thành `non_tex`.
- Xuất `elements`, `hierarchy`, `bibtex`; chạy validator kiểu/cột và QA khóa ngoại, root, chu trình, citation key.

**Cổng G2 — pipeline mẫu:** 3–5 Publication nghiệm thu đầu-cuối; mọi lỗi đã biết có fixture, ba bảng qua hợp đồng đã duyệt, lần chạy lại cho cùng nội dung logic. Không yêu cầu byte Parquet giống nhau nếu metadata file khác.

### Bước 6 — Chạy các Range và xử lý lỗi

**Chủ trì:** QA/vận hành; mỗi thành viên chạy và chịu trách nhiệm Range của mình.

- Runner xử lý theo Publication để thống nhất các Version, có checkpoint theo Version và mốc tổng hợp Publication.
- Cache phụ thuộc checksum nguồn, phiên bản Parser/normalization và schema; đổi một thành phần thì tính lại phạm vi bị ảnh hưởng.
- Lỗi một Version không dừng cả lượt. Tách `parsed`, `empty_non_tex`, `parse_error`, `source_missing` trong manifest nội bộ sau khi duyệt tên trạng thái.
- Ghi file tạm rồi thay thế atomically; checkpoint chỉ được đánh dấu xong sau khi đầu ra hợp lệ.
- Chạy lô nhỏ, kiểm tra output và khả năng resume trước khi mở toàn Range. Dữ liệu nhiều thành viên phải theo cùng một hợp đồng.
- Gom lỗi theo loại, sửa bằng code, thêm fixture rồi chạy lại phần ảnh hưởng. Mọi chỉnh sửa tay được cho phép đều có log, không thay cho sửa pipeline.

**Cổng G3 — corpus:** tất cả Publication/Version trong snapshot bàn giao đều được đối soát, có đầu ra hoặc trạng thái thiếu/lỗi rõ ràng; QA báo đầy đủ, không gắn nhãn hoàn thành khi lỗi bắt buộc còn mở.

### Bước 7 — Benchmark, báo cáo và đóng gói

**Chủ trì:** vai trò Báo cáo; Bảo nghiệm thu.

- Chốt commit, dependency, cấu hình, snapshot và môi trường Colab CPU dùng đo.
- Đo một lần chạy mới, tách riêng lần resume; không gộp thời gian crawl vào benchmark Parser.
- Notebook đọc đầu ra có phiên bản xác định, sinh bảng/hình khi build; không crawl Internet lại trong mỗi lần build báo cáo.
- Giải thích thuật toán, lỗi phổ biến, mức độ bao phủ và giới hạn đo; đưa ví dụ trước/sau từ kết quả tái lập được.
- Người không viết module thử clone sạch, cài đặt và chạy bộ mẫu theo README.

**Cổng G4 — sẵn sàng nộp:** báo cáo build thành công, link công khai xem được theo yêu cầu môn, code và dữ liệu báo cáo cùng phiên bản, nhóm trưởng kiểm tra checklist cuối.

## 7. QA và số liệu phải thu ngay từ đầu

### 7.1. Kiểm tra tự động

- Cột, kiểu, nullability và khóa theo schema đã duyệt; kiểm tra trùng giữa các shard/Range.
- Mọi `element_id`/`parent_id` của cạnh tồn tại và thuộc đúng Publication. Node cha phải thuộc cấu trúc Version đang xét, dù nội dung Element được dùng chung giữa Version.
- Kiểm tra cấu trúc cây trên các lần xuất hiện, sau đó kiểm tra ánh xạ sang bảng xuất; không ép bảng dedup phải là cây nếu hợp đồng biểu diễn chưa cho phép điều đó.
- Không có chu trình, self-edge hoặc root không xác định; xử lý thứ tự/lặp theo G0.
- Đối soát citation key, entry trùng, entry thiếu trường; ghi rõ trường hợp không thể suy ra từ source.
- Chạy hai lần, kiểm thử source thay đổi, output thiếu/hỏng và tiến trình bị ngắt.

### 7.2. Kiểm tra bằng mắt

QA chọn mẫu có seed từ từng thành viên, cộng thêm tất cả nhóm lỗi mới. Với mỗi mẫu, đối chiếu source → cây → nội dung chuẩn hóa → entry/citation. Ghi Publication, Version, vị trí, loại lỗi, người sửa và bằng chứng kiểm tra lại.

Fixture Git phải do nhóm tự viết. `.gitignore` hiện chặn `*.tex`/`*.bib`; trước khi thêm fixture, duyệt ngoại lệ giới hạn đúng `tests/fixtures/`, không mở bỏ qua cho toàn bộ dữ liệu thô.

### 7.3. Định nghĩa số liệu nội bộ

Ghi cả tử số và mẫu số, kèm danh sách ID/Version nền tảng:

- **Tỷ lệ parse thành công:** Version có TeX parse thành công / Version có TeX hợp lệ được đưa vào lượt chạy.
- **Độ phủ Version:** (Version parse thành công + Version `non_tex` đã xác minh) / tổng Version dự kiến theo discovery của snapshot. Báo riêng lỗi/thiếu; Publication chưa discovery được phải có chỉ tiêu riêng vì chưa biết số Version.
- **Publication hoàn chỉnh:** mọi Version dự kiến được xử lý hợp lệ và đầu ra tích hợp qua QA. Không chỉ đếm Publication có ít nhất một Version tốt.
- **Dedup Element:** số lần xuất hiện trước dedup và số Element riêng biệt sau dedup; báo theo loại và toàn corpus, không nhầm số cạnh với số Element.
- **Dedup BibTeX:** số entry đầu vào, số entry chuẩn sau gộp, số key đổi và số xung đột trường.
- **Hiệu năng:** wall time đầu-cuối, số Publication thực xử lý, trung bình/Publication, RAM đỉnh và dung lượng đầu ra; ghi rõ phạm vi tiến trình và đơn vị.

`src/common/metrics.py` hiện không đo RAM trung bình hoặc RAM tiến trình con; đỉnh RAM tính từ lúc tiến trình khởi động. Nếu chạy đa tiến trình phải bổ sung phép đo phù hợp trước khi công bố tổng RAM. Đây là giới hạn công cụ hiện tại, không được diễn giải thành kết quả benchmark.

## 8. Lịch thực hiện đề xuất

**D0** là ngày G0 và G1 được nghiệm thu. Lịch dưới đây là khung nội bộ, chưa phải deadline môn; cần đối chiếu Moodle và thời gian của năm thành viên trước khi chốt. Nếu một cổng chưa đạt, điều chỉnh lịch các bước phụ thuộc thay vì tự bỏ tiêu chí.

| Mốc | Kết quả cần có | Điều kiện chuyển tiếp |
| --- | --- | --- |
| Trước D0 | Hoàn tất đối soát crawl, chọn mẫu, chốt vai trò và các quyết định schema | G0 + G1 được duyệt |
| D1–D2 | Root/gom file và bộ fixture; thiết kế giao diện normalization/BibTeX | Nghiệm thu bước 1 |
| D3–D4 | Cây/loại nút; normalization và BibTeX phát triển theo giao diện đã chốt | Test từng module và review mẫu |
| D5–D6 | Tích hợp citation key, dedup, xuất ba bảng và QA | G2 đạt |
| D7–D9 | Chạy lô nhỏ rồi các Range; sửa lỗi có fixture, thu thống kê | G3 đạt |
| D10–D11 | Benchmark Colab CPU, hoàn thiện Jupyter Book và README | Build báo cáo và clone sạch đạt |
| D12 | Review chéo, dự phòng lỗi, kiểm tra link nộp | G4 đạt |

Các vai trò có thể làm song song ở phần không phụ thuộc nhau sau khi hợp đồng được chốt. Thời gian chạy corpus chưa được benchmark nên không cam kết hoàn tất trong khung trên.

## 9. Cách nhóm trưởng điều phối và review

Mỗi buổi làm việc, từng người cập nhật ngắn: việc đã chạy được và bằng chứng; việc tiếp theo; điểm đang chặn; ID/Version liên quan. Bảo tổng hợp theo cổng G0–G4, không dùng số dòng code hoặc số commit làm tỷ lệ hoàn thành.

PR nên đi theo phần nghiệm thu: gom file → cấu trúc cây → normalization → BibTeX → dedup/xuất bảng → runner/QA → báo cáo. Mỗi PR ghi input/output, test đã chạy, mẫu thật đã kiểm tra và giới hạn còn lại. Commit nhỏ, có tác giả rõ ràng; không trộn dữ liệu, bí mật hoặc chỉnh schema chưa duyệt.

Một thay đổi schema hoặc quy tắc chuẩn hóa cần ghi: lý do, phần bị ảnh hưởng, phiên bản mới, người duyệt và phạm vi cần chạy lại. Không âm thầm trộn output sinh bởi các phiên bản Parser khác nhau.

## 10. Checklist nhóm trưởng trước khi nghiệm thu M2

- [ ] Đủ năm người, chủ sở hữu từng phần, Range và deadline đã xác nhận.
- [ ] G0: schema/ID/root/lần xuất hiện/citation key đã chốt; code và validator thống nhất.
- [ ] G1: đầu vào được đối soát theo Version, snapshot và bộ mẫu tái lập được.
- [ ] G2: pipeline mẫu chạy thật, test từng lớp đạt, QA ba bảng qua.
- [ ] G3: đối soát mọi Range; không bỏ qua Version rỗng, Version lỗi hoặc Publication thiếu.
- [ ] Không có lỗi cấu trúc/citation bắt buộc còn mở; mọi ngoại lệ có log và chủ sở hữu.
- [ ] Số liệu coverage/dedup và benchmark có dữ liệu gốc, cách tính và phạm vi đo rõ ràng.
- [ ] Jupyter Book sinh hình/bảng bằng code, giải thích kết quả thực tế, build và mở link được.
- [ ] README đủ để người khác clone/cài/chạy mẫu; dependency tái lập được.
- [ ] Không dùng LLM hoặc mô hình pretrained trong pipeline Parser theo quy tắc repo.
- [ ] Không commit raw corpus, Parquet hoặc bí mật; chỉ fixture tự viết đã được duyệt.
- [ ] G4: nhóm trưởng kiểm tra link code/báo cáo và yêu cầu nộp chính thức.

## 11. Việc cần chốt trong buổi họp đầu

1. Gán bốn vai trò còn trống và một người review cho mỗi phần.
2. Chốt deadline chính thức; quy đổi D0–D12 thành ngày cụ thể.
3. Duyệt từng quyết định ở mục 4, đặc biệt root và lần xuất hiện trong hierarchy.
4. Xác nhận bộ mẫu/snapshot và danh sách lỗi Crawling cần chủ sở hữu xử lý.
5. Chốt repo Jupyter Book dùng chung và người chịu trách nhiệm build/xuất bản.

Nguồn nội bộ để theo dõi tiếp: [AGENTS.md](AGENTS.md), [checklist nhóm trưởng](docs/team-lead-checklist.md), [review schema](docs/schema-review.md), [pipeline Crawling](docs/crawl-pipeline.md), [vận hành toàn Range](docs/full-range-crawl.md). Các đoạn trạng thái cũ trong tài liệu lịch sử cần đối chiếu với code và manifest hiện tại.
