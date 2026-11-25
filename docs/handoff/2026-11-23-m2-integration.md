# Integration: hoàn thiện mốc 19/11 của issue #33

Ngày thực hiện: 23/11/2026. Nhánh local `feat/m2-export` được fast-forward tới
`00dad41` trên `main`, gồm các PR #44, #46, #51 đã merge.
Phần hoàn thiện được bàn giao trên nhánh `codex/m2-integration-19nov`.

## Thay đổi

- Nối trực tiếp các gói thật: Source 5, Structure 3, Leaves 1, Normalize 1, BibTeX 6.
- Xóa `src/parse/_fallback.py` và các nhánh thay thế trong Integration.
  `default_normalize` nay trỏ tới normalizer thật. Giữ `allow_fallback` và
  `--allow-fallback` để lời gọi cũ vẫn chạy, nhưng chúng không bật gói thay thế;
  metrics luôn ghi `allow_fallback: false`, `fallback_modules: []`.
- Export 3, Pipeline 5: thay đổi phiên bản để checkpoint cũ không bị dùng lại.
  Log JSONL sắp xếp khóa trước khi ghi: trước đây resume đọc JSON checkpoint
  đã sắp khóa, làm log khác byte so với lượt chạy mới dù nội dung giống nhau.
- Test tích hợp chạy bằng các gói thật, gồm đổi key trước normalize, gộp entry
  giữa Version, chia sẻ Element, tính tất định và resume không gọi assembler.

## Bộ mẫu và kết quả

Đầu vào là `configs/m2-sample-100.json`, seed `20261112`, corpus thật
`data/m2-sample`. Xác minh đạt 100/100 Publication, 148 Version, gồm 7 non-TeX.
Không sửa raw, receipt, golden hay schema.

| Chỉ số | Kết quả |
|---|---:|
| Publication thành công / tổng | 93 / 100 |
| Publication chỉ có Version rỗng | 6 |
| Version parsed / non-TeX / failed / missing | 132 / 7 / 9 / 0 |
| Độ phủ Version | 93,9189% |
| Element trước / sau khử trùng lặp | 52.650 / 39.492 |
| Ứng viên BibTeX / entry cuối | 11.031 / 3.653 |
| Cạnh hierarchy | 52.278 |
| Citation key thiếu entry | 985 |

Số ứng viên BibTeX giảm do cả gộp trùng và lọc group không được cite (C12),
không diễn giải toàn bộ mức giảm là trùng lặp. `metrics/export.json` lưu thời gian,
RAM đỉnh tiến trình hiện tại và dung lượng ảnh chụp của lượt chạy mới, không resume.
Đây là đo local CPU; chưa phải benchmark Colab CPU mốc 25/11.
`git_commit` trong metrics là base `00dad41` tại thời điểm đo trước commit;
code của lượt đo được nhận diện thêm bằng các phiên bản module ở trên và checksum
trong báo cáo nghiệm thu local.

## Kiểm tra và tái lập

Môi trường: `/home/nhminh/miniconda3/envs/DL_Env/bin/python` (Python 3.12.13),
đã cài dependency dự án ghim `bibtexparser==2.1.0` theo chấp thuận của người dùng.
Trong các lệnh dưới, `python` là Python của môi trường này.

```sh
python -m scripts.m2_sample verify --plan configs/m2-sample-100.json --data-dir data/m2-sample
python -m scripts.parse_range --data-dir data/m2-sample --plan configs/m2-sample-100.json \
  --out-dir data/parse-19nov-real-a --metrics metrics/export.json --no-resume
python -m scripts.parse_range --data-dir data/m2-sample --plan configs/m2-sample-100.json \
  --out-dir data/parse-19nov-real-b --no-resume
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/test_parse_export.py tests/test_parse_types.py tests/test_parse_normalize.py \
  tests/test_parse_bibtex.py tests/test_parse_structure.py tests/test_parse_leaves.py \
  tests/test_parse_leaves_golden.py tests/test_parse_sentences.py tests/test_parse_source.py \
  tests/test_parse_bibtex_input.py tests/test_parse_bibtex_input_sidecar.py
```

Kiểm thử đã chạy: **204 passed in 1.42s** cho các module M2 ở lệnh trên;
`git diff --check` đạt. Không chạy toàn bộ suite vì thay đổi chỉ thuộc Integration M2.

Hai lượt chạy mới cho **304 file giống hệt từng byte**: ba bảng, JSONL và 300 file
checkpoint/export/order của 100 Publication. Đã đọc lại ba bảng qua `schema.validate`
và nạp cả 100 checkpoint qua `validate_E` (I1–I9), log đủ 148 cặp `(arxiv_id, version)`.
Resume dùng lại **100/100** checkpoint, không gọi assembler, và 304 file vẫn giữ
nguyên checksum. File metrics được loại khỏi so sánh byte vì chứa thời gian/RAM.
Chi tiết checksum output/code và danh sách lỗi: `data/m2-19nov-acceptance.json`
(local, không commit dữ liệu). `metrics/export.json` giữ số đo lượt chạy mới:
24,2226 giây, peak RSS 238,79 MB; hai lượt kiểm tính tất định chạy đồng thời trên máy.

## Giới hạn bàn giao

Đã chạy đủ 100 bài bằng các gói thật; không đồng nghĩa mọi bài parse thành công
hay mọi tiêu chí chất lượng Parser đã được nghiệm thu.

- `2508.03907v1`, `2508.04618v1,v2`: validator Structure phát hiện
  `Block.raw` còn comment LaTeX. Cần chuyển cho gói Source/Structure xử lý bằng fixture.
- `2508.03927v1`, `2508.06982v1`: `invalid_syntax`, đã ghi trong bàn giao BibTeX.
- `2508.06444v1`, `2508.06783v2`, `2508.07326v1,v2`: `ambiguous_root`.
  Pipeline hiện chưa nhận cấu hình root đã review.
- 985 key thiếu entry được giữ theo hợp đồng `missing_entry`, không sinh entry giả.
  PR #59 đang nối sidecar bibliography và root đã review vào pipeline để xử lý
  phần thiếu này. Không tự sửa source hay ghép key không phân biệt hoa/thường.
- Chưa chạy toàn Range, benchmark Colab CPU hoặc nghiệm thu thủ công chất lượng lá/BibTeX.

Nguồn: [issue #33](https://github.com/hcmus-arxiv-reference/arxiv-reference-matching/issues/33),
[PR #51](https://github.com/hcmus-arxiv-reference/arxiv-reference-matching/pull/51),
[PR #59](https://github.com/hcmus-arxiv-reference/arxiv-reference-matching/pull/59),
[bàn giao BibTeX](2026-11-21-bibtex.md).
