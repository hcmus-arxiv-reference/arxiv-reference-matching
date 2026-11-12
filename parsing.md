---
title: "Mốc dự án 2 — Phân tích cú pháp phân cấp và chuẩn hóa"
short_title: "Mốc 2 — Phân tích cú pháp"
label: m2-parsing
description: "Chuyển đổi mã nguồn LaTeX thô thành một kho lưu trữ có cấu trúc phân cấp với nội dung đã được làm sạch, chuẩn hóa, khử trùng lặp (elements, hierarchy) và các mục BibTeX đã được hợp nhất (bibtex)."
---

# Mục tiêu

Trong mốc này, sinh viên sẽ chuyển từ việc thu thập dữ liệu đơn giản sang xử lý và phân tích dữ liệu nâng cao. Trọng tâm là chuyển đổi dữ liệu thô phi cấu trúc, tức mã nguồn LaTeX đã thu thập ở Mốc 1, sang định dạng có cấu trúc phân cấp với nội dung đã được làm sạch, chuẩn hóa và khử trùng lặp. Hoạt động này mô phỏng quy trình khoa học dữ liệu thực tế về xử lý và chuẩn hóa văn bản phi cấu trúc. Phần học máy của quy trình này, tức quy trình ghép tài liệu tham khảo, sẽ tiếp nối ở Mốc 3 và sử dụng các đầu ra được tạo ra tại đây.

# Mô tả

Sinh viên được yêu cầu xây dựng một bộ phân tích cú pháp tự động để xử lý các tệp mã nguồn LaTeX đã thu thập từ Mốc trước. Quy trình xử lý bao gồm các thành phần sau:

## Gom nhiều tệp

Nội dung của một mã nguồn LaTeX thường được phân bố trên nhiều tệp `.tex`, chẳng hạn thông qua các lệnh `\input` hoặc `\include`. Sinh viên phải xác định đường biên dịch chính bằng chương trình và chỉ phân tích cú pháp những tệp thực sự được đưa vào bản kết xuất PDF cuối cùng. Các tệp không được sử dụng hoặc dư thừa trong thư mục nguồn phải được bỏ qua. Cụ thể, gốc của bài công bố là tệp `.tex` chứa khai báo `\documentclass`. Lần theo các lệnh `\input` và `\include` theo tính bắc cầu, coi các lệnh đã bị chú thích là văn bản thuần thay vì lệnh đưa tệp vào, sao cho các tệp có thể đi tới từ gốc tạo thành đường biên dịch và mọi tệp khác trong thư mục nguồn đều là tệp phụ trợ dư thừa. Việc lần theo đường này tái hiện những gì chính LaTeX sẽ biên dịch, do đó kết quả phân tích bao quát những gì người đọc bản PDF cuối cùng nhìn thấy.

## Xây dựng cấu trúc phân cấp

#### Cấu trúc phân cấp

Mục tiêu là chuyển đổi mã LaTeX thô thành cấu trúc cây phân cấp cho từng phiên bản của từng bài công bố.

- **Tài liệu** đóng vai trò là gốc.

- **Chương** hoặc **Mục** thường tạo thành cấp thứ hai.

- Các phần tử khác như **Tiểu mục**, **Đoạn** và các phân chia logic tiếp theo tạo thành những cấp thấp hơn. Vì thứ tự lồng nhau chính xác phụ thuộc vào định dạng cụ thể của bài công bố, bộ phân tích cú pháp phải tự động xác định cấp phân cấp phù hợp cho từng phần tử như vậy.

#### Lưu ý khi phân tích cú pháp

Để bảo đảm tính nhất quán, bộ phân tích cú pháp phải tuân thủ các quy tắc cụ thể về mức độ chi tiết của phần tử và việc loại trừ:

- **Các phần tử nhỏ nhất:** Các nút lá của cấu trúc phân cấp phải là **Câu**, tức văn bản được phân tách bằng dấu chấm, **Công thức khối**, tức các khối toán học như nội dung của môi trường `equation` hoặc của `$$...$$`, và **Hình**, trong đó **Bảng** cũng được coi là một loại Hình cho mục đích này. Các ý liệt kê được coi là phân nhánh xuống những cấp sâu hơn, nghĩa là một khối `\begin{itemize}...\end{itemize}` được coi là một thành phần ở cấp cao hơn, với mỗi ý là một phần tử ở cấp tiếp theo. Các nút lá dạng câu mang nội dung văn xuôi của phần thân văn bản: không tách bên trong biểu thức toán học, lệnh, các từ viết tắt như i.e. và et al. và Fig. 1, URL hoặc số thập phân, vì dấu chấm không kết thúc câu thì không tạo ra nút lá mới.

- **Loại trừ:** Các mục Tài liệu tham khảo **không** được phân tích cú pháp để đưa vào cấu trúc phân cấp.

- **Đưa vào:** Lời cảm ơn và Phụ lục, thường không được đánh số thông qua dạng `\section*`, **phải** được đưa vào.

## Chuẩn hóa và khử trùng lặp

#### Làm sạch và chuẩn hóa

Sinh viên phải làm sạch và chuẩn hóa dữ liệu trong cấu trúc phân cấp:

- **Làm sạch LaTeX:** Loại bỏ các lệnh định dạng không cần thiết, chẳng hạn `\centering`, tùy chọn vị trí `[htpb]` và `\midrule`, vốn không đóng góp vào ý nghĩa ngữ nghĩa.

- **Chuẩn hóa toán học:** Chuyển tất cả biểu thức toán học nội dòng sang một định dạng thống nhất như dạng `$...$`, và chuyển tất cả biểu thức toán học dạng khối sang một định dạng thống nhất như dạng `\begin{equation}...\end{equation}`.

#### Trích xuất tài liệu tham khảo

Đối với các trích dẫn được định nghĩa bằng `\bibitem` trong các tệp `.tex`, sinh viên phải chuyển chúng thành các mục BibTeX chuẩn bằng các công cụ lập trình như biểu thức chính quy.

#### Khử trùng lặp

Việc khử trùng lặp được yêu cầu ở hai mức, và cả hai mức đều hoạt động *xuyên suốt các phiên bản* của một bài công bố:

- **Các mục tài liệu tham khảo:** Các mục tài liệu tham khảo trùng lặp trong từng phiên bản hoặc giữa các phiên bản khác nhau của cùng một bài công bố cần được xử lý phù hợp. Nếu các khóa trích dẫn khác nhau, tức tên của các mục, cùng trỏ tới một nội dung tài liệu tham khảo, cần chọn một khóa trích dẫn duy nhất, và các lệnh `\cite{}` của những mục còn lại phải được đổi tên sang khóa đã chọn này. Ngoài ra, quá trình khử trùng lặp cần hợp các trường của những mục trùng lặp thay vì chọn một mục rồi loại bỏ toàn bộ thông tin khác. Xét một tài liệu tham khảo được giữ lại qua ba phiên bản: phiên bản 1 liệt kê tài liệu đó bằng khóa `vaswani2017` với tiêu đề, tác giả và năm, phiên bản 2 đổi tên khóa thành `vit_transformer` và thêm `doi`, còn phiên bản 3 giữ nguyên tài liệu tham khảo đó với khóa `vit_transformer` nhưng bỏ `year`. Khi đó, mục hợp nhất giữ một khóa đã chọn, hợp các trường thành tiêu đề, tác giả, năm và doi, và các lệnh `\cite` trỏ tới những khóa bị loại bỏ được đổi tên sang khóa đã chọn, chính là dòng được đưa vào bảng `bibtex` bên dưới. Một ví dụ minh họa chi tiết cho mức còn lại được trình bày tiếp theo cùng các bảng trong phần Yêu cầu, trong đó một câu dùng chung phục vụ cả hai phiên bản dưới dạng một phần tử duy nhất.

- **Nội dung toàn văn:** Việc khử trùng lặp nội dung toàn văn phải được áp dụng cho các phần tử phân cấp. Nếu nội dung văn bản của một phần tử khớp hoàn toàn giữa các phiên bản khác nhau, tức khớp toàn văn sau khi làm sạch, phần tử đó cần được biểu diễn bằng một định danh duy nhất trong đầu ra cuối cùng để giảm dư thừa. Lưu ý: việc đối sánh toàn văn cần được thực hiện *sau* khi làm sạch để loại bỏ những khác biệt ở các chi tiết nhỏ như định dạng hoặc khoảng trắng, vốn có thể khiến mã nhận diện những văn bản giống hệt nhau là khác nhau.

# Yêu cầu

Xử lý mọi bài công bố được tạo ra ở Mốc 1. Với mỗi bài công bố, phân tích cú pháp mã nguồn LaTeX của mọi phiên bản theo đường biên dịch, xây dựng cấu trúc phân cấp, chuẩn hóa và khử trùng lặp nội dung, đồng thời trích xuất tài liệu tham khảo thành một tập các mục BibTeX đã được hợp nhất. Một phiên bản không có mã nguồn TeX, được Mốc 1 giữ lại dưới dạng một bản ghi rỗng, sẽ không tạo ra phần tử đã phân tích cú pháp nào: ghi nhận phiên bản đó là rỗng thay vì bỏ qua, để số liệu thống kê độ phủ và các bảng bên dưới phản ánh đúng thực tế.

Mốc này **không yêu cầu nộp dữ liệu**: tập dữ liệu đã xử lý được nhóm giữ lại làm đầu vào làm việc cho Mốc 3, giống như tập dữ liệu đã thu thập ở Mốc 1.

**Gợi ý tổ chức dữ liệu.** Như ở Mốc 1, các nhóm tự tổ chức dữ liệu làm việc của mình. Gợi ý này áp dụng cùng tinh thần đó cho dữ liệu đã được phân tích cú pháp và chuẩn hóa, vì vậy có thể làm theo nguyên trạng hoặc điều chỉnh cho thuận tiện. Với mỗi bài công bố, lưu chung nội dung và cấu trúc đã phân tích cú pháp của *tất cả* các phiên bản: các phần tử đã phân tích cú pháp, quan hệ cha giữa chúng theo từng phiên bản, và các mục BibTeX đã được hợp nhất, khử trùng lặp. Dữ liệu này thay thế thư mục TeX thô từ Mốc 1 làm tài liệu cho các bước xử lý tiếp theo, vì vậy cần lưu đủ thông tin để lập các bảng cuối cùng mà không phải phân tích cú pháp lại.

Ở lần nộp cuối cùng trong Mốc 3, dữ liệu này trở thành các bảng của bộ dữ liệu được công bố. Mốc này đã quy định ba bảng trong số đó:

| **Bảng** | **Các cột (kiểu dữ liệu) và nội dung** |
|:---|:---|
| elements | một dòng cho mỗi phần tử *phân biệt* trên tất cả các phiên bản của bài công bố: element_id (string, non-null), arxiv_id (string, non-null), kind (string, dictionary), content (string). Nội dung khớp hoàn toàn giữa các phiên bản, tức khớp toàn văn sau khi làm sạch, chỉ chiếm một dòng |
| hierarchy | arxiv_id (string, non-null), version (int), element_id (string, non-null), parent_id (string, non-null), với một dòng cho mỗi cạnh nút-cha của từng phiên bản |
| bibtex | arxiv_id (string, non-null), citation_key (string, non-null), entry_type (string, dictionary), title (string), authors (list of strings), year (int, nullable), doi (string), journal (string), url (string), lưu các mục BibTeX đã được hợp nhất sau khi khử trùng lặp và gộp |
*Các bảng của bộ dữ liệu được quy định trong mốc này*

**Cách lưu trữ các phần tử và cấu trúc phân cấp giữa các phiên bản.** Các phần tử của những phiên bản khác nhau dùng chung một kho lưu trữ: khi một nút lá hoặc thành phần xuất hiện trong hai phiên bản với nội dung đã làm sạch giống hệt nhau, nó chỉ được ghi nhận một lần, nên một `element_id` duy nhất phục vụ cả hai phiên bản, đúng với yêu cầu khử trùng lặp ở trên. Khi đó, các dòng `hierarchy` chỉ lưu các cạnh nút-cha của từng phiên bản, và một phần tử do phiên bản trước đóng góp có thể đóng vai trò là nút trong các cạnh của phiên bản sau, được gắn với một nút cha chỉ tồn tại trong phiên bản sau đó. Định danh phần tử bắt đầu bằng khóa của bài công bố, theo sau là một thành phần phân biệt duy nhất trong phạm vi bài công bố. Ví dụ nhỏ bên dưới, gồm một bài công bố với hai phiên bản và một câu không thay đổi giữa cả hai, cho thấy các dòng kết quả:

| **element_id**   | **kind** | **content**                            |
|:-----------------|:---------|:---------------------------------------|
| 2310-12345#root1 | document | Gốc phiên bản 1                        |
| 2310-12345#root2 | document | Gốc phiên bản 2                        |
| 2310-12345#h1    | heading  | Giới thiệu                             |
| 2310-12345#h2    | heading  | Bối cảnh và mô hình                    |
| 2310-12345#s1    | sentence | Chúng tôi nghiên cứu bài toán ghép trích dẫn |
*Các dòng `elements` minh họa, một kho lưu trữ dùng chung trong đó `s1` phục vụ cả hai phiên bản*

| **version** | **element_id** | **parent_id**    |
|:------------|:---------------|:-----------------|
| 1           | 2310-12345#h1  | 2310-12345#root1 |
| 1           | 2310-12345#s1  | 2310-12345#h1    |
| 2           | 2310-12345#h2  | 2310-12345#root2 |
| 2           | 2310-12345#s1  | 2310-12345#h2    |
*Các dòng `hierarchy` minh họa: câu dùng chung `s1` là một nút trong cả hai phiên bản, được gắn với `h1` ở phiên bản 1 và với `h2` ở phiên bản 2*

# Hình thức nộp bài

## Mã nguồn

Mã nguồn của mốc này được commit vào cùng một kho GitHub công khai duy nhất đã sử dụng ở Mốc 1, tiếp tục lịch sử tích lũy ghi lại tiến độ của nhóm. Kho chỉ chứa các tệp mã nguồn như tệp Python có phần mở rộng `.py` hoặc `.ipynb` và loại trừ các tệp dữ liệu, tệp thực thi đã biên dịch cùng những tài liệu không phải mã nguồn khác, kèm theo:

```
<group-repo>/
|-- src # thư mục chứa mã nguồn
|   |-- *.{py/ipynb}
|   |-- requirements.txt # Để tái tạo môi trường
|-- README.md # Hướng dẫn thiết lập môi trường và thực thi mã
```

Mốc này được nộp theo nhóm qua Moodle bằng cách dán các liên kết công khai tới kho mã nguồn dùng chung và báo cáo mốc được mô tả bên dưới. Tất cả các bài nộp nêu trên phải sử dụng ngôn ngữ chính thức của chương trình học của bạn. **KHÔNG cho phép nộp trễ**.

## Yêu cầu báo cáo (Jupyter Book)

Sinh viên phải chuẩn bị báo cáo mốc được biên dịch dưới dạng **Jupyter Book**, sử dụng cùng kho sách đã được giới thiệu ở Mốc 1 và được lưu trữ trên GitHub Pages của kho đó, bổ sung một phần về phân tích cú pháp và chuẩn hóa vào sách đó thay vì tạo sách mới. Sách phải trình bày số liệu thống kê và phân tích dữ liệu đã xử lý, đồng thời các hình và bảng phải được *tạo ra trong quá trình biên dịch sách*, không được dán dưới dạng ảnh chụp màn hình tĩnh, nhằm bảo đảm chất lượng và tính tương tác. Cụ thể, báo cáo cần bao gồm:

- **Phân tích cú pháp phân cấp:** Giải thích logic được sử dụng để phát hiện cấu trúc tệp, phân tích cấu trúc phân cấp LaTeX và xử lý đầu vào gồm nhiều tệp.

- **Chuẩn hóa:** Chi tiết về cách triển khai việc làm sạch dữ liệu, chuẩn hóa toán học và khử trùng lặp tài liệu tham khảo.

- **Thống kê:** Các số liệu thống kê liên quan như tỷ lệ phân tích cú pháp thành công, độ phủ phiên bản của từng bài công bố và số lượng phần tử/mục trước và sau khi khử trùng lặp.

Hiệu năng của bộ phân tích cú pháp cũng cần được minh họa qua hai điểm chính là thời gian chạy và mức sử dụng bộ nhớ: thời gian chạy tính thời gian thực từ đầu đến cuối của bộ phân tích cú pháp và thời gian trung bình để xử lý một bài công bố, còn mức sử dụng bộ nhớ tính lượng RAM tối đa đã sử dụng và dung lượng lưu trữ của đầu ra cuối cùng. Môi trường thử nghiệm cho việc đo hiệu năng cuối cùng là một phiên Google Colab chạy ở chế độ chỉ dùng CPU. Không áp dụng giới hạn trên cho thời gian chạy, còn giới hạn trên của mức sử dụng ổ đĩa tối đa do phiên Colab quy định.

Tệp `README.md` của kho vẫn được giữ riêng: tệp này cung cấp hướng dẫn rõ ràng về việc thiết lập môi trường cần thiết, chẳng hạn phiên bản Python và các gói cần cài đặt thông qua pip hoặc conda, cũng như chạy mã với các cấu hình cụ thể.

# Tiêu chí chấm điểm

Điểm của bạn được xác định dựa trên năm tiêu chí chính được liệt kê bên dưới:

- **Bộ phân tích cú pháp phân cấp:** Độ chính xác của bộ phân tích cú pháp trong việc phát hiện cấu trúc, xử lý mã nguồn gồm nhiều tệp và xác định các cấp phân cấp phù hợp.

- **Chuẩn hóa và khử trùng lặp:** Thực hiện đúng việc làm sạch, chuẩn hóa toán học, trích xuất tài liệu tham khảo và cả hai mức khử trùng lặp, bao gồm các mục tài liệu tham khảo thông qua việc đổi tên `\cite` và hợp các trường, cũng như nội dung toàn văn giữa các phiên bản.

- **Hiệu năng của bộ phân tích cú pháp:** Mức độ hiệu quả của bộ phân tích cú pháp thông qua thời gian chạy và mức sử dụng bộ nhớ.

- **Chất lượng mã nguồn và khả năng tái lập:** Mã nguồn gọn gàng, chạy được, có hướng dẫn rõ ràng.

- **Báo cáo (Jupyter Book):** Các hình được tạo ra khi biên dịch sách, tính tương tác và tính rõ ràng của sách được lưu trữ trực tuyến.
