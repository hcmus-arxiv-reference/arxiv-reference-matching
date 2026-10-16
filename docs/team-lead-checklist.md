# Checklist của nhóm trưởng

Cập nhật 2026-10-16. Người phụ trách: Nguyễn Thành Bảo (nhóm trưởng, Parser).
Chỉ đánh dấu hoàn tất khi có bằng chứng; test mock không thay cho chạy dữ liệu thật.

## 1. Phạm vi, trách nhiệm và thời hạn

- [x] Ghi nhận Range của Bảo: `2508.02872`–`2508.07871`, bao gồm hai đầu,
  5.000 ID được giao; phải lấy mọi Version.
- [x] Ghi nhận trách nhiệm của Bảo: hạ tầng chung, Parser, QA và thống kê
  phục vụ báo cáo; các phần khác chỉ hỗ trợ tích hợp theo AGENTS.md.
- [ ] Chốt danh sách đủ 5 thành viên, tên thư mục `MEMBER_NAME` duy nhất,
  Range và tài khoản Hugging Face của từng người. README hiện mới nêu 4 tài khoản.
- [ ] Chốt người sở hữu Crawler, Semantic Scholar/metadata, Chuẩn hóa/BibTeX
  và Matching; thống nhất đầu vào/đầu ra để tránh hai người cùng sửa một phần.
- [ ] Ghi deadline từng milestone và lịch bàn giao nội bộ theo thông báo lớp.

## 2. Hợp đồng dữ liệu trước khi chạy hàng loạt

- [x] Đối chiếu trang Crawling và ghi tên cột `papers`, `references` tại
  [crawling-requirements.md](crawling-requirements.md).
- [x] Chốt `papers.authors`, `papers.revised_dates`, `references.ref_authors`
  là list of strings, không ghép chuỗi hoặc JSON blob.
- [x] Chốt đường dẫn Hugging Face: `raw/<member>/<publication key>/v<n>/`
  và `tables/<member>/<tên bảng>.parquet`.
- [x] Ghi rõ `publicationDate` của Semantic Scholar không mặc nhiên là
  `ref_submission_date`; tham khảo [semantic-scholar-check.md](semantic-scholar-check.md).
- [ ] Đối chiếu đề Parsing và Matching; giải quyết bất nhất 6/7 bảng và tên
  bảng giữa kế hoạch, README và schema dự thảo.
- [ ] Chốt Element ID, cách giữ từng lần xuất hiện/thứ tự đọc và khóa
  `hierarchy` khi nội dung giống nhau xuất hiện nhiều chỗ.
- [ ] Chốt đường dẫn raw cục bộ và hợp đồng manifest theo `(arxiv_id, version)`:
  Version dự kiến, trạng thái, checksum, checkpoint, lỗi và `non_tex`.
- [ ] Nhóm trưởng xác nhận, đóng băng schema toàn dự án và ghi phiên bản hợp
  đồng; đổi sau đó phải thông báo và được duyệt trước khi các thành viên xuất lại dữ liệu.

## 3. Hạ tầng và truy cập

- [x] Có `src/common/{schema,config,hf_io,metrics}.py`, test và hướng dẫn cài đặt.
- [x] Cài dependencies và chạy **54 test đạt**, kèm 15 subtest. Bằng chứng:
  [infrastructure-review.md](infrastructure-review.md).
- [x] Có `.env.example`, `.gitignore`; `.env`, dữ liệu, Parquet và môi trường
  Python cục bộ bị loại khỏi Git.
- [x] Đã kiểm tra `CONTACT_EMAIL` có giá trị cục bộ, không đưa địa chỉ vào repo.
- [x] Module chặn upload ngoài thư mục thành viên và chặn repo public.
  Đây là kiểm tra trong module, không kiểm soát thao tác thủ công bằng công cụ khác.
- [ ] Điền `HF_TOKEN`, `HF_REPO_ID` cục bộ và chạy `ensure_repo` thật qua
  `.venv/bin/python -m scripts.check_hf` để tạo/xác minh dataset private.
- [ ] Thử upload/download thật một thư mục mẫu và một bảng Parquet của mình;
  so nội dung/checksum trước và sau. Chỉ thực hiện khi đã có mẫu và repo phù hợp.
- [ ] Xác nhận quyền truy cập dataset giữa các thành viên, không chia sẻ token trong repo/chat.
- [ ] Chạy test tự động trên GitHub Actions và thử setup từ clone sạch.

## 4. Bàn giao dữ liệu mẫu cho Parser

- [ ] Chọn 3–5 Publication trong Range, tải mọi Version và lưu snapshot discovery.
- [ ] Một kết nối arXiv, cách ít nhất 3 giây giữa request, dùng
  `export.arxiv.org` và User-Agent có email cấu hình.
- [ ] Nhận diện tar/gzip/TeX/PDF theo nội dung; giải nén an toàn và chỉ giữ
  `.tex`, `.bib`, giữ nguyên nội dung cùng đường dẫn tương đối cho input/include.
- [ ] Version không có TeX vẫn có bản ghi rõ ràng; timeout/429/5xx được ghi
  là lỗi cần xử lý, không biến thành kết luận không có TeX.
- [ ] Chạy tải lần hai chứng minh resume bỏ qua dữ liệu đã xác minh, và thử
  trường hợp checkpoint còn nhưng file bị thiếu/hỏng.
- [ ] Thành viên S2 lấy hết các trang bằng `next`, giữ metadata thô cục bộ,
  chỉ lọc reference có arXiv ID khi xuất bảng, cache ở cấp Publication.
- [ ] Nhóm trưởng kiểm tra tay mẫu đa dạng trước khi mở rộng.

## 5. Parser và QA tích hợp

- [ ] Test từng lớp Parser: file gốc/input/include, headings, sentence,
  formula, figure/table, itemize, chuẩn hóa và deduplicate sau cleanup.
- [ ] Có Acknowledgements/Appendices; loại References khỏi hierarchy.
- [ ] Không dùng LLM/pretrained trong Parser; mọi ngoại lệ có code và log.
- [ ] Schema validation đạt; kiểm tra khóa ngoại, Publication/Version,
  parent, chu trình và thứ tự/lần xuất hiện theo hợp đồng đã chốt.
- [ ] Chạy Parser cả Range với checkpoint; một Version lỗi không dừng cả lượt.
- [ ] Thu bảng các thành viên từ Hugging Face và xuất QA theo chủ sở hữu:
  schema, khóa trùng giữa shard/Range, reference, BibTeX thiếu tiêu đề,
  độ phủ Version và mẫu ngẫu nhiên tái lập bằng seed.
- [ ] Báo lỗi cụ thể cho đúng người sửa, không tự ghi đè dữ liệu của người khác.
- [ ] Kiểm tra log mọi chỉnh sửa tay; review script gộp của người phụ trách.

## 6. Báo cáo và nộp bài

- [ ] Chốt môi trường Colab CPU, phiên bản dependencies và ID/snapshot benchmark.
- [ ] Đo end-to-end, thời gian discovery/trung bình mỗi bài, RAM đỉnh/trung
  bình của toàn hệ thống, disk đỉnh và dung lượng cuối; ghi rõ đơn vị/phạm vi đo.
- [ ] Ghi số Publication/Version dự kiến, thành công, thiếu và lý do; số
  Element trước/sau dedup, reference coverage và dung lượng trước/sau bỏ ảnh.
- [ ] Jupyter Book ở repo riêng; bảng/hình sinh bằng code lúc build, không dùng ảnh chụp.
- [ ] Đối chiếu yêu cầu Matching/nhãn/split/đánh giá với chủ sở hữu trước khi tổng hợp báo cáo.
- [ ] Hoàn thiện README, ghim dependencies, thử quy trình trên clone sạch và
  kiểm tra lịch sử Git không có bí mật/dữ liệu.
- [ ] Chuẩn bị poster và các link nộp bài theo thông báo lớp; kiểm tra quyền
  xem repo, báo cáo và dữ liệu đúng yêu cầu trước khi nộp.

## Việc ưu tiên tiếp theo

1. Bổ sung cấu hình Hugging Face và xác minh repo private thật.
2. Hoàn tất hợp đồng schema còn mở với nhóm; giữ rõ phạm vi Crawling trước.
3. Chuẩn bị bộ tải mẫu có manifest/resume và kiểm tra bàn giao cho Parser.
