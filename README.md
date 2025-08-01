# HỆ THỐNG GIÁM SÁT & CÂN BẰNG TẢI SDN WI-FI RESORT

**Người thực hiện:** Lê Gia Hoàng Thiện, Phạm Thị Thanh Vinh, Lê Hoàng Vũ, Lê Thị Thùy Trang\
**Môn học:** Thiết kế mạng / SDN\
**Dự án:** Mô phỏng hệ thống quản lý, giám sát và cân bằng tải các Access Point trong mạng Wi-Fi Resort sử dụng Mininet-WiFi và Ryu SDN Controller.

---

## 1. Mục đích dự án

- Mô phỏng mạng Wi-Fi cho resort với nhiều Access Point (AP) và các client di động (station).
- Giám sát trạng thái, hiệu suất, phát hiện AP lỗi hoặc quá tải.
- Cân bằng tải, tự động chuyển client sang AP tối ưu dựa trên RSSI và tình trạng AP.
- Cung cấp giao diện web trực quan hiển thị trạng thái hệ thống, số client, hiệu suất mạng, sự kiện roaming.
- Hỗ trợ thử nghiệm, kiểm chứng các thuật toán cân bằng tải, phát hiện lỗi AP trong môi trường ảo hóa.

---

## 2. Thành phần mã nguồn

### 2.1. `topology_mininetwifi.py`

- **Chức năng:**
  - Khởi tạo và mô phỏng topo mạng Wi-Fi Resort bằng Mininet-WiFi (3 AP đại diện các khu vực: Lobby, Pool, Conference).
  - Sinh 8 thiết bị client với vị trí thực tế khác nhau, mô phỏng kết nối và roaming.
  - Gửi dữ liệu RSSI về controller để phục vụ cân bằng tải, mô phỏng hành vi di chuyển.
  - Hỗ trợ dừng/bật AP (demo AP bị lỗi), tạo traffic liên tục giữa các thiết bị.
- **Chạy:**
  ```bash
  sudo python3 topology_mininetwifi.py
  ```

### 2.2. `ryu_controler.py`

- **Chức năng:**
  - Triển khai SDN WiFi Load Balancer bằng Ryu Controller (OpenFlow v1.3).
  - Theo dõi số client, trạng thái AP, phát hiện AP lỗi (không có lưu lượng), xử lý tự động chuyển client sang AP khác.
  - Cung cấp REST API trả về trạng thái tải từng AP, danh sách client, chỉ số hiệu suất, nhận dữ liệu RSSI từ client.
  - Giám sát sự kiện roaming, phân tích lỗi mạng, ghi nhận lịch sử.
- **Chạy:**
  ```bash
  ryu-manager ryu_controler.py
  ```

### 2.3. `API_monitering.py`

- **Chức năng:**
  - Xây dựng giao diện web giám sát hệ thống SDN WiFi resort với Flask và Chart.js.
  - Truy xuất số liệu qua API, hiển thị bảng trạng thái AP, số client, trạng thái lỗi, hiệu suất mạng, sự kiện roaming.
  - Cập nhật dữ liệu realtime mỗi 2 giây, có bảng chi tiết host, biểu đồ số client.
- **Chạy:**
  ```bash
  python3 API_monitering.py
  ```
  - Sau đó truy cập: [http://localhost:5000](http://localhost:5000)

---

## 3. Hướng dẫn sử dụng

1. **Cài đặt Mininet-WiFi và Ryu Controller** (làm theo hướng dẫn chính thức).
2. **Khởi chạy controller:**
   ```bash
   ryu-manager ryu_controler.py
   ```
3. **Khởi chạy mô phỏng topo Mininet-WiFi:**
   ```bash
   sudo python3 topology_mininetwifi.py
   ```
4. **Chạy web giám sát:**
   ```bash
   python3 API_monitering.py
   ```
5. **Mở trình duyệt truy cập:**\
   [http://localhost:5000](http://localhost:5000)

Bạn có thể quan sát trạng thái, số client, hiệu suất mạng, sự kiện roaming và phát hiện AP lỗi trực quan trên giao diện web.

---

## 4. Liên hệ - Đóng góp

- Mọi góp ý hoặc câu hỏi, vui lòng liên hệ Lê Gia Hoàng Thiện.
- Xin cảm ơn thầy/cô và các bạn đã quan tâm, đánh giá hệ thống!

