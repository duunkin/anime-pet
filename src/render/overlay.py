"""
src/render/overlay.py
---------------------
Cửa sổ chính hiển thị Live2D Overlay (QOpenGLWidget):
- Không viền (Frameless), trong suốt hoàn toàn (Translucent), luôn trên cùng (Always on top).
- Áp dụng Windows DWM API để loại bỏ triệt để lỗi nền đen trên Windows 10/11.
- Kỹ thuật Click-through động (Dynamic Click-through): Xuyên qua vùng trống, bắt chuột trên nhân vật.
- Tương tác chuột:
  + Mắt nhìn theo con trỏ chuột khi ở gần.
  + Click trái = giật mình.
  + Giữ chuột trái rồi kéo = nhấc nhân vật lên; thả ra = rơi tự do xuống sàn.
  + Click phải = QMenu (Ngủ, Nhảy, Thoát).
- Thích ứng FPS: 60 FPS khi hoạt động, tự giảm về 15 FPS khi nhàn rỗi lâu.
- Phím tắt thoát: Ctrl+Q và Esc (hỗ trợ cả khi cửa sổ mất focus).
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
from src.behavior.state_machine import PetStateMachine, PetState
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
    """Bật hoặc tắt cờ WS_EX_TRANSPARENT để hỗ trợ click xuyên thấu."""
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
    Cửa sổ Overlay chính phối hợp các hệ thống: Physics, Live2DView, StateMachine.
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

        self.is_closing: bool = False
        self.is_hovered: bool = False

        # Quản lý kéo thả chuột
        self._mouse_down: bool = False
        self._is_dragging: bool = False
        self._press_screen_pos: QPoint = QPoint()

        # Quản lý thời gian tính toán vật lý
        self._last_frame_time: float = time.perf_counter()

        # Lưu cache bounding box vật lý của nhân vật
        self._current_phys_box: Optional[Tuple[float, float, float, float]] = None

        # 1. Cấu hình cờ cửa sổ
        self._setup_window_flags()

        # 2. Cấu hình phím tắt
        self._setup_shortcuts()

        # 3. Kết nối callbacks của State Machine và Physics
        self._setup_behavior_bindings()

        # 4. Timer vẽ khung hình (FPS thích ứng)
        self.render_timer = QTimer(self)
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
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    def _setup_shortcuts(self) -> None:
        """Đăng ký phím tắt Ctrl+Q và Esc trong Qt."""
        self.shortcut_esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.shortcut_esc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_esc.activated.connect(lambda: self.exit_application("Phím Esc"))

        self.shortcut_ctrl_q = QShortcut(QKeySequence("Ctrl+Q"), self)
        self.shortcut_ctrl_q.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_ctrl_q.activated.connect(lambda: self.exit_application("Phím Ctrl+Q"))

    def _setup_behavior_bindings(self) -> None:
        """Kết nối các tín hiệu giữa State Machine, Physics và Live2D View."""
        # Khi state machine muốn phát một hành vi (motion / biểu cảm)
        self.state_machine.on_trigger_behavior = self.live2d_view.play_behavior

        # Khi state machine thay đổi chế độ FPS
        self.state_machine.on_fps_mode_changed = self._apply_fps_mode

        # Khi nhân vật rơi chạm đất -> báo state machine chuyển sang IDLE
        self.physics.on_ground_hit = self.state_machine.trigger_land

    def _apply_fps_mode(self, is_high: bool) -> None:
        """Điều chỉnh tần số quét của render timer giữa 60 FPS và 15 FPS."""
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

        self.setFocus()
        self.activateWindow()

        # Khởi động các bộ đếm thời gian
        if not self.render_timer.isActive():
            self.render_timer.start()
        if not self.cursor_timer.isActive():
            self.cursor_timer.start()
        if self.fallback_timer is not None and not self.fallback_timer.isActive():
            self.fallback_timer.start(int(self.settings.auto_exit_seconds * 1000))

    # --------------------------------------------------------------------------
    # KHỐI OPENGL VÀ RENDER
    # --------------------------------------------------------------------------
    def initializeGL(self) -> None:
        """Qt tự động gọi khi context OpenGL sẵn sàng."""
        success = self.live2d_view.initialize_gl()
        if not success:
            print("[Overlay] Không thể khởi tạo Live2D Model!")

    def resizeGL(self, width: int, height: int) -> None:
        """Cập nhật kích thước khung nhìn khi cửa sổ resize."""
        self.live2d_view.resize(width, height)
        self.physics.set_screen_bounds(width, height, self.settings.floor_margin_px)

    def paintGL(self) -> None:
        """Vẽ khung hình hiện tại."""
        now = time.perf_counter()
        dt = max(0.001, min(0.1, now - self._last_frame_time))
        self._last_frame_time = now

        # 1. Cập nhật vật lý (rơi tự do / kéo thả)
        self.physics.update(dt)

        # 2. Lấy tọa độ pixel màn hình từ physics
        center_x, center_y, bottom_y = self.physics.get_screen_center_and_bottom()

        # 3. Cập nhật vị trí model Live2D trong NDC
        self.live2d_view.set_screen_position(center_x, bottom_y, self.width(), self.height())

        # 4. Cập nhật state machine
        self.state_machine.update(dt, self.live2d_view.is_motion_finished())

        # 5. Vẽ model qua Live2D Shaders
        self.live2d_view.render_frame()

        # 6. Cập nhật lại khung bao kích thước cho Physics và Hit-testing
        dpr = self.devicePixelRatio()
        phys_w = self.width() * dpr
        phys_h = self.height() * dpr
        self._current_phys_box = self.live2d_view.get_screen_bounds_physical(phys_w, phys_h)
        if self._current_phys_box is not None:
            bx1, by1, bx2, by2 = self._current_phys_box
            # Quy đổi kích thước physical sang logical cho physics
            self.physics.update_dimensions((bx2 - bx1) / dpr, (by2 - by1) / dpr)

    @Slot()
    def on_render_tick(self) -> None:
        """Kích hoạt vẽ lại frame tiếp theo."""
        if not self.is_closing:
            self.update()

    # --------------------------------------------------------------------------
    # KHỐI POLLING CHUỘT & CLICK-THROUGH (SPIKE 2 ENGINE)
    # --------------------------------------------------------------------------
    def is_cursor_over_character(self, cursor_phys_x: int, cursor_phys_y: int) -> bool:
        """
        Kiểm tra con trỏ chuột (ở tọa độ Physical Pixels) có nằm trên nhân vật hay không.
        Sử dụng phân đoạn hình thể (nửa trên thu hẹp vùng đầu, nửa dưới giữ rộng vùng thân).
        """
        if self._current_phys_box is None:
            return False

        x1, y1, x2, y2 = self._current_phys_box
        # Kiểm tra nhanh hộp bao ngoài
        if not (x1 <= cursor_phys_x <= x2 and y1 <= cursor_phys_y <= y2):
            return False

        # Phân đoạn hình thể (Shaped Hit-Testing)
        mid_y = y1 + (y2 - y1) * 0.40
        center_x = (x1 + x2) * 0.5
        width = x2 - x1

        if cursor_phys_y < mid_y:
            # Thu hẹp vùng đầu để tránh click trúng khoảng trống 2 bên tai/tóc
            head_half_w = (width * 0.70) * 0.5
            return (center_x - head_half_w) <= cursor_phys_x <= (center_x + head_half_w)
        else:
            return True

    @Slot()
    def poll_cursor(self) -> None:
        """
        Vòng lặp ~30ms:
        1. Kiểm tra phím thoát toàn cục (GetAsyncKeyState) đề phòng overlay mất focus.
        2. Hit-testing con trỏ chuột với hitbox nhân vật.
        3. Bật/tắt cờ WS_EX_TRANSPARENT chỉ khi chuyển trạng thái (tránh nhấp nháy).
        4. Cập nhật mắt nhìn theo chuột khi ở gần.
        """
        if self.is_closing or sys.platform != "win32":
            return

        user32 = ctypes.windll.user32

        # --- A. PHÍM THOÁT TOÀN CỤC ---
        esc_down = bool(user32.GetAsyncKeyState(VK_ESCAPE) & 0x8000)
        ctrl_down = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
        q_down = bool(user32.GetAsyncKeyState(VK_Q) & 0x8000)

        if esc_down:
            self.exit_application("Phím Esc (GetAsyncKeyState)")
            return
        if ctrl_down and q_down:
            self.exit_application("Phím Ctrl+Q (GetAsyncKeyState)")
            return

        # --- B. LẤY TỌA ĐỘ CON TRỎ CHUỘT VẬT LÝ ---
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))

        # --- C. ĐIỀU KHIỂN MẮT NHÌN THEO CHUỘT ---
        dpr = self.devicePixelRatio()
        tracking_dist_phys = self.settings.eye_tracking_distance_px * dpr
        self.live2d_view.update_look_at(pt.x, pt.y, self._current_phys_box, tracking_dist_phys)

        # --- D. HIT-TESTING VỚI THÂN NHÂN VẬT ---
        now_hovered = self.is_cursor_over_character(pt.x, pt.y)

        # Đang trong quá trình kéo chuột thì luôn giữ không cho click-through
        if self._is_dragging or self._mouse_down:
            now_hovered = True

        if now_hovered != self.is_hovered:
            self.is_hovered = now_hovered
            hwnd = int(self.winId())

            if self.is_hovered:
                # Con trỏ ĐI VÀO -> Tắt WS_EX_TRANSPARENT (Bắt sự kiện chuột)
                set_clickthrough(hwnd, False)
                self.live2d_view.set_hover_highlight(True)
                self.state_machine.notify_interaction()
            else:
                # Con trỏ ĐI RA -> Bật WS_EX_TRANSPARENT (Click xuyên qua)
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
            self._press_screen_pos = event.globalPosition().toPoint()
            event.accept()

        elif event.button() == Qt.MouseButton.RightButton:
            # Hiện menu ngữ cảnh QMenu
            self._show_context_menu(event.globalPosition().toPoint())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Xử lý di chuyển chuột và kéo nhân vật."""
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
                self.physics.drag_to(float(current_pos.x()), float(current_pos.y()))
                self.state_machine.notify_interaction()

            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        """Xử lý thả chuột: phân biệt giữa click giật mình và thả sau kéo."""
        if event.button() == Qt.MouseButton.LeftButton and self._mouse_down:
            self._mouse_down = False

            if self._is_dragging:
                # Người dùng đã kéo thả -> Thả rơi tự do
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
