# Bối cảnh triển khai

## Thuật ngữ

- **Publication:** bài arXiv có ID gốc, không kèm hậu tố version.
- **Version:** một phiên bản của Publication (`v1`, `v2`, …).
- **Reference:** bản ghi Semantic Scholar của bài được trích dẫn có arXiv ID.
- **BibTeX entry:** mục trích dẫn sau chuẩn hóa và khử trùng lặp.
- **Element:** nút của cây phân cấp tài liệu.
- **Range:** dải arXiv ID giao cho một thành viên. Mỗi thành viên chạy codebase
  chung trên Range của mình; dữ liệu các Range được gộp ở bước riêng.
- **Stage:** một bước của crawler có interface riêng, là đơn vị để so sánh và ghép
  bản cài đặt giữa các thành viên. Gồm: **Discovery** (ID → Publication, danh sách
  Version, metadata), **Source fetch** (Version → `.tex/.bib`), **References**
  (Publication → Reference), **Manifest** (trạng thái để resume), **Export**
  (ghi bảng `papers`/`references`), **Runner** (chạy toàn Range).
  _Tránh_: module, bước, quá trình (khi muốn nói đúng nghĩa này).
- **Engine:** một cách ghép đầy đủ các Stage thành crawler chạy được. `main` chỉ giữ
  một Engine (ADR 0001).
