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
`preserve`, `paragraph_break`) và môi trường (`root`, `list`, `heading`,
`transparent`, `formula`, `figure`, `literal`, `inline_math`, `exclude`).
`arguments`/`optional_arguments` hoặc `argument_spec` xác định chính xác đối số
cần đọc. `optional_argument_indices` chọn phần pretext cần giữ trong wrapper;
`paragraph_boundary: false` cho phép wrapper bố cục giữ câu xuyên qua ranh giới.
`contexts` giới hạn cleanup ở prose/heading/figure/formula, nên lệnh
định dạng trong văn xuôi có thể được bỏ mà vẫn giữ lệnh có ý nghĩa trong toán.

Abstract và Acknowledgements tạo section theo rule; enumerate/description tạo
itemize. Các môi trường proof/theorem/lemma đã khai báo được đọc tiếp phần thân.
Công thức nhiều dòng giữ nguyên hàng/cột trong aligned/gathered/alignedat/array,
rồi bọc equation. Hình/bảng giữ nội dung nguyên khối, bỏ placement ngoài và các
lệnh định dạng đã khai báo; đối số như width của includegraphics vẫn được giữ.
Literal environments giữ chính xác thân, kể cả whitespace, `%` và lệnh giả.

Đây vẫn là parser cú pháp, không thực thi macro TeX hay suy diễn environment
tùy biến. Tag ngoài mapping ở luồng văn bản được giữ kèm diagnostic; môi trường
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
