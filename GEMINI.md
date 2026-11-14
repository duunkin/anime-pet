
# GEMINI.md: Anime Desktop Pet (đọc file này TRƯỚC, đừng quét cả repo)

> Mục đích: cho agent (Gemini / Antigravity) đủ ngữ cảnh để làm việc ngay, không phải đọc lại toàn bộ code mỗi chat mới.
> Repo: https://github.com/duunkin/anime-pet.git

## 0. Quy tắc làm việc (QUAN TRỌNG, tiết kiệm token)

1. **Không đọc toàn bộ repo.** Dựa vào mục 3 (bản đồ file) để chỉ mở đúng file cần sửa.
2. **Không đọc lại** thư mục `models/`, `assets/`, `build/`, `dist/`, `.venv/`, `__pycache__/`, file `.moc3`, `.png`, `.json` của model Live2D.
3. **Chỉ trả về phần thay đổi**: nếu sửa < 30% file thì đưa đoạn code cần thay (ghi rõ file + hàm), không in lại cả file. Chỉ in cả file khi tạo file mới hoặc sửa lớn.
4. **Không giải thích dài.** Tối đa 3-5 dòng: đã đổi gì, vì sao, cách test.
5. **Một task mỗi lần.** Làm đúng phạm vi được yêu cầu, không tự refactor các file không liên quan.
6. **Hỏi lại tối đa 1 câu** nếu yêu cầu mơ hồ; nếu có thể đoán hợp lý thì cứ làm và ghi rõ giả định.
7. Khi xong task, **cập nhật mục 6 (Trạng thái)** của file này (1-2 dòng) để chat sau không phải đoán lại.
8. Trả lời bằng **tiếng Việt**; tên biến, hàm, comment code dùng tiếng Anh.

## 1. Dự án là gì

App Python hiển thị một hoặc nhiều nhân vật anime (Live2D) đi lại trên màn hình laptop như pet game, phản ứng khi chuột di chuyển / click.

- Ngôn ngữ: **Python**
- GUI/render: **PySide6** (cửa sổ overlay trong suốt, toàn màn hình)
- Đồ họa nhân vật: **Live2D**
- IDE: PyCharm
- OS đích: **Windows và Linux** (không dùng API chỉ có trên 1 OS mà không bọc lớp trừu tượng)
- Người dùng: đã viết chương trình Python nhỏ, cần code rõ ràng, dễ đọc, có comment ở chỗ khó.

## 2. Yêu cầu đã chốt (không hỏi lại)

**Hiển thị & chuột**
- Overlay toàn màn hình, nhân vật đi được trên mọi cửa sổ khác.
- Click xuyên qua vùng trong suốt; chỉ bắt chuột khi trúng nhân vật.
- Multi-monitor: hiện trên mọi màn hình, nhân vật đi qua lại giữa các màn hình.
- Ẩn nhân vật khi người dùng đang chơi game hoặc trình chiếu (fullscreen app).
- Tự giảm FPS khi nhân vật idle / đang ngủ.

**Chuyển động & hành vi**
- Leo trèo, nhảy, bám mép cửa sổ như pet game; đứng trên thanh tiêu đề các cửa sổ đang mở và bám/leo mép cửa sổ.
- Idle: xoay vòng ngẫu nhiên chớp mắt, ngủ gật, hành động ngẫu nhiên (vươn vai, nhảy múa, đọc sách...).
- Chuột lại gần: mắt nhìn theo con trỏ.
- Click trái vào nhân vật: giật mình / đổi biểu cảm đơn giản.
- Giữ chuột trái: nhấc nhân vật lên, thả ra thì rơi (trọng lực).
- Click phải: mở menu hành động (ngủ, nhảy, hát...).
- Không cần: double click, bong bóng thoại, âm thanh/giọng nói.

**Hệ thống & nhận biết**
- Phản ứng biểu cảm khi CPU/RAM quá tải.
- Nhận biết app đang active và tiêu đề cửa sổ (ví dụ đang xem YouTube) để đổi hành vi.
- Bàn phím: gõ lâu thì cổ vũ/nhìn, không hoạt động lâu thì ngủ.
- Nhiều nhân vật tương tác đơn giản (chào, rượt, ngồi cạnh nhau).
- Có cả hệ thống độ thân thiết (affection) và tâm trạng (mood).

**Chat AI & nhắc nhở**
- Chat với nhân vật qua AI chạy local, offline hoàn toàn, model nhẹ 1-3B tham số chạy mượt trên CPU.
- UI chat: khung nhỏ nổi cạnh nhân vật, mở bằng phím tắt.
- Tính cách: người dùng tự viết mô tả cho từng nhân vật.
- Nhắc nghỉ ngơi / uống nước theo chu kỳ và nhắc lịch học / deadline do người dùng đặt; hiện bằng icon nhỏ trên đầu nhân vật.

**Quản lý app**
- System tray: bật/tắt nhân vật, cài đặt, thoát.
- Tự khởi động cùng OS, xuất hiện sau khi đăng nhập xong một lúc.
- Thêm/xóa nhân vật ngay trong app; app tự quét một thư mục cố định để nhận nhân vật mới.
- Cần bảng ánh xạ (mapping) giữa motion/expression của model Live2D và hành vi của app (sleep, startled...).
- Lưu: danh sách nhân vật, cài đặt, vị trí, mood, affection. **Không** lưu lịch sử chat AI.
- Đóng gói: Windows (.exe) và Linux (AppImage/build).

## 3. Bản đồ file (cập nhật khi thêm file mới)

| File | Vai trò |
|---|---|
| `main.py` | Điểm vào, khởi tạo QApplication, nối các thành phần |
| `overlay.py` | Cửa sổ overlay trong suốt toàn màn hình, xử lý click-through |
| `physics.py` | Trọng lực, rơi, va chạm, nhảy, bám mép |
| `state_machine.py` | Máy trạng thái hành vi (idle, walk, sleep, dragged, startled...) |
| `live2d_view.py` | Tải và render model Live2D, phát motion/expression |

> Cấu trúc module dự kiến cho các phase sau (chưa có, tạo khi cần, đừng tạo trước): window tracking, tray, settings/persistence, AI chat, reminders, system monitor. TODO(user): bổ sung đường dẫn thực tế khi các file này xuất hiện.

## 4. Quy ước code

- Python 3.x, type hints cho hàm công khai, docstring ngắn.
- Tách logic khỏi UI: `physics.py` và `state_machine.py` **không import PySide6** để test được độc lập.
- Mọi phần phụ thuộc OS (lấy danh sách cửa sổ, phát hiện fullscreen, autostart) đặt sau một interface chung, có implementation riêng cho Windows và Linux.
- Không hard-code đường dẫn; dùng `pathlib` và một hằng số thư mục model/config.
- Không thêm thư viện mới nếu chưa cần; nếu cần, nêu tên + lý do và cập nhật `requirements.txt`.
- Vòng lặp chính phải nhẹ: tránh tạo đối tượng mới mỗi frame, tránh gọi API hệ thống nặng mỗi frame (cache, giảm tần suất).
- Bắt lỗi ở biên (tải model, đọc config) và log rõ ràng, không để app crash im lặng.

## 5. Lộ trình (phase)

- **Phase 0**: spike kỹ thuật (overlay + Live2D, click-through, vị trí cửa sổ). **Xong**, chạy không lỗi.
- **Phase 1**: nhân vật cơ bản (main/overlay/physics/state_machine/live2d_view). **Đang chạy**, còn lag nhẹ.
- **Các phase sau** (theo roadmap Graphify): tương tác chuột đầy đủ, nhận biết cửa sổ, idle/mood/affection, tray + lưu cấu hình, chat AI local, nhắc nhở, multi-monitor, đóng gói. TODO(user): dán roadmap chi tiết từ Graphify vào đây khi có.

## 6. Trạng thái hiện tại (agent cập nhật mục này sau mỗi task)

- Phase 1 chạy được. Vấn đề đã biết: **nhân vật hơi lag**.
- Gợi ý hướng kiểm tra lag (chưa xác nhận nguyên nhân): tần suất timer/vòng lặp cập nhật, chi phí render Live2D mỗi frame, việc repaint toàn màn hình của overlay thay vì vùng nhỏ quanh nhân vật.
- Việc tiếp theo: giảm lag Phase 1 rồi sang Phase 2.

## 7. Cách báo lỗi / chạy thử

- Chạy: `python main.py` (từ thư mục gốc repo, trong venv).
- Khi gặp lỗi, người dùng sẽ dán traceback; chỉ sửa đúng chỗ gây lỗi.
- Nếu cần đo hiệu năng, đề xuất đoạn đo FPS / thời gian mỗi frame ngắn gọn thay vì viết lại kiến trúc.

## 8. Việc KHÔNG được làm

- Không đổi framework (PySide6, Live2D) hay ngôn ngữ nếu không được yêu cầu.
- Không xóa/ghi đè model Live2D hoặc file cấu hình của người dùng.
- Không đẩy code lên GitHub hay chạy lệnh phá hủy (`rm -rf`, `git reset --hard`, `git push --force`) khi chưa được xác nhận.
- Không thêm tính năng đã chốt là "không cần" (âm thanh, bong bóng thoại, double click).