<!-- Điền đủ các mục. PR thiếu mục sẽ không được review. Xem CONTRIBUTING.md mục 5. -->

## Gói và mục tiêu

<!-- Gói nào (structure / leaves / bibtex / export / khác), PR này làm gì trong 1–3 câu. -->

## Phạm vi

- Làm:
- **Không** làm (để PR sau):

## Tiêu chí "Xong khi" (docs/m2-cong-viec.md mục 4)

<!-- Chép các ô của gói mình, tích ô PR này đạt, ghi số đo bên cạnh. -->

- [ ]

## Bằng chứng

<details><summary>Output <code>pytest -q</code></summary>

```
dán output ở đây
```

</details>

<!-- Từ mốc 19/11: dán metrics/<gói>.json trên bộ mẫu 100 bài, kèm commit và seed. -->

## Kiểm tra trước khi gửi

- [ ] Test chạy offline, không cần mạng hay corpus
- [ ] Output tất định (chạy hai lần ra giống nhau), có test kiểm
- [ ] Không sửa `src/parse/types.py` hoặc `src/common/schema.py` (nếu có: giải thích ảnh hưởng)
- [ ] Không thêm thư viện mới (nếu có: lý do)
- [ ] Không dùng LLM hay mô hình pretrained
- [ ] Không commit `data/`, `*.parquet`, `.tex` thật, `.env`, token
- [ ] Golden chỉ đổi khi có giải thích
