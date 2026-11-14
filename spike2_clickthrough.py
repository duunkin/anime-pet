"""
spike2_clickthrough.py
----------------------
Thử nghiệm kỹ thuật (Spike 2) cho ứng dụng Desktop Pet:
- Vùng trống của overlay: click xuyên qua (click-through) xuống cửa sổ bên dưới.
- Khi con trỏ chuột nằm trên nhân vật: overlay chặn click-through, bắt sự kiện click.
- In ra console "Đã click nhân vật" khi click trúng, đồng thời đổi màu highlight và in log
  khi con trỏ đi vào / đi ra khỏi vùng nhân vật.
- Sử dụng ctypes gọi Win32 API SetWindowLongW bật/tắt cờ WS_EX_TRANSPARENT kết hợp
  với QTimer (~30ms) đọc GetCursorPos.
- Xử lý chính xác màn hình có DPI Scaling khác 100% (High-DPI).
- Giữ nguyên phím tắt Esc / Ctrl+Q để thoát chương trình, hỗ trợ bắt phím toàn cục
  khi cửa sổ mất focus do click-through.

================================================================================
TẠI SAO CÁCH LÀM NÀY HOẠT ĐỘNG?
================================================================================
1. Cờ WS_EX_TRANSPARENT trên Windows:
   - Khi một cửa sổ có extended style `WS_EX_TRANSPARENT` (đi kèm `WS_EX_LAYERED`),
     hệ điều hành Windows (DWM và subsystem User32) sẽ bỏ qua cửa sổ này trong quá trình
     hit-testing chuột (kiểm tra thông điệp WM_NCHITTEST).
   - Toàn bộ thao tác chuột (click, cuộn chuột, kéo thả) tại vị trí đó sẽ được chuyển
     thẳng (xuyên qua) xuống cửa sổ nằm ngay bên dưới trong Z-order.
   - Lưu ý: Cờ WS_EX_TRANSPARENT KHÔNG làm cửa sổ biến mất về mặt thị giác, nó chỉ làm
     cửa sổ "vô hình" đối với các sự kiện chuột (input transparent).

2. Kỹ thuật Dynamic Hit-Testing (Bật/Tắt cờ động):
   - Một QTimer (~30ms) liên tục lấy tọa độ con trỏ chuột toàn màn hình qua `GetCursorPos`.
   - Chương trình kiểm tra xem tọa độ này có nằm trong vùng bao (hitbox) của model Live2D hay không.
   - NẰM TRONG: Gọi `SetWindowLongW` GỠ bỏ `WS_EX_TRANSPARENT` -> Cửa sổ nhận được sự kiện chuột
     bình thường (mousePressEvent), cho phép click, kéo hoặc tương tác với pet.
   - NẰM NGOÀI: Gọi `SetWindowLongW` BẬT lại `WS_EX_TRANSPARENT` -> Chuột xuyên qua desktop.

================================================================================
HẠN CHẾ CỦA PHƯƠNG PHÁP NÀY:
================================================================================
1. Độ trễ (Polling Latency):
   - Chu kỳ timer 30ms tạo ra độ trễ trung bình ~15ms - 30ms từ khi con trỏ lướt vào nhân vật
     cho đến khi Windows cập nhật xong cờ `WS_EX_TRANSPARENT`.
   - Nếu người dùng di chuột cực nhanh và click ngay lập tức vào nhân vật trong khoảng <30ms,
     cú click đó có thể bị lọt xuống cửa sổ bên dưới do cờ chưa kịp chuyển trạng thái.

2. Nhấp nháy / Giật lag con trỏ (Cursor Hitching / Boundary Flicker):
   - Mỗi lần gọi `SetWindowLongW` và `SetWindowPos(SWP_FRAMECHANGED)`, Windows phải tái cấu trúc
     bộ đệm layer của cửa sổ.
   - Nếu con trỏ chuột dừng hoặc rung lắc ngay tại ranh giới mép viền của nhân vật, việc chuyển đổi
     cờ liên tục hàng chục lần mỗi giây có thể khiến con trỏ chuột bị nhấp nháy hoặc gây giật micro-stutter.
   - *Cách khắc phục trong code:* Dùng biến cờ trạng thái `self.is_hovered` để CHỈ gọi Win32 API
     khi có sự thay đổi trạng thái (State Transition: In -> Out hoặc Out -> In).

================================================================================
XỬ LÝ DPI SCALING KHÁC 100% (HIGH-DPI / PER-MONITOR DPI):
================================================================================
- Windows 10/11 thường mặc định scale màn hình ở mức 125%, 150%, 175% hoặc 200% (máy hiện tại là 125%).
- Hàm Win32 `GetCursorPos(&pt)` trả về tọa độ theo PIXEL VẬT LÝ (Physical Pixels), ví dụ: 0..1920, 0..1080.
- Trong khi đó, hệ tọa độ widget của Qt (PySide6) làm việc theo PIXEL LOGIC (Logical Pixels / DIPs),
  ví dụ: màn hình 1920x1080 ở scale 125% thì kích thước logical chỉ là 1536x864.
- Tỉ lệ quy đổi: `devicePixelRatio = Physical_Pixels / Logical_Pixels` (ở đây là 1.25).
- Trong bài toán này, hitbox của model Live2D được tính toán và ánh xạ sang cùng một không gian
  tọa độ (Physical Pixels) trước khi so sánh với kết quả từ `GetCursorPos`, đảm bảo độ chính xác
  tuyệt đối trên mọi mức DPI Scaling mà không bị lệch hitbox.
"""

import os
import sys
import ctypes
from typing import Optional, Tuple

from PySide6.QtCore import Qt, QTimer, Slot, QPointF
from PySide6.QtGui import (
    QSurfaceFormat,
    QKeySequence,
    QShortcut,
    QCloseEvent,
    QKeyEvent,
    QMouseEvent,
)
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from OpenGL import GL

import live2d

# ==============================================================================
# HẰNG SỐ CẤU HÌNH (CONFIGURATION CONSTANTS)
# ==============================================================================
MODEL_PATH: str = "characters/hiyori/hiyori.model3.json"

TARGET_FPS: int = 60
FRAME_INTERVAL_MS: int = int(1000 / TARGET_FPS)

# Chu kỳ kiểm tra vị trí con trỏ chuột (~30ms tương đương ~33Hz)
CURSOR_POLL_INTERVAL_MS: int = 30

# Cấu hình đặt vị trí & kích thước model (góc dưới bên phải)
MODEL_SCALE: float = 0.65
MODEL_OFFSET_X: float = 0.65
MODEL_OFFSET_Y: float = -0.35

MOTION_GROUP_IDLE: str = "Idle"
MOTION_GROUP_TAP: str = "TapBody"

# Cơ chế an toàn (fallback): Tự thoát sau N giây
AUTO_EXIT_SECONDS: int = 60

# ==============================================================================
# WIN32 API CONSTANTS & STRUCTURES
# ==============================================================================
GWL_EXSTYLE: int = -20
WS_EX_LAYERED: int = 0x00080000
WS_EX_TRANSPARENT: int = 0x00000020

SWP_NOSIZE: int = 0x0001
SWP_NOMOVE: int = 0x0002
SWP_NOZORDER: int = 0x0004
SWP_FRAMECHANGED: int = 0x0020
SWP_FLAGS: int = SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED

VK_ESCAPE: int = 0x1B
VK_CONTROL: int = 0x11
VK_Q: int = ord('Q')


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MARGINS(ctypes.Structure):
    _fields_ = [
        ("cxLeftWidth", ctypes.c_int),
        ("cxRightWidth", ctypes.c_int),
        ("cyTopHeight", ctypes.c_int),
        ("cyBottomHeight", ctypes.c_int),
    ]


# ==============================================================================
# CÁC HÀM TIỆN ÍCH WINDOWS & FILE PATH
# ==============================================================================
def apply_windows_transparency(window_handle: int) -> bool:
    """Kích hoạt DWM transparency trên Windows 10/11."""
    if sys.platform != "win32":
        return False
    try:
        margins = MARGINS(-1, -1, -1, -1)
        res = ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(window_handle, ctypes.byref(margins))
        return res == 0
    except Exception as exc:
        print(f"[Windows DWM] Lỗi: {exc}")
        return False


def set_clickthrough(window_handle: int, clickthrough: bool) -> None:
    """
    Bật hoặc tắt tính năng click xuyên qua (click-through) cho cửa sổ.
    
    - clickthrough = True: Bật WS_EX_TRANSPARENT -> Click xuyên qua xuống dưới.
    - clickthrough = False: Gỡ bỏ WS_EX_TRANSPARENT -> Cửa sổ bắt sự kiện chuột.
    """
    if sys.platform != "win32":
        return

    user32 = ctypes.windll.user32
    current_style = user32.GetWindowLongW(window_handle, GWL_EXSTYLE)

    if clickthrough:
        new_style = current_style | WS_EX_LAYERED | WS_EX_TRANSPARENT
    else:
        new_style = (current_style | WS_EX_LAYERED) & ~WS_EX_TRANSPARENT

    if new_style != current_style:
        user32.SetWindowLongW(window_handle, GWL_EXSTYLE, new_style)
        user32.SetWindowPos(window_handle, 0, 0, 0, 0, 0, SWP_FLAGS)


def resolve_model_path(path_str: str) -> str:
    """Chuẩn hóa đường dẫn file model3.json."""
    abs_path = os.path.abspath(path_str)
    if os.path.exists(abs_path):
        return abs_path

    directory = os.path.dirname(abs_path)
    target_name = os.path.basename(abs_path).lower()
    if os.path.isdir(directory):
        for filename in os.listdir(directory):
            if filename.lower() == target_name:
                return os.path.join(directory, filename)

    return abs_path


# ==============================================================================
# CLASS CHÍNH: LIVE2D OVERLAY CÓ CLICK-THROUGH
# ==============================================================================
class Live2DClickthroughOverlay(QOpenGLWidget):
    """
    Cửa sổ Live2D Overlay hỗ trợ Click-through thông minh:
    - Vùng trống: Click xuyên qua.
    - Vùng nhân vật: Bắt click, đổi màu khi hover, phản ứng khi bấm chuột.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.model: Optional[live2d.Model] = None
        self.is_closing: bool = False

        # Trạng thái con trỏ hiện tại đang hover trên nhân vật hay không
        self.is_hovered: bool = False

        # Lưu bounding box của model trong không gian model space
        self.model_bounds: Optional[Tuple[float, float, float, float]] = None

        # 1. Cấu hình cờ cửa sổ và thuộc tính trong suốt
        self._setup_window_flags()

        # 2. Cấu hình phím tắt thoát
        self._setup_shortcuts()

        # 3. Timer vẽ khung hình (~60 FPS)
        self.render_timer = QTimer(self)
        self.render_timer.setInterval(FRAME_INTERVAL_MS)
        self.render_timer.timeout.connect(self.on_timer_tick)

        # 4. Timer kiểm tra vị trí con trỏ chuột (~30ms)
        self.cursor_timer = QTimer(self)
        self.cursor_timer.setInterval(CURSOR_POLL_INTERVAL_MS)
        self.cursor_timer.timeout.connect(self.poll_cursor_position)

        # 5. Timer tự thoát an toàn (fallback)
        self.fallback_timer: Optional[QTimer] = None
        if AUTO_EXIT_SECONDS > 0:
            self.fallback_timer = QTimer(self)
            self.fallback_timer.setSingleShot(True)
            self.fallback_timer.timeout.connect(self.on_fallback_timeout)

    # --------------------------------------------------------------------------
    # KHỞI TẠO CỬA SỔ & PHÍM TẮT
    # --------------------------------------------------------------------------
    def _setup_window_flags(self) -> None:
        """Thiết lập cửa sổ không viền, trong suốt và luôn trên cùng."""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _setup_shortcuts(self) -> None:
        """Đăng ký phím tắt Esc và Ctrl+Q."""
        self.shortcut_esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.shortcut_esc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_esc.activated.connect(lambda: self.exit_application("Phím Esc (Shortcut)"))

        self.shortcut_ctrl_q = QShortcut(QKeySequence("Ctrl+Q"), self)
        self.shortcut_ctrl_q.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_ctrl_q.activated.connect(lambda: self.exit_application("Phím Ctrl+Q (Shortcut)"))

    def showEvent(self, event) -> None:
        """Khi cửa sổ xuất hiện: Bật DWM, bật chế độ click-through ban đầu."""
        super().showEvent(event)

        hwnd = int(self.winId())
        apply_windows_transparency(hwnd)

        # Ban đầu: Bật chế độ click-through vì con trỏ có thể chưa nằm trên model
        set_clickthrough(hwnd, True)

        self.setFocus()
        self.activateWindow()

        # Khởi động các timer
        if not self.render_timer.isActive():
            self.render_timer.start()
        if not self.cursor_timer.isActive():
            self.cursor_timer.start()
        if self.fallback_timer is not None and not self.fallback_timer.isActive():
            print(f"[An toàn] Tự động thoát sau {AUTO_EXIT_SECONDS}s (bấm Esc hoặc Ctrl+Q để thoát).")
            self.fallback_timer.start(AUTO_EXIT_SECONDS * 1000)

    # --------------------------------------------------------------------------
    # OPENGL VÀ LIVE2D RENDERING
    # --------------------------------------------------------------------------
    def initializeGL(self) -> None:
        """Khởi tạo Live2D và nạp model."""
        print("[OpenGL] Đang khởi tạo OpenGL Context...")
        live2d.glInit()

        target_path = resolve_model_path(MODEL_PATH)
        print(f"[Live2D] Đường dẫn model: {target_path}")

        if not os.path.exists(target_path):
            print(f"[LỖI] Không tìm thấy model: {target_path}")
            QMessageBox.critical(self, "Lỗi", f"Không tìm thấy model:\n{target_path}")
            self.exit_application("Model không tồn tại")
            return

        try:
            self.model = live2d.Model()
            self.model.LoadModelJson(target_path, create_renderer=True)
            print("[Live2D] Nạp model thành công!")

            # Tính toán Bounding Box của nhân vật trong không gian model space
            self._compute_model_bounds()

            # Bật motion idle và các hiệu ứng tự động
            self.model.StartRandomMotion(MOTION_GROUP_IDLE, 1)
            self.model.SetAutoBlink(True)
            self.model.SetAutoBreath(True)

        except Exception as e:
            print(f"[LỖI] Ngoại lệ khi nạp Live2D: {e}")
            self.exit_application("Lỗi nạp model")

    def _compute_model_bounds(self) -> None:
        """
        Duyệt qua các đỉnh của các bộ phận drawable để xác định khung hình chữ nhật
        bao quanh toàn bộ nhân vật (Model Space Coordinates).
        """
        if self.model is None:
            return

        self.model.Update()
        min_x, max_x = float('inf'), float('-inf')
        min_y, max_y = float('inf'), float('-inf')

        drawable_count = len(self.model.GetDrawableIds())
        for i in range(drawable_count):
            verts = self.model.GetDrawableVertices(i)
            for j in range(0, len(verts), 2):
                vx, vy = verts[j], verts[j + 1]
                if vx < min_x: min_x = vx
                if vx > max_x: max_x = vx
                if vy < min_y: min_y = vy
                if vy > max_y: max_y = vy

        # Thêm một chút biên đệm an toàn (padding 5%) cho tóc/váy chuyển động
        pad_x = (max_x - min_x) * 0.05
        pad_y = (max_y - min_y) * 0.05
        self.model_bounds = (min_x - pad_x, min_y - pad_y, max_x + pad_x, max_y + pad_y)
        print(f"[Live2D] Model bounds: X=[{self.model_bounds[0]:.2f}, {self.model_bounds[2]:.2f}], "
              f"Y=[{self.model_bounds[1]:.2f}, {self.model_bounds[3]:.2f}]")

    def resizeGL(self, width: int, height: int) -> None:
        """Đồng bộ kích thước viewport OpenGL."""
        GL.glViewport(0, 0, width, height)
        if self.model is not None:
            self.model.Resize(width, height)
            self.model.SetScale(MODEL_SCALE)
            self.model.SetOffset(MODEL_OFFSET_X, MODEL_OFFSET_Y)

    def paintGL(self) -> None:
        """Vẽ khung hình (~60 FPS) với nền trong suốt."""
        live2d.clearBuffer(0.0, 0.0, 0.0, 0.0)

        if self.model is not None:
            if self.model.IsMotionFinished():
                self.model.StartRandomMotion(MOTION_GROUP_IDLE, 1)

            self.model.Update()
            self.model.Draw()

    @Slot()
    def on_timer_tick(self) -> None:
        """Kích hoạt vẽ lại frame mới."""
        if not self.is_closing:
            self.update()

    # --------------------------------------------------------------------------
    # KHỐI HIT-TESTING & BẬT/TẮT CLICK-THROUGH DỰA TRÊN GETCURSORPOS
    # --------------------------------------------------------------------------
    def get_character_screen_box_physical(self) -> Optional[Tuple[float, float, float, float]]:
        """
        Quy đổi Bounding Box của nhân vật sang tọa độ MÀN HÌNH VẬT LÝ (Physical Pixels).
        
        Quy trình chuyển đổi:
        Model Space -> [Nhân Ma trận MVP] -> Normalized Device Coordinates (NDC) [-1, 1]
                    -> [Quy đổi Viewport]  -> Physical Screen Pixels
        """
        if self.model is None or self.model_bounds is None:
            return None

        min_xm, min_ym, max_xm, max_ym = self.model_bounds
        mvp = self.model.GetMvp()

        # Ma trận biến đổi cột (Column-major MVP matrix)
        # x_ndc = x_model * MVP[0] + MVP[12]
        # y_ndc = y_model * MVP[5] + MVP[13]
        ndc_x1 = min_xm * mvp[0] + mvp[12]
        ndc_x2 = max_xm * mvp[0] + mvp[12]
        ndc_y1 = min_ym * mvp[5] + mvp[13]
        ndc_y2 = max_ym * mvp[5] + mvp[13]

        # Kích thước màn hình vật lý (Physical Pixels)
        dpr = self.devicePixelRatio()
        phys_w = self.width() * dpr
        phys_h = self.height() * dpr

        # Đổi từ NDC [-1, 1] sang Physical Pixels [0, phys_w] x [0, phys_h]
        # Trục Y của OpenGL hướng lên, còn trục Y màn hình Windows hướng xuống
        screen_x1 = (ndc_x1 + 1.0) / 2.0 * phys_w
        screen_x2 = (ndc_x2 + 1.0) / 2.0 * phys_w
        screen_y1 = (1.0 - ndc_y2) / 2.0 * phys_h
        screen_y2 = (1.0 - ndc_y1) / 2.0 * phys_h

        return (min(screen_x1, screen_x2), min(screen_y1, screen_y2),
                max(screen_x1, screen_x2), max(screen_y1, screen_y2))

    def is_cursor_over_character(self, cursor_phys_x: int, cursor_phys_y: int) -> bool:
        """
        Kiểm tra xem con trỏ chuột (ở tọa độ Physical Pixels) có nằm trên nhân vật hay không.
        
        Để bám sát hình dáng nhân vật thật hơn hình chữ nhật thô:
        Chia cơ thể nhân vật thành 2 phân đoạn theo chiều dọc:
        1. Vùng Đầu/Tóc (nửa trên): Chiều ngang thon gọn hơn (~75% bề rộng).
        2. Vùng Thân/Váy/Chân (nửa dưới): Chiều ngang phình rộng đầy đủ (100% bề rộng).
        """
        box = self.get_character_screen_box_physical()
        if box is None:
            return False

        x1, y1, x2, y2 = box
        # 1. Kiểm tra nhanh Bounding Box tổng quát (Fast Rejection)
        if not (x1 <= cursor_phys_x <= x2 and y1 <= cursor_phys_y <= y2):
            return False

        # 2. Kiểm tra theo hình dạng cơ thể thực tế (Shaped Hit-Testing)
        mid_y = y1 + (y2 - y1) * 0.40  # 40% trên là đầu/cổ
        center_x = (x1 + x2) / 2.0
        width = x2 - x1

        if cursor_phys_y < mid_y:
            # Vùng đầu: thu hẹp mép trái/phải để tránh khoảng trống cạnh đầu
            head_half_width = (width * 0.70) / 2.0
            return (center_x - head_half_width) <= cursor_phys_x <= (center_x + head_half_width)
        else:
            # Vùng thân và váy: giữ nguyên toàn bộ chiều rộng
            return True

    def set_hover_visual_feedback(self, active: bool) -> None:
        """
        Đổi màu highlight nhân vật khi con trỏ đi vào / đi ra.
        
        Sử dụng SetPartScreenColor:
        - active = True: Thêm sắc sáng lam nhạt (Screen Color RGB = 0.15, 0.15, 0.25)
        - active = False: Khôi phục màu gốc (Screen Color RGB = 0.0, 0.0, 0.0)
        """
        if self.model is None:
            return

        part_count = self.model.GetPartCount()
        r, g, b = (0.15, 0.15, 0.25) if active else (0.0, 0.0, 0.0)
        for i in range(part_count):
            self.model.SetPartScreenColor(i, r, g, b, 1.0)

    @Slot()
    def poll_cursor_position(self) -> None:
        """
        Hàm định kỳ ~30ms:
        1. Đọc GetCursorPos (tọa độ vật lý trên Windows).
        2. Hit-testing với vùng nhân vật.
        3. Thay đổi cờ WS_EX_TRANSPARENT chỉ khi trạng thái thay đổi (tránh nhấp nháy).
        4. Kiểm tra phím tắt toàn cục qua GetAsyncKeyState (khi overlay mất focus).
        """
        if self.is_closing or sys.platform != "win32":
            return

        user32 = ctypes.windll.user32

        # --- A. KIỂM TRA PHÍM THOÁT TOÀN CỤC (GLOBAL ESC / CTRL+Q) ---
        # Khi cửa sổ ở chế độ click-through, người dùng click vào app khác sẽ làm
        # overlay mất focus bàn phím. GetAsyncKeyState đảm bảo Esc / Ctrl+Q luôn thoát được!
        esc_down = bool(user32.GetAsyncKeyState(VK_ESCAPE) & 0x8000)
        ctrl_down = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
        q_down = bool(user32.GetAsyncKeyState(VK_Q) & 0x8000)

        if esc_down:
            self.exit_application("Phím Esc (GetAsyncKeyState)")
            return
        if ctrl_down and q_down:
            self.exit_application("Phím Ctrl+Q (GetAsyncKeyState)")
            return

        # --- B. ĐỌC TỌA ĐỘ CON TRỎ CHUỘT VẬT LÝ ---
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))

        # --- C. KIỂM TRA CON TRỎ CÓ TRÊN NHÂN VẬT KHÔNG ---
        now_hovered = self.is_cursor_over_character(pt.x, pt.y)

        # --- D. CHỈ THAY ĐỔI KHI TRẠNG THÁI CHUYỂN ĐỔI (STATE TRANSITION) ---
        if now_hovered != self.is_hovered:
            self.is_hovered = now_hovered
            hwnd = int(self.winId())

            if self.is_hovered:
                # Con trỏ ĐI VÀO nhân vật -> BẮT CLICK (Tắt WS_EX_TRANSPARENT)
                set_clickthrough(hwnd, False)
                self.set_hover_visual_feedback(True)
                print(f"[Hover] Con trỏ ĐI VÀO nhân vật tại ({pt.x}, {pt.y}) "
                      f"-> Đổi màu Highlight & Tắt WS_EX_TRANSPARENT (Bắt click)")
            else:
                # Con trỏ ĐI RA khỏi nhân vật -> CLICK XUYÊN QUA (Bật WS_EX_TRANSPARENT)
                set_clickthrough(hwnd, True)
                self.set_hover_visual_feedback(False)
                print(f"[Hover] Con trỏ ĐI RA khỏi nhân vật tại ({pt.x}, {pt.y}) "
                      f"-> Khôi phục màu gốc & Bật WS_EX_TRANSPARENT (Click xuyên qua)")

    # --------------------------------------------------------------------------
    # XỬ LÝ SỰ KIỆN CLICK CHUỘT VÀ BÀN PHÍM
    # --------------------------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        """
        Được gọi khi người dùng bấm chuột VÀ con trỏ đang ở trên nhân vật
        (do WS_EX_TRANSPARENT đã được gỡ bỏ lúc hover).
        """
        if event.button() == Qt.MouseButton.LeftButton:
            print("Đã click nhân vật")

            # Kích hoạt motion phản ứng (TapBody) nếu có
            if self.model is not None:
                try:
                    self.model.StartMotion(MOTION_GROUP_TAP, 0, 3)
                except Exception:
                    self.model.StartRandomMotion(MOTION_GROUP_IDLE, 3)

        super().mousePressEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Bắt sự kiện phím khi cửa sổ có focus."""
        if event.key() == Qt.Key.Key_Escape:
            self.exit_application("Phím Esc (keyPressEvent)")
            event.accept()
        elif event.key() == Qt.Key.Key_Q and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.exit_application("Phím Ctrl+Q (keyPressEvent)")
            event.accept()
        else:
            super().keyPressEvent(event)

    @Slot()
    def on_fallback_timeout(self) -> None:
        """Fallback an toàn sau N giây."""
        self.exit_application(f"Hết thời gian chờ {AUTO_EXIT_SECONDS}s (Fallback Auto-Exit)")

    def exit_application(self, reason: str = "") -> None:
        """Dọn dẹp và đóng ứng dụng an toàn."""
        if self.is_closing:
            return
        self.is_closing = True

        print(f"[Thoát] Yêu cầu thoát ứng dụng: {reason}")

        if self.render_timer.isActive():
            self.render_timer.stop()
        if self.cursor_timer.isActive():
            self.cursor_timer.stop()
        if self.fallback_timer is not None and self.fallback_timer.isActive():
            self.fallback_timer.stop()

        try:
            self.makeCurrent()
            if self.model is not None:
                self.model.DestroyRenderer()
                self.model = None
            live2d.glRelease()
            self.doneCurrent()
        except Exception as e:
            print(f"[Dọn dẹp] Ngoại lệ khi giải phóng OpenGL: {e}")

        self.close()
        QApplication.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.exit_application("CloseEvent")
        event.accept()


# ==============================================================================
# ENTRY POINT
# ==============================================================================
def main() -> None:
    print("=================================================================")
    print(" LIVE2D PET OVERLAY - SPIKE 2: CLICK-THROUGH & HIT-TESTING")
    print(" - Vùng trống: Click xuyên qua màn hình desktop bên dưới.")
    print(" - Vùng nhân vật: Bắt click, in 'Đã click nhân vật', đổi màu hover.")
    print(" - Thoát chương trình: Nhấn [Esc] hoặc [Ctrl+Q] bất cứ lúc nào.")
    print("=================================================================")

    surface_format = QSurfaceFormat()
    surface_format.setAlphaBufferSize(8)
    surface_format.setDepthBufferSize(24)
    surface_format.setStencilBufferSize(8)
    surface_format.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
    surface_format.setSwapInterval(1)
    QSurfaceFormat.setDefaultFormat(surface_format)

    app = QApplication(sys.argv)
    live2d.init()

    screen = app.primaryScreen()
    screen_geometry = screen.geometry()
    dpr = screen.devicePixelRatio()
    print(f"[Màn hình] Kích thước logic: {screen_geometry.width()}x{screen_geometry.height()}, "
          f"DPI Scale: {dpr * 100:.0f}% (Kích thước vật lý: {int(screen_geometry.width()*dpr)}x{int(screen_geometry.height()*dpr)})")

    overlay = Live2DClickthroughOverlay()
    overlay.setGeometry(screen_geometry)
    overlay.show()

    exit_code = app.exec()

    try:
        live2d.dispose()
        print("[Live2D] Đã giải phóng Live2D thành công.")
    except Exception as e:
        print(f"[Live2D] Ngoại lệ: {e}")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
