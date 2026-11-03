# Chuẩn bị trước
Chơi thử các map 1,2,4,9 để lúc demo được mượt

# Kịch bản

## 1. Giới thiệu
“Đây là chương trình Bloxorz Solver của nhóm. Người chơi điều khiển khối hộp lăn trên bàn và đưa khối đứng thẳng vào ô đích. Chương trình hỗ trợ chơi thủ công và tìm lời giải bằng BFS, DFS, UCS, A*.”

“Giao diện gồm bàn chơi, số bước, bảng chọn màn và chế độ giải bằng thuật toán.”

## 2. Demo luật chơi cơ bản

Thao tác trên màn 1:
1. Di chuyển để thấy khối đứng, nằm ngang và nằm dọc.
2. Cố tình lăn ra ngoài để trình diễn hiệu ứng rơi và chơi lại.
3. Hoàn thành màn; cho thấy khối lọt xuống đích, bảng sao và nút qua màn/chơi lại.
Lời dẫn mẫu:
“Khối có ba tư thế chính: đứng, nằm ngang và nằm dọc. Mỗi lần lăn làm thay đổi vị trí hoặc tư thế. Nếu khối không được sàn đỡ đầy đủ, lượt chơi thất bại.”

“Chỉ khi khối nguyên vẹn đứng trên ô đích thì màn chơi mới hoàn thành. Sau khi thắng, chương trình hiển thị số bước, thời gian, đánh giá sao và mở khóa màn tiếp theo.”

## 3. Demo các ô đặc biệt

Nên chia thành các đoạn ngắn và cắt chuyển giữa màn, không cần chơi hết từng màn.
- Ô dễ vỡ: cho khối nằm trên ô, sau đó minh họa việc đứng lên khiến khối rơi.
- Công tắc O và X: cho thấy cầu thay đổi khi kích hoạt; giải thích O nhận mọi phần khối, X yêu cầu khối nguyên vẹn đứng lên.
- Công tắc tách khối: kích hoạt, di chuyển một khối, nhấn Space đổi khối và đưa hai khối về cạnh nhau để ghép.
Lời dẫn mẫu:
“Ô màu vàng/cam không chịu được khối nguyên vẹn đứng thẳng, nhưng cho phép khối nằm trên nó.”

“Công tắc O kích hoạt khi có phần khối đè lên. Công tắc X chỉ kích hoạt khi khối đứng thẳng. Tùy cấu hình màn, công tắc đảo trạng thái cầu hoặc đặt cầu về trạng thái xác định.”

“Công tắc tách chia khối thành hai khối con. Người chơi dùng Space để đổi khối điều khiển. Hai khối sẽ tự ghép khi nằm kề nhau; một khối con riêng lẻ không thể hoàn thành màn.”

## 4. Demo các thuật toán
“Trong chế độ giải tự động, thuật toán tìm đường từ trạng thái hiện tại, bao gồm cả trạng thái cầu và khối đang điều khiển.”

“Kết quả gồm thời gian tìm kiếm, bộ nhớ đỉnh Python, số node mở rộng và độ dài lời giải. Chức năng Replay phát lại các hành động tìm được; Pause và Step giúp quan sát từng bước.”

“Solver dùng chung bộ luật với chế độ chơi thủ công nên lời giải vẫn tuân thủ các quy tắc về ô dễ vỡ, cầu và tách khối.”

## 5. So sánh các thuật toán

Thao tác: Chạy lần lượt bốn thuật toán trên cùng một màn, Restart trước mỗi lần. Không cần phát hết lời giải DFS dài; chỉ trình diễn vài bước rồi Pause.

Lời dẫn mẫu:
“Nhóm chạy các thuật toán trên cùng trạng thái đầu để so sánh công bằng. BFS tìm lời giải ít hành động nhất khi mỗi hành động có chi phí 1. UCS cũng tối thiểu hóa số hành động trong cấu hình chi phí này.”

“DFS ưu tiên đi sâu nên có thể tìm ra lời giải dài hơn. Thời gian tìm kiếm và thời gian phát lại là hai đại lượng khác nhau: thuật toán có thể tìm nhanh nhưng trả về nhiều bước.”

“A* sử dụng heuristic để định hướng tìm kiếm. Hiệu quả cụ thể được đánh giá qua số liệu thực nghiệm của nhóm.”

Chỉ đọc số liệu thực tế trên màn hình, không khẳng định thuật toán nào luôn nhanh nhất.

## 6. Kết thúc

Thao tác: Nếu cần, bấm Export CSV; kết thúc bằng màn game hoặc bảng kết quả.

Lời dẫn mẫu:
“Chương trình đã hỗ trợ chơi thủ công, các ô đặc biệt và bốn thuật toán tìm kiếm. Kết quả được ghi nhận để phục vụ phân tích, so sánh trong báo cáo. Cảm ơn thầy cô đã theo dõi.”