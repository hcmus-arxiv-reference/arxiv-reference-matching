# Engine Python cho Hierarchy

Từ thư mục gốc repo, dùng môi trường Python hiện có của dự án:

```sh
python -m src.parse.Hierarchy.build
```

Build cần CMake >= 3.18, compiler C++17, header Python của interpreter đang chạy,
nlohmann_json >= 3.11, OpenSSL development files và pybind11 >= 3.0. Script
dùng `sys.executable` và ưu tiên OpenSSL trong `sys.prefix`; không cài thêm gói.
Extension và thư mục build được gitignore. Đổi phiên bản Python thì build lại
với interpreter đó, dùng `--build-dir` khác nếu CMake cache thuộc interpreter cũ.

Binding dùng pybind11 để gọi trực tiếp class C++ và chuyển các struct/STL container
sang Python; không serialize kết quả qua JSON trung gian.

```python
from src.parse.Hierarchy import HierarchyEngine
from src.parse.MultifileGathering.merge import merge_latex

latex = merge_latex("/path/to/version", main_file="main.tex")
engine = HierarchyEngine(arxiv_id="2508.02872", version=1)
result = engine.parse(latex)

elements = result.elements    # list[Element], dùng types.py hiện có
hierarchy = result.hierarchy  # list[Hierarchy], dùng types.py hiện có
if not result.complete:
    print(result.diagnostics)
```

Mỗi engine giữ một instance Parser C++ và nạp mapping một lần khi khởi tạo.
Có thể truyền `mapping_path=` để dùng cấu hình khác. Tạo engine mới khi thay
mapping hoặc metadata Publication/Version. `parse()` không ghi file và không tự
build extension. Khi thiếu extension, lỗi import có hướng dẫn build.

`diagnostics` giữ nguyên code, message, source và offset **theo byte UTF-8** từ
C++. `ordered_children` giữ thứ tự xuất hiện, kể cả phần tử lặp; đây là dữ liệu
trung gian, không phải bảng mới. C++ core thực hiện các bước chuẩn hóa đã khai
báo trong mapping trước khi băm ID; binding Python giữ nguyên diagnostic.
Khóa cite/ref được giữ nguyên, chưa thực hiện BibTeX key rewriting. Chỉ dùng
kết quả cho bước sau khi đã đánh giá `complete` và các giới hạn của Parser.

Mapping điều khiển các action của lệnh (`heading`, `item`, `unwrap`, `discard`,
`preserve`, `paragraph_break`, `replace`, `accent`, `inline_math`) và môi trường (`root`, `list`, `heading`,
`transparent`, `formula`, `figure`, `literal`, `inline_math`, `exclude`).
`arguments`/`optional_arguments` hoặc `argument_spec` xác định chính xác đối số
cần đọc. `optional_argument_indices` chọn phần pretext cần giữ trong wrapper;
`token_arguments: true` cho phép đối số là một token không có ngoặc, ví dụ
`\setlength\tabcolsep{3pt}` hoặc `\'e`. `content_arguments` và
`content_optional_arguments` chọn chỉ số đối số cần giữ khi unwrap, tính từ 0;
`content_prefix`/`content_suffix` thêm khoảng cách quanh chú thích. Vì vậy
`\textcolor{red}{Text}` chỉ giữ `Text`, `\texorpdfstring{TeX}{PDF}` giữ nhánh TeX,
còn `\footnote{Text}` giữ văn bản chú thích trong câu hiện tại.
`paragraph_boundary: false` cho phép wrapper bố cục giữ câu xuyên qua ranh giới.
`contexts` giới hạn cleanup ở prose/heading/figure/formula, nên lệnh
định dạng trong văn xuôi có thể được bỏ mà vẫn giữ lệnh có ý nghĩa trong toán.
Đối số được giữ của wrapper văn xuôi đi qua bộ dựng cây: công thức khối bên
trong vẫn tạo lá formula, heading/list vẫn tạo nút tương ứng. Nhóm và khai báo
cục bộ giữ scope; dấu chấm trong nội dung đối số được bảo vệ khi tách câu.
Ngoặc nhóm cú pháp không xuất hiện trong văn xuôi/heading đã chuẩn hóa;
ngoặc escape và ngoặc có nghĩa trong toán vẫn được giữ.

Abstract và Acknowledgements tạo section theo rule; enumerate/description tạo
itemize. Các môi trường proof/theorem/lemma đã khai báo được đọc tiếp phần thân.
Công thức nhiều dòng giữ nguyên hàng/cột trong aligned/gathered/alignedat/array,
rồi bọc equation. Hình/bảng giữ nội dung nguyên khối, bỏ placement ngoài và các
lệnh định dạng đã khai báo; đối số như width của includegraphics vẫn được giữ.
Literal environments giữ chính xác thân, kể cả whitespace, `%` và lệnh giả.
Đối số cấu hình của môi trường figure/table/tabular được giữ nguyên ngoài
comment; ví dụ `$` trong khai báo cột `>{$}l<{$}` không phải công thức độc lập.

Engine đọc `\newtheorem`/`\newtheorem*` trong source để nhận diện các tên như
`thm`, `prop`, `lem` theo khai báo của từng Version. Rule ở
`declarations.newtheorem` giữ thân và tên tùy chọn, không tạo số định lý tự sinh.
Macro `\newcommand`, `\renewcommand`, `\providecommand`, `\DeclareRobustCommand`
và `\def` với tham số liên tiếp `#1`…`#9` được thay thế theo thứ tự khai báo;
hỗ trợ optional default và scope nhóm/môi trường. Ví dụ alias `\be`/`\ee`
trỏ tới `\begin{equation}`/`\end{equation}` được nhận diện thành formula.
Giới hạn `declarations.macros` chặn đệ quy, quá nhiều lần mở rộng hoặc quá nhiều
byte. Diagnostic trong đoạn mở rộng trỏ về vị trí gọi macro ở source ban đầu.
`\newif` cùng công tắc true/false và `\iftrue`/`\iffalse` được xử lý trực tiếp;
không đoán giá trị của các điều kiện khác để chọn định nghĩa ở preamble.
Scanner toán theo dõi độ sâu ngoặc nhóm để delimiter trong đối số văn bản
không kết thúc sớm công thức ngoài. Nếu gặp lỗi cú pháp ở phần thân, engine
giữ phần văn xuôi hợp lệ đã đọc trước đó và trả diagnostic, `complete=false`.

Đây vẫn là parser cú pháp với thay thế macro giới hạn, không phải bộ thực thi
TeX. Chưa thực thi package, `\edef`/`\xdef`/`\gdef`, `\let`, tham số phân cách
tùy ý, hook hay `\newenvironment`.
Khai báo/điều kiện bên trong đối số heading vẫn thuộc đường chuẩn hóa riêng,
chưa hỗ trợ đầy đủ. `\xspace` chỉ dùng quy tắc nhìn ký tự kế tiếp, gồm tránh
chèn khoảng trắng trước dấu gạch nối và dấu `/`, chưa mô phỏng đầy đủ package.
Một heading token đứng riêng trong đối số wrapper (ví dụ `\keywords\section`)
được giữ kèm diagnostic, để không dừng parse và bỏ mất phần source phía sau.
Bên trong hình nguyên khối giữ macro; `normalize_body: false` của TikZ/picture
giữ cả mã vẽ để tránh nhầm biến vòng
lặp với lệnh cleanup. Callback toán như `\mathpalette` giữ nguyên đối số.
Chữ có dấu dùng bảng ký tự Unicode của từng rule; ngoài bảng giữ combining mark,
chưa có bước NFC tổng quát. Title/author/affiliation và lệnh sinh lại tiêu đề
được bỏ khỏi cây nội dung; keywords và nội dung footnote được giữ.
Tag ngoài mapping ở luồng văn bản được giữ kèm diagnostic; môi trường
chưa biết giữ toàn bộ source trong diagnostic. Bên trong lá toán/hình nguyên
khối, cú pháp chưa có rule cleanup được giữ lại. Các rule mới dùng action hiện
có có thể bổ sung trực tiếp vào JSON; action mới cần được hiện thực trong C++.
Chuẩn hóa thay đổi nội dung thì ID và ID của các cây cha liên quan cũng đổi;
định dạng hash và schema bảng vẫn giữ nguyên.

Chạy kiểm thử sau khi build:

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_hierarchy_engine.py
```

Test native được skip nếu chưa build extension. C++ core vẫn có CMake target và
test độc lập; mặc định `BUILD_PYTHON_BINDINGS=OFF` khi build trực tiếp bằng CMake.

## Benchmark trên source thật

```sh
python -m src.parse.Hierarchy.benchmark --limit 30
```

Cũng có thể chạy trực tiếp `python src/parse/Hierarchy/benchmark.py`.
Mặc định đọc `data/arxiv_crawl_20261024/raw`, ưu tiên folder nhiều `.tex`,
sau đó `.bib`; mỗi Publication lấy một Version có số file nhiều nhất, khi
bằng nhau lấy Version mới nhất. Sau khi chọn main, benchmark gọi `merge_latex`
rồi truyền chuỗi sang `HierarchyEngine` với đúng arxiv_id và Version.

`--limit` là số lần thực sự gọi `engine.parse`. Nếu merge bị từ chối, benchmark
ghi lỗi rồi chọn tiếp ứng viên; lỗi engine vẫn được tính là một lần gọi.
Nếu hết ứng viên, `target_reached=false`. Mọi ca đã thử, kể cả merge thất bại,
đều có trong báo cáo để tránh che khuất giới hạn của bước gom source.

Kết quả mặc định ở `src/parse/Hierarchy/output/benchmark/`:

- `report.md`: thống kê và liên kết đến các cây.
- `report.json`: kết quả từng ca, lỗi, thời gian, số lượng theo kind và diagnostic.
- `cases/<publication>_<version>/merged.tex`: chuỗi đưa vào engine.
- `cases/<publication>_<version>/tree.md`: cây đọc được, giữ thứ tự và nút lặp.
- `cases/<publication>_<version>/tree.json`: toàn bộ elements, hierarchy,
  ordered_children, roots và diagnostics; đây là artifact kiểm tra, không đổi schema bảng.
- `cases/<publication>_<version>/case.json`, `file_tree.json`: metadata và kết quả chọn file.

Tùy chọn `--raw-dir`, `--output-dir`, `--labels`, `--mapping`, `--preview-nodes`
cho phép đổi dữ liệu, nhãn chọn main, mapping và giới hạn preview Markdown
(mặc định 1.000 lần xuất hiện). JSON không bị cắt theo giới hạn preview.
`--exclude-report` bỏ toàn bộ Publication có trong một báo cáo cũ, kể cả khi
Version giàu source nhất đã đổi, để mở rộng mẫu mà không lấy lại bài cũ:

```sh
python -m src.parse.Hierarchy.benchmark --limit 60 \
  --exclude-report src/parse/Hierarchy/output/benchmark_astra_fixes/report.json \
  --output-dir src/parse/Hierarchy/output/benchmark_expansion_90/new60
```

Chạy lại ghi đè các artifact cùng tên; báo cáo chỉ liệt kê các ca thuộc lượt mới,
các file cũ khác vẫn được giữ. Source đầu vào không bị sửa.

Phân biệt các chỉ số:

- `main_accuracy`: so file main với nhãn review sẵn trong
  `MultifileGathering/benchmark_labels.json`; chỉ tính nhãn còn khớp checksum.
  Ca chọn main thất bại vẫn tính sai nếu có nhãn hợp lệ.
- `merge_success_rate`: số folder merge được / tất cả folder đã thử.
- `engine_return_rate`: số ca engine trả được kết quả / số ca merge được.
- `complete_rate`: số kết quả không diagnostic / số ca engine trả kết quả.
- `structure_valid_rate`: số kết quả đạt kiểm tra schema, metadata, khóa,
  foreign key, DAG, độ liên thông và ordered_children / số ca engine trả kết quả.
  Nút đã dedup có thể có nhiều cha; không ép mỗi ID chỉ có một cha.
- `semantic_tree_accuracy=null`: chưa có cây chuẩn được gán nhãn độc lập,
  nên chưa thể chấm độ đúng nội dung, tách câu và quan hệ phân cấp.

Các tỷ lệ trả `null` khi mẫu số bằng 0. Cây có diagnostic là kết quả chưa
hoàn tất, dù cấu trúc hợp lệ. RAM là đỉnh của cả tiến trình; dung lượng là
ảnh chụp file output, không phải disk đỉnh. Đây là mẫu ưu tiên nhiều TeX và
merge được, không phải mẫu ngẫu nhiên đại diện cho toàn bộ corpus.

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_hierarchy_benchmark.py
```

## Đối chiếu cây tham chiếu

`compare_reference.py` đọc các nhãn độc lập trong
`output/gold_reference/labels/<publication>_<version>.json`. Handoff và manifest
cho Agy nằm cạnh thư mục nhãn. Nhãn dùng ID riêng cho từng lần xuất hiện và
vị trí byte UTF-8 trong merged source; không lấy ID/cây dự đoán làm đáp án.
Đây là tác vụ gán nhãn đánh giá, không đưa LLM vào runtime Parser.

```sh
python -m src.parse.Hierarchy.compare_reference
```

Mặc định ưu tiên bản benchmark đã chụp cố định ở
`output/gold_reference/baseline/report.json`, tránh việc chạy lại benchmark làm
đổi mẫu đang gán nhãn. Có thể truyền `--report-path`, `--references-dir`,
`--output-dir`. Báo cáo so sánh nằm trong `gold_reference/comparison/`.

Nhãn được kiểm tra checksum source, metadata, loại nút, ID, gốc, cha/con,
chu trình, nút rời và biên byte của bằng chứng. So cây đầy đủ theo nội dung,
thứ tự và từng lần xuất hiện; thêm precision/recall/F1 cho tập đa hợp nội dung
nút, lá và cặp cha/con. Chỉ gộp khoảng trắng trước khi so, khác biệt làm sạch
khác vẫn tính là không khớp. Nhãn văn bản của gốc document không được chấm vì
đề không quy định một nhãn cố định cho gốc. Ca engine ném lỗi vẫn tính là sai
nếu có nhãn đầy đủ hợp lệ. Kết quả `outline`/`partial` hoặc còn uncertainty
không được chấm toàn cây. Nhãn thiếu/lỗi được báo riêng, không tính là đúng.

Chỉ số là **mức khớp với nhãn tham chiếu**, kèm nguồn và trạng thái draft/reviewed.
Nhãn AI còn cần kiểm tra độc lập trước khi dùng làm độ chính xác đã xác minh.


Lượt đối chiếu sau khi đồng bộ mapping/C++ nằm ở
`output/benchmark_mapping_engine/report.md`, kèm replay script cho cùng 30
chuỗi merged.tex cố định. Các nhãn cũ chưa đồng bộ chuẩn hóa toán/hình; F1 theo
nội dung phải được đọc cùng phân tích khác biệt, không chỉ xem số tổng hợp.

## Kiểm kê tag trên toàn corpus

Công cụ QA `audit_commands.py` đọc manifest Publication/Version, kiểm kê mọi
`.tex/.sty/.cls`, rồi thử chọn main → merge → native engine cho từng Version:

```sh
python -m src.parse.Hierarchy.audit_commands \
  --manifest src/parse/Hierarchy/output/undefined_commands_all/manifest.json \
  --raw-dir data/arxiv_crawl_20261024/raw \
  --output-dir src/parse/Hierarchy/output/undefined_commands_after_mapping
```

Manifest cục bộ của lượt này chứa toàn bộ 5.000 Publication / 8.486 Version.
`command_catalog.json/csv` và `environment_catalog.json/csv` giữ danh sách tag,
số lần xuất hiện, số Publication/Version/file, bằng chứng định nghĩa cục bộ,
ví dụ source và diagnostic. `source_occurrences` là token ngoài thân định nghĩa;
`macro_body_occurrences` được đếm riêng. Lexical presence không chứng minh lệnh
được thực thi; không có trong mapping cũng không chứng minh TeX không định nghĩa nó.
Diagnostic chỉ phản ánh những source merge được. Offset `<merged>` dùng byte UTF-8;
`char_offset` của ví dụ lexical là offset trong chuỗi source đã decode.

`ledger.jsonl` checkpoint từng Version. Chạy lại cùng cấu hình sẽ bỏ qua source
không đổi; source đổi được xử lý lại và record mới nhất thay record cũ trong thống
kê. Khi code, mapping, engine hoặc manifest đổi, công cụ từ chối dùng checkpoint
không tương thích; hãy dùng output directory mới để giữ kết quả cũ.
Báo cáo giữ riêng PDF-only, dữ liệu lỗi, lỗi chọn main/merge/engine và lỗi đọc file.
Các gợi ý action trong catalog cần được review trước khi sửa mapping.

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q tests/test_hierarchy_audit.py
```

Lượt bổ sung theo audit nằm ở `output/benchmark_audit_improvements/`:
`changes.md` ghi các rule mới, kiểm thử và giới hạn; `report.md` cùng thư mục
`cases/` giữ cây MD/JSON trên 30 chuỗi source cố định; `corpus_summary.json`
và `corpus_cases.jsonl` ghi lượt chạy lại engine trên các Version đã merge
được trong audit cũ. Các ca non-TeX/merge lỗi giữ trạng thái riêng, không coi là
engine parse thành công. Lượt chạy lại này không tạo lexical inventory mới.

Review độc lập Astra Medium và sáu lỗi đã tái hiện nằm ở
`output/astra_review/review.md`. Kết quả sau sửa, kiểm thử, cây MD/JSON của
cùng 30 đầu vào và replay corpus nằm ở `output/benchmark_astra_fixes/`;
`changes.md` phân biệt lỗi engine đã xác nhận với hạn chế của nhãn đánh giá.

Lượt mở rộng 60 Publication mới nằm ở `output/benchmark_expansion_90/`.
`new60/report.json` giữ mọi lần thử, kể cả merge lỗi; `annotation/manifest.json`
đóng băng 60 source để Agy dựng nhãn độc lập. `report.md` và `comparison/`
tách 30 cũ, 60 mới và tổng 90. Nhãn cũ được kiểm tra checksum và giữ nguyên;
nhãn Agy mới vẫn là draft, có scope/uncertainty và kiểm tra chất lượng riêng.
Không dùng thay đổi điểm giữa hai bộ dữ liệu khác nhau để kết luận engine cải thiện.
