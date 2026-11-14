"""
src/render/overlay.py
---------------------
Cửa sổ hiển thị Live2D Pet Overlay kích thước nhỏ gọn (QOpenGLWidget):
- TÁI CẤU TRÚC HIỆU NĂNG: Cửa sổ chỉ có kích thước vừa khít nhân vật + lề 40px mỗi phía
  (thay vì phủ toàn màn hình gây lag/nặng GPU như trước).
- Di chuyển cửa sổ bằng self.move() theo tọa độ pixel màn hình từ PetPhysics mỗi frame.
- PetPhysics hoàn toàn làm việc với hệ tọa độ màn hình (Logical Pixels); việc quy đổi sang
  tọa độ cục bộ chỉ nằm trong lớp overlay/render này.
- Giữ nguyên toàn bộ tương tác:
  + Mắt nhìn theo con trỏ chuột (làm mượt độc lập FPS theo dt trong paintGL, cập nhật mục tiêu trong poll_cursor).
  + Click chuột trái = giật mình (STARTLED).
  + Giữ chuột trái & kéo = nhấc nhân vật lên; thả ra = rơi tự do xuống sàn.
  + Click phải = QMenu (Ngủ, Nhảy, Thoát).
  + Hit-testing theo hình thể cơ thể (Shaped Hit-Testing).
  + Click xuyên thấu (WS_EX_TRANSPARENT) cho toàn bộ vùng trống (kể cả viền lề 40px).
- Hỗ trợ đầy đủ Per-Monitor DPI Awareness v2, ghi chú rõ ràng mọi vị trí quy đổi Logical / Physical Pixels.
"""

import sys
import time
import ctypes
from typing import Optional, Tuple

from PySide6.QtCore import Qt, QTimer, Slot, QPoint
from PySide6.QtGui import (
    QKeySequence,
    QShortcut,
    QCloseEvent,
    QKeyEvent,
    QMouseEvent,
    QAction,
)
from PySide6.QtWidgets import QApplication, QMenu
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from src.config.settings import AppSettings
from src.core.physics import PetPhysics
from src.behavior.state_machine import PetStateMachine
from src.render.live2d_view import Live2DView


# ==============================================================================
# WIN32 API STRUCTURES & CONSTANTS
# ==============================================================================
GWL_EXSTYLE: int = -20
WS_EX_LAYERED: int = 0x00080000
WS_EX_TRANSPARENT: int = 0x00000020

SWP_NOSIZE: int = 0x0001
SWP_NOMOVE: int = 0x0002
SWP_NOZORDER: int = 0x0004
SWP_FRAMECHANGED: int = 0x0020
SWP_FLAGS: int = SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_FRAMECHANGED


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MARGINS(ctypes.Structure):
    _fields_ = [
        ("cxLeftWidth", ctypes.c_int),
        ("cxRightWidth", ctypes.c_int),
        ("cyTopHeight", ctypes.c_int),
        ("cyBottomHeight", ctypes.c_int),
    ]


def apply_windows_transparency(window_handle: int) -> bool:
    """Kích hoạt DWM transparency trên Windows để khử lỗi nền đen."""
    if sys.platform != "win32":
        return False
    try:
        margins = MARGINS(-1, -1, -1, -1)
        res = ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(window_handle, ctypes.byref(margins))
        return res == 0
    except Exception as exc:
        print(f"[Windows DWM] Lỗi gọi DwmExtendFrameIntoClientArea: {exc}")
        return False


def set_clickthrough(window_handle: int, clickthrough: bool) -> None:
    """
    Bật hoặc tắt cờ WS_EX_TRANSPARENT để hỗ trợ click xuyên thấu vùng trống.
    - clickthrough = True: Bật WS_EX_TRANSPARENT -> Click xuyên qua màn hình/app bên dưới.
    - clickthrough = False: Tắt WS_EX_TRANSPARENT -> Cửa sổ bắt sự kiện chuột trên nhân vật.
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


class Live2DPetOverlay(QOpenGLWidget):
    """
    Cửa sổ Overlay kích thước nhỏ phối hợp các hệ thống: Physics, Live2DView, StateMachine.
    """

    def __init__(self,
                 settings: AppSettings,
                 physics: PetPhysics,
                 state_machine: PetStateMachine,
                 live2d_view: Live2DView,
                 parent=None):
        super().__init__(parent)

        self.settings: AppSettings = settings
        self.physics: PetPhysics = physics
        self.state_machine: PetStateMachine = state_machine
        self.live2d_view: Live2DView = live2d_view

        # Lề 40px mỗi phía (Logical Pixels)
        self.margin_px: float = float(self.settings.window_margin_px)

        self.is_closing: bool = False
        self.is_hovered: bool = False

        # Quản lý kéo thả chuột (Logical Pixels màn hình)
        self._mouse_down: bool = False
        self._is_dragging: bool = False
        self._press_screen_pos: QPoint = QPoint()

        # Quản lý thời gian tính toán vật lý
        self._last_frame_time: float = time.perf_counter()

        # Cache bounding box vật lý của nhân vật (trong không gian Local Physical Pixels của cửa sổ)
        self._current_phys_box: Optional[Tuple[float, float, float, float]] = None

        # Lưu vị trí chuột lần poll trước để kiểm tra dịch chuyển > 3px (Physical Pixels)
        self._last_cursor_pos: Optional[Tuple[int, int]] = None

        # Bộ đo hiệu năng (Performance measurement)
        self._perf_frame_count: int = 0
        self._perf_total_paint_time: float = 0.0
        self._perf_last_report_time: float = time.perf_counter()

        # 1. Cấu hình cờ cửa sổ (Frameless, Always On Top, Translucent)
        self._setup_window_flags()

        # 2. Cấu hình phím tắt (Esc, Ctrl+Q) trong Qt
        self._setup_shortcuts()

        # 3. Kết nối callbacks của State Machine và Physics
        self._setup_behavior_bindings()

        # 4. Timer vẽ khung hình (sử dụng PreciseTimer, 60 FPS hoạt động / 30 FPS nhàn rỗi)
        self.render_timer = QTimer(self)
        self.render_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.render_timer.setInterval(int(1000 / self.settings.target_fps))
        self.render_timer.timeout.connect(self.on_render_tick)

        # 5. Timer kiểm tra vị trí con trỏ chuột (~30ms)
        self.cursor_timer = QTimer(self)
        self.cursor_timer.setInterval(self.settings.cursor_poll_interval_ms)
        self.cursor_timer.timeout.connect(self.poll_cursor)

        # 6. Timer an toàn (fallback) nếu có cấu hình
        self.fallback_timer: Optional[QTimer] = None
        if self.settings.auto_exit_seconds > 0:
            self.fallback_timer = QTimer(self)
            self.fallback_timer.setSingleShot(True)
            self.fallback_timer.timeout.connect(
                lambda: self.exit_application(f"Auto-exit sau {self.settings.auto_exit_seconds}s")
            )

    def _setup_window_flags(self) -> None:
        """Thiết lập cửa sổ không viền, trong suốt và luôn trên cùng."""
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.SubWindow
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    def _setup_shortcuts(self) -> None:
        """Đăng ký phím tắt Ctrl+Q và Esc an toàn trong Qt (không can thiệp toàn cục)."""
        self.shortcut_esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.shortcut_esc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_esc.activated.connect(lambda: self.exit_application("Phím Esc (Qt Shortcut)"))

        self.shortcut_ctrl_q = QShortcut(QKeySequence("Ctrl+Q"), self)
        self.shortcut_ctrl_q.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_ctrl_q.activated.connect(lambda: self.exit_application("Phím Ctrl+Q (Qt Shortcut)"))

    def _setup_behavior_bindings(self) -> None:
        """Kết nối các tín hiệu giữa State Machine, Physics và Live2D View."""
        # Khi state machine muốn phát một hành vi (motion / biểu cảm)
        self.state_machine.on_trigger_behavior = self.live2d_view.play_behavior

        # Khi state machine thay đổi chế độ FPS
        self.state_machine.on_fps_mode_changed = self._apply_fps_mode

        # Khi nhân vật rơi chạm đất -> báo state machine chuyển sang IDLE
        self.physics.on_ground_hit = self.state_machine.trigger_land

    def _apply_fps_mode(self, is_high: bool) -> None:
        """Điều chỉnh tần số quét của render timer giữa target_fps (60) và idle_fps (30)."""
        fps = self.settings.target_fps if is_high else self.settings.idle_fps
        interval_ms = max(10, int(1000 / fps))
        self.render_timer.setInterval(interval_ms)

    def showEvent(self, event) -> None:
        """Khi cửa sổ xuất hiện trên màn hình."""
        super().showEvent(event)

        hwnd = int(self.winId())
        apply_windows_transparency(hwnd)

        # Mặc định ban đầu bật click xuyên thấu
        set_clickthrough(hwnd, True)

        # Khởi động các bộ đếm thời gian
        if not self.render_timer.isActive():
            self.render_timer.start()
        if not self.cursor_timer.isActive():
            self.cursor_timer.start()
        if self.fallback_timer is not None and not self.fallback_timer.isActive():
            self.fallback_timer.start(int(self.settings.auto_exit_seconds * 1000))

    # --------------------------------------------------------------------------
    # ĐỒNG BỘ VỊ TRÍ CỬA SỔ VỚI TỌA ĐỘ MÀN HÌNH CỦA PETPHYSICS
    # --------------------------------------------------------------------------
    def _sync_window_position(self) -> None:
        """
        Quy đổi tọa độ màn hình từ PetPhysics sang vị trí cửa sổ nhỏ (Logical Pixels):
        - PetPhysics quản lý:
          + center_x: Tâm ngang của nhân vật trên màn hình (Logical Pixels).
          + bottom_y: Chân/đáy của nhân vật trên màn hình (Logical Pixels).
        - Cửa sổ nhỏ có lề margin_px (40px) ở mỗi phía:
          + Tâm ngang nhân vật nằm chính giữa cửa sổ: win_x = center_x - width / 2.
          + Chân nhân vật nằm cách mép dưới cửa sổ 40px: win_y = bottom_y - (height - 40).
        - Gọi self.move(win_x, win_y) để dịch chuyển cửa sổ trên desktop.
        """
        center_x, center_y, bottom_y = self.physics.get_screen_center_and_bottom()
        win_w = self.width()
        win_h = self.height()

        target_win_x = int(round(center_x - win_w / 2.0))
        target_win_y = int(round(bottom_y - (win_h - self.margin_px)))

        # Chỉ gọi move nếu tọa độ thực sự thay đổi để tránh system call thừa
        if target_win_x != self.x() or target_win_y != self.y():
            self.move(target_win_x, target_win_y)

    # --------------------------------------------------------------------------
    # KHỐI OPENGL VÀ RENDER
    # --------------------------------------------------------------------------
    def initializeGL(self) -> None:
        """
        Qt tự động gọi khi context OpenGL sẵn sàng.
        Khởi tạo Live2D model, tính kích thước cửa sổ vừa vặn + lề 40px mỗi phía,
        và đồng bộ vị trí với PetPhysics.
        """
        success = self.live2d_view.initialize_gl()
        if not success:
            print("[Overlay] Không thể khởi tạo Live2D Model!")
            return

        # 1. Tính toán kích thước nhân vật dựa trên aspect ratio và cấu hình
        aspect = self.live2d_view.get_model_aspect_ratio()
        char_h = float(self.settings.character_height_px)
        char_w = char_h * aspect

        # 2. Kích thước cửa sổ = kích thước nhân vật + lề 40px mỗi phía (Logical Pixels)
        win_w = int(round(char_w + 2.0 * self.margin_px))
        win_h = int(round(char_h + 2.0 * self.margin_px))

        # 3. Cập nhật kích thước ban đầu vào PetPhysics (Logical Pixels)
        self.physics.update_dimensions(char_w, char_h)

        # 4. Thiết lập kích thước cửa sổ Qt
        print(f"[Overlay] Thiết lập cửa sổ nhỏ: {win_w}x{win_h} (Logical px, gồm lề {self.margin_px:.0f}px mỗi phía)")
        self.resize(win_w, win_h)

        # Cấu hình bố cục và cache Bounding Box (Local Physical Pixels)
        dpr = self.devicePixelRatio()
        self.live2d_view.setup_layout(win_w, win_h, dpr, self.margin_px)
        self._current_phys_box = self.live2d_view.get_screen_bounds_physical(win_w * dpr, win_h * dpr)
        if self._current_phys_box is not None:
            bx1, by1, bx2, by2 = self._current_phys_box
            self.physics.update_dimensions((bx2 - bx1) / dpr, (by2 - by1) / dpr)

        # 5. Đồng bộ vị trí ban đầu của cửa sổ trên màn hình desktop
        self._sync_window_position()

    def resizeGL(self, width: int, height: int) -> None:
        """
        Cập nhật bố cục viewport và model Live2D bên trong cửa sổ nhỏ khi kích thước thay đổi.
        LƯU Ý DPI:
        - width, height: Kích thước cửa sổ Qt (Logical Pixels).
        - dpr = devicePixelRatio(): Tỉ lệ phóng to DPI.
        - setup_layout ánh xạ sang Physical Pixels và căn lề 40px * dpr chuẩn xác.
        - Tính toán và cache lại self._current_phys_box (không tính mỗi frame trong paintGL).
        - Cập nhật lại kích thước nhân vật cho PetPhysics (Logical Pixels).
        """
        dpr = self.devicePixelRatio()
        self.live2d_view.setup_layout(width, height, dpr, self.margin_px)

        phys_w = width * dpr
        phys_h = height * dpr
        self._current_phys_box = self.live2d_view.get_screen_bounds_physical(phys_w, phys_h)

        if self._current_phys_box is not None:
            bx1, by1, bx2, by2 = self._current_phys_box
            char_logical_w = (bx2 - bx1) / dpr
            char_logical_h = (by2 - by1) / dpr
            self.physics.update_dimensions(char_logical_w, char_logical_h)

    def paintGL(self) -> None:
        """Vẽ khung hình hiện tại."""
        t_start: float = 0.0
        if self.settings.debug_perf:
            t_start = time.perf_counter()

        now = time.perf_counter()
        dt = max(0.001, min(0.1, now - self._last_frame_time))
        self._last_frame_time = now

        # 1. Cập nhật vật lý (rơi tự do / kéo thả theo tọa độ màn hình)
        self.physics.update(dt)

        # 2. Di chuyển cửa sổ overlay theo vị trí nhân vật từ PetPhysics
        self._sync_window_position()

        # 3. Cập nhật state machine
        self.state_machine.update(dt, self.live2d_view.is_motion_finished())

        # 4. Cập nhật cử động mắt nhìn theo chuột (làm mượt độc lập FPS theo dt)
        self.live2d_view.update_look(
            dt,
            look_speed=self.settings.look_speed,
            use_manual_params=self.settings.use_manual_look_params
        )

        # 5. Vẽ model vào framebuffer nhỏ
        self.live2d_view.render_frame()

        # 6. Đo hiệu năng và in mỗi 1 giây (nếu bật debug_perf)
        if self.settings.debug_perf:
            paint_duration = time.perf_counter() - t_start
            self._perf_frame_count += 1
            self._perf_total_paint_time += paint_duration

            elapsed = time.perf_counter() - self._perf_last_report_time
            if elapsed >= 1.0:
                fps_measured = self._perf_frame_count / elapsed
                avg_paint_ms = (self._perf_total_paint_time / max(1, self._perf_frame_count)) * 1000.0
                fps_mode = "cao" if self.state_machine.is_high_fps else "thấp"
                print(f"[Perf] {round(fps_measured)} FPS, paintGL TB {avg_paint_ms:.1f} ms, mức FPS hiện tại: {fps_mode}")
                self._perf_frame_count = 0
                self._perf_total_paint_time = 0.0
                self._perf_last_report_time = time.perf_counter()

    @Slot()
    def on_render_tick(self) -> None:
        """Kích hoạt vẽ lại frame tiếp theo."""
        if not self.is_closing:
            self.update()

    # --------------------------------------------------------------------------
    # KHỐI POLLING CHUỘT & CLICK-THROUGH (HỖ TRỢ HIGH-DPI VÀ CỬA SỔ NHỎ)
    # --------------------------------------------------------------------------
    def is_cursor_over_character(self, local_phys_x: float, local_phys_y: float) -> bool:
        """
        Kiểm tra con trỏ chuột có nằm trên nhân vật hay không.
        
        LƯU Ý HỆ TỌA ĐỘ & DPI:
        - local_phys_x, local_phys_y: Tọa độ chuột trong KHÔNG GIAN CỤC BỘ CỦA CỬA SỔ (Local Physical Pixels).
        - self._current_phys_box: Bounding box của nhân vật trong cửa sổ (Local Physical Pixels).
        - Nếu con trỏ nằm ở ngoài cửa sổ hoặc nằm trong vùng lề 40px -> trả về False (xuyên thấu).
        - Phân đoạn hình thể (Shaped Hit-Testing):
          + Nửa trên (đầu): thu hẹp 70% bề rộng để tránh click trúng khoảng trống hai bên tai/tóc.
          + Nửa dưới (thân): giữ trọn 100% bề rộng.
        """
        if self._current_phys_box is None:
            return False

        x1, y1, x2, y2 = self._current_phys_box

        # Kiểm tra hộp bao ngoài nhanh (Fast Rejection)
        if not (x1 <= local_phys_x <= x2 and y1 <= local_phys_y <= y2):
            return False

        # Phân đoạn hình thể (Shaped Hit-Testing)
        mid_y = y1 + (y2 - y1) * 0.40
        center_x = (x1 + x2) * 0.5
        width = x2 - x1

        if local_phys_y < mid_y:
            # Thu hẹp vùng đầu để tránh click trúng khoảng trống
            head_half_w = (width * 0.70) * 0.5
            return (center_x - head_half_w) <= local_phys_x <= (center_x + head_half_w)
        else:
            return True

    @Slot()
    def poll_cursor(self) -> None:
        """
        Vòng lặp ~30ms kiểm tra chuột:
        1. Lấy tọa độ chuột toàn màn hình qua GetCursorPos (Physical Pixels).
        2. Quy đổi sang tọa độ cục bộ của cửa sổ (Local Physical Pixels).
        3. Cập nhật mục tiêu nhìn của mắt (set_look_target).
        4. Kiểm tra cử động chuột gần nhân vật (>3px trong eye_tracking_distance) -> notify_interaction().
        5. Hit-testing với thân nhân vật và bật/tắt WS_EX_TRANSPARENT:
           - Trúng nhân vật -> Tắt WS_EX_TRANSPARENT (bắt sự kiện click/kéo).
           - Vùng trống (lề 40px hoặc ngoài nhân vật) -> Bật WS_EX_TRANSPARENT (click xuyên thấu).
        """
        if self.is_closing or sys.platform != "win32":
            return

        user32 = ctypes.windll.user32

        # 1. LẤY TỌA ĐỘ CON TRỎ CHUỘT TOÀN MÀN HÌNH (PHYSICAL PIXELS)
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))

        # 2. QUY ĐỔI SANG TỌA ĐỘ VẬT LÝ CỤC BỘ TRONG CỬA SỔ (LOCAL PHYSICAL PIXELS)
        dpr = self.devicePixelRatio()
        win_phys_x = round(self.x() * dpr)
        win_phys_y = round(self.y() * dpr)

        local_cursor_phys_x = pt.x - win_phys_x
        local_cursor_phys_y = pt.y - win_phys_y

        # 3. THIẾT LẬP MỤC TIÊU NHÌN THEO CHUỘT
        tracking_dist_phys = self.settings.eye_tracking_distance_px * dpr
        self.live2d_view.set_look_target(local_cursor_phys_x, local_cursor_phys_y,
                                         self._current_phys_box, tracking_dist_phys)

        # 4. DUY TRÌ FPS CAO KHI CHUỘT DI CHUYỂN GẦN NHÂN VẬT (>3px so với lần poll trước)
        cursor_moved = False
        if self._last_cursor_pos is not None:
            dx_cur = pt.x - self._last_cursor_pos[0]
            dy_cur = pt.y - self._last_cursor_pos[1]
            if (dx_cur * dx_cur + dy_cur * dy_cur) > 9.0:  # > 3px (3^2 = 9)
                cursor_moved = True
        self._last_cursor_pos = (pt.x, pt.y)

        if self._current_phys_box is not None:
            bx1, by1, bx2, by2 = self._current_phys_box
            eye_x = (bx1 + bx2) * 0.5
            eye_y = by1 + (by2 - by1) * 0.3
            dist_to_pet = ((local_cursor_phys_x - eye_x) ** 2 + (local_cursor_phys_y - eye_y) ** 2) ** 0.5
            if dist_to_pet <= tracking_dist_phys and cursor_moved:
                self.state_machine.notify_interaction()

        # 5. HIT-TESTING VỚI THÂN NHÂN VẬT VÀ ĐIỀU KHIỂN CLICK-THROUGH
        now_hovered = self.is_cursor_over_character(local_cursor_phys_x, local_cursor_phys_y)

        # Khi đang trong quá trình kéo chuột hoặc giữ chuột, luôn giữ không cho click-through
        if self._is_dragging or self._mouse_down:
            now_hovered = True

        if now_hovered != self.is_hovered:
            self.is_hovered = now_hovered
            hwnd = int(self.winId())

            if self.is_hovered:
                # Con trỏ ĐI VÀO thân nhân vật -> Tắt WS_EX_TRANSPARENT (Bắt sự kiện chuột)
                set_clickthrough(hwnd, False)
                self.live2d_view.set_hover_highlight(True)
                self.state_machine.notify_interaction()
            else:
                # Con trỏ ĐI RA (vào vùng lề 40px hoặc ra ngoài) -> Bật WS_EX_TRANSPARENT (Click xuyên thấu)
                set_clickthrough(hwnd, True)
                self.live2d_view.set_hover_highlight(False)

    # --------------------------------------------------------------------------
    # KHỐI XỬ LÝ SỰ KIỆN CHUỘT (TƯƠNG TÁC PET & QMENU)
    # --------------------------------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Xử lý sự kiện nhấn chuột trên nhân vật."""
        self.state_machine.notify_interaction()

        if event.button() == Qt.MouseButton.LeftButton:
            self._mouse_down = True
            self._is_dragging = False
            # globalPosition().toPoint() trả về tọa độ màn hình (Logical Pixels)
            self._press_screen_pos = event.globalPosition().toPoint()
            event.accept()

        elif event.button() == Qt.MouseButton.RightButton:
            # Hiện menu ngữ cảnh QMenu tại vị trí con trỏ chuột trên màn hình
            self._show_context_menu(event.globalPosition().toPoint())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Xử lý di chuyển chuột và kéo nhân vật khắp màn hình."""
        if self._mouse_down:
            current_pos = event.globalPosition().toPoint()
            delta = current_pos - self._press_screen_pos
            dist = (delta.x() ** 2 + delta.y() ** 2) ** 0.5

            if not self._is_dragging and dist >= self.settings.drag_threshold_px:
                # Vượt ngưỡng -> Bắt đầu kéo
                self._is_dragging = True
                self.physics.start_drag(float(current_pos.x()), float(current_pos.y()))
                self.state_machine.trigger_drag_start()

            if self._is_dragging:
                # Kéo nhân vật theo tọa độ màn hình (Logical Pixels)
                self.physics.drag_to(float(current_pos.x()), float(current_pos.y()))
                self._sync_window_position()
                self.state_machine.notify_interaction()

            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Xử lý thả chuột: phân biệt giữa click giật mình và thả sau kéo."""
        if event.button() == Qt.MouseButton.LeftButton and self._mouse_down:
            self._mouse_down = False

            if self._is_dragging:
                # Người dùng đã kéo thả -> Thả rơi tự do xuống sàn
                self._is_dragging = False
                is_falling = self.physics.release_drag()
                self.state_machine.trigger_drag_release(is_falling)
            else:
                # Nhấp chuột đơn thuần mà không kéo -> Giật mình (STARTLED)
                self.state_machine.trigger_left_click()

            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def _show_context_menu(self, global_pos: QPoint) -> None:
        """Hiển thị menu ngữ cảnh chuột phải bằng QMenu (Ngủ, Nhảy, Thoát)."""
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: rgba(32, 34, 40, 230);
                color: #FFFFFF;
                border: 1px solid rgba(255, 255, 255, 30);
                border-radius: 8px;
                padding: 6px;
                font-size: 13px;
                font-family: 'Segoe UI', sans-serif;
            }
            QMenu::item {
                padding: 6px 24px 6px 16px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: rgba(80, 140, 255, 180);
            }
            QMenu::separator {
                height: 1px;
                background: rgba(255, 255, 255, 25);
                margin: 4px 8px;
            }
        """)

        # Hành động: Ngủ
        action_sleep = QAction("💤 Ngủ (Sleep)", self)
        action_sleep.triggered.connect(self.state_machine.trigger_sleep_menu)
        menu.addAction(action_sleep)

        # Hành động: Nhảy
        action_dance = QAction("💃 Nhảy (Dance)", self)
        action_dance.triggered.connect(self.state_machine.trigger_dance_menu)
        menu.addAction(action_dance)

        menu.addSeparator()

        # Hành động: Thoát
        action_exit = QAction("❌ Thoát (Ctrl+Q)", self)
        action_exit.triggered.connect(lambda: self.exit_application("Chọn Thoát từ Menu"))
        menu.addAction(action_exit)

        menu.exec(global_pos)

    # --------------------------------------------------------------------------
    # THOÁT ỨNG DỤNG AN TOÀN
    # --------------------------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Bắt phím bấm trực tiếp khi cửa sổ có focus."""
        if event.key() == Qt.Key.Key_Escape:
            self.exit_application("Phím Esc (keyPressEvent)")
            event.accept()
        elif event.key() == Qt.Key.Key_Q and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.exit_application("Phím Ctrl+Q (keyPressEvent)")
            event.accept()
        else:
            super().keyPressEvent(event)

    def exit_application(self, reason: str = "") -> None:
        """Dọn dẹp tài nguyên và thoát ứng dụng an toàn."""
        if self.is_closing:
            return
        self.is_closing = True

        print(f"[Overlay] Đang thoát ứng dụng: {reason}")

        if self.render_timer.isActive():
            self.render_timer.stop()
        if self.cursor_timer.isActive():
            self.cursor_timer.stop()
        if self.fallback_timer is not None and self.fallback_timer.isActive():
            self.fallback_timer.stop()

        try:
            self.makeCurrent()
            self.live2d_view.release()
            self.doneCurrent()
        except Exception as e:
            print(f"[Overlay] Ngoại lệ khi giải phóng Live2D: {e}")

        self.close()
        QApplication.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.exit_application("CloseEvent")
        event.accept()
