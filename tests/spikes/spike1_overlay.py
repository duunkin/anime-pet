"""
spike1_overlay.py
-----------------
Thử nghiệm kỹ thuật (Spike 1) cho ứng dụng Desktop Pet:
- Cửa sổ PySide6 không viền (Frameless), nền trong suốt hoàn toàn (Translucent),
  luôn nằm trên cùng (Stay On Top), phủ toàn bộ màn hình chính.
- Hiển thị model Live2D Hiyori từ file model3.json ở góc dưới bên phải màn hình.
- Chạy vòng lặp render ~60 FPS bằng QOpenGLWidget và QTimer.
- Nhận phím Esc hoặc Ctrl+Q để thoát an toàn, kèm fallback tự thoát sau 60 giây.

================================================================================
THÔNG TIN PHIÊN BẢN THƯ VIỆN & CÁCH GỌI API LIVE2D-PY:
================================================================================
1. Thư viện sử dụng:
   - Python: 3.11+
   - PySide6: 6.12.0 (GUI framework & Qt OpenGL integration)
   - live2d-py: 1.0.0 (Wrapper Python của Live2D Cubism SDK 5-r.5 Native)
   - PyOpenGL: 3.1.10

2. Cách gọi API live2d-py:
   - live2d.init(): Khởi tạo hệ thống quản lý tài nguyên Live2D (gọi 1 lần).
   - live2d.glInit(): Nạp con trỏ hàm OpenGL shaders/buffers của Live2D SDK
     (bắt buộc gọi TRONG context OpenGL đang kích hoạt, tức trong initializeGL).
   - live2d.Model(): Tạo đối tượng đại diện cho Live2D Model.
   - model.LoadModelJson(path): Nạp file .model3.json và biên dịch shader, texture.
   - model.Resize(width, height): Đồng bộ kích thước viewport hiển thị.
   - model.SetScale(scale): Thu nhỏ / phóng to model (0.0 đến 1.0+).
   - model.SetOffset(x, y): Dịch chuyển vị trí model trong hệ tọa độ NDC [-1, 1].
   - model.StartRandomMotion(group, priority): Bắt đầu chuyển động (idle).
   - model.IsMotionFinished(): Kiểm tra chuyển động hiện tại đã kết thúc chưa.
   - model.Update(): Cập nhật physics, eye blink, breath, motion của model.
   - model.Draw(): Thực hiện các lệnh vẽ OpenGL của model.
   - live2d.clearBuffer(0, 0, 0, 0): Xóa bộ đệm màu với alpha = 0 (trong suốt).
   - live2d.dispose(): Giải phóng tài nguyên Live2D khi đóng ứng dụng.

================================================================================
NGUYÊN NHÂN & CÁCH KHẮC PHỤC LỖI NỀN TRONG SUỐT VỚI QOPENGLWIDGET TRÊN WINDOWS:
================================================================================
Trên Windows 10/11, việc vẽ OpenGL trong suốt qua desktop thường gặp 3 lỗi lớn:

1. [LỖI] Màn hình bị hộp đen (Black box / Nền đen che mất desktop):
   - Nguyên nhân: Mặc định trên nhiều GPU/driver (NVIDIA/AMD/Intel), QSurfaceFormat
     khởi tạo với alphaBufferSize = 0, khiến kênh alpha bị bỏ qua và ép thành 1.0 (đen).
     Ngoài ra, nếu Desktop Window Manager (DWM) của Windows không nhận được chỉ thị
     mở rộng glass frame vào client area, Windows sẽ vẽ nền đen đằng sau frameless window.
   - Cách khắc phục:
     a) Cấu hình QSurfaceFormat: Thiết lập `fmt.setAlphaBufferSize(8)` và gán
        `QSurfaceFormat.setDefaultFormat(fmt)` TRƯỚC KHI tạo QApplication.
     b) Kích hoạt Qt Attributes:
        - `Qt.WidgetAttribute.WA_TranslucentBackground = True`
        - `Qt.WidgetAttribute.WA_NoSystemBackground = True`
     c) Windows DWM API: Gọi `dwmapi.DwmExtendFrameIntoClientArea(hwnd, MARGINS(-1,-1,-1,-1))`
        thông qua thư viện `ctypes` để ép Windows DWM composite vùng client area
        ở chế độ trong suốt thực sự với Desktop compositor.

2. [LỖI] Viền đen răng cưa quanh nhân vật (Dark/Black Halos / Fringing):
   - Nguyên nhân: Xung đột chế độ nhân alpha (Premultiplied Alpha) giữa OpenGL
     và bộ trộn DWM của Windows.
   - Cách khắc phục: Dùng `live2d.clearBuffer(0.0, 0.0, 0.0, 0.0)` ở đầu mỗi frame,
     và để Live2D Cubism SDK tự quản lý hàm hòa trộn glBlendFunc nội bộ của nó.

3. [LỖI] Cửa sổ frameless không nhận được phím Esc / Ctrl+Q:
   - Nguyên nhân: Cửa sổ không viền và trong suốt đôi khi không nhận focus mặc định,
     hoặc người dùng lỡ bấm chuột xuyên/ra ngoài màn hình.
   - Cách khắc phục:
     - Gán `setFocusPolicy(Qt.FocusPolicy.StrongFocus)`.
     - Dùng đồng thời `QShortcut` (ApplicationShortcut) và ghi đè `keyPressEvent`.
     - Kèm cơ chế tự thoát an toàn (fallback) sau `AUTO_EXIT_SECONDS` (60s).
================================================================================
"""

import os
import sys
import ctypes
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QSurfaceFormat, QKeySequence, QShortcut, QCloseEvent, QKeyEvent
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from OpenGL import GL

import live2d

# ==============================================================================
# HẰNG SỐ CẤU HÌNH (CONFIGURATION CONSTANTS)
# ==============================================================================
# Đường dẫn tương đối hoặc tuyệt đối tới file .model3.json
MODEL_PATH: str = "../../characters/Hiyori/Hiyori.model3.json"

# Tần số quét khung hình mục tiêu (~60 FPS tương đương ~16ms/frame)
TARGET_FPS: int = 60
FRAME_INTERVAL_MS: int = int(1000 / TARGET_FPS)

# Vị trí & Tỉ lệ hiển thị của nhân vật:
# Hệ tọa độ Live2D Model:
# - Trục X: [-1.0 (trái), 0.0 (giữa), 1.0 (phải)]
# - Trục Y: [-1.0 (dưới), 0.0 (giữa), 1.0 (trên)]
MODEL_SCALE: float = 0.65       # Kích thước thu phóng vừa vặn góc màn hình
MODEL_OFFSET_X: float = 0.65    # Đẩy lệch sang phải để nằm ở góc phải
MODEL_OFFSET_Y: float = -0.35   # Đẩy lệch xuống dưới để chân/thân đứng sát đáy

# Nhóm chuyển động nhàn rỗi (Idle motion group) trong file model3.json
MOTION_GROUP_IDLE: str = "Idle"

# Cơ chế an toàn (fallback): Tự động thoát sau N giây nếu người dùng không thao tác
# Đặt <= 0 nếu không muốn giới hạn thời gian chạy.
AUTO_EXIT_SECONDS: int = 60


# ==============================================================================
# TIỆN ÍCH WINDOWS DWM (DWM TRANSPARENCY HELPER)
# ==============================================================================
def apply_windows_transparency(window_handle: int) -> bool:
    """
    Kích hoạt chế độ mở rộng khung kính trong suốt DWM trên Windows 10/11.
    
    Hàm này gọi API Win32 DwmExtendFrameIntoClientArea với margin = -1
    để khắc phục triệt để lỗi nền đen khi render OpenGL trên cửa sổ không viền.
    """
    if sys.platform != "win32":
        return False

    try:
        class MARGINS(ctypes.Structure):
            _fields_ = [
                ("cxLeftWidth", ctypes.c_int),
                ("cxRightWidth", ctypes.c_int),
                ("cyTopHeight", ctypes.c_int),
                ("cyBottomHeight", ctypes.c_int),
            ]

        # Margin -1 cho biết toàn bộ diện tích cửa sổ sẽ được DWM xử lý trong suốt
        margins = MARGINS(-1, -1, -1, -1)
        dwm = ctypes.windll.dwmapi
        result = dwm.DwmExtendFrameIntoClientArea(window_handle, ctypes.byref(margins))
        if result == 0:
            print("[Windows DWM] Đã kích hoạt DwmExtendFrameIntoClientArea thành công.")
            return True
        else:
            print(f"[Windows DWM] Cảnh báo: Mã lỗi DWM: {result}")
            return False
    except Exception as exc:
        print(f"[Windows DWM] Không thể gọi API DWM: {exc}")
        return False


def resolve_model_path(path_str: str) -> str:
    """
    Chuẩn hóa và tìm kiếm file model .model3.json.
    Hỗ trợ cả trường hợp viết hoa/viết thường khác nhau trên các hệ điều hành.
    """
    abs_path = os.path.abspath(path_str)
    if os.path.exists(abs_path):
        return abs_path

    # Thử tìm kiếm không phân biệt hoa thường trong cùng thư mục
    directory = os.path.dirname(abs_path)
    target_name = os.path.basename(abs_path).lower()
    if os.path.isdir(directory):
        for filename in os.listdir(directory):
            if filename.lower() == target_name:
                return os.path.join(directory, filename)

    return abs_path


# ==============================================================================
# CLASS CHÍNH: LIVE2D OVERLAY WINDOW (QOpenGLWidget)
# ==============================================================================
class Live2DOverlayWindow(QOpenGLWidget):
    """
    Cửa sổ hiển thị Live2D Overlay:
    - Kế thừa từ QOpenGLWidget để vừa đóng vai trò cửa sổ cấp cao nhất (Top-level Window),
      vừa là bề mặt vẽ OpenGL tăng tốc phần cứng.
    - Không viền, trong suốt, luôn trên cùng, bao phủ toàn màn hình.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # 1. Khởi tạo thuộc tính nội bộ
        self.model: Optional[live2d.Model] = None
        self.is_closing: bool = False

        # 2. Cấu hình Cửa sổ không viền, luôn nằm trên cùng và nền trong suốt
        self._setup_window_flags()

        # 3. Cấu hình phím tắt và xử lý focus
        self._setup_shortcuts()

        # 4. Vòng lặp cập nhật khung hình (~60 FPS)
        self.render_timer = QTimer(self)
        self.render_timer.setInterval(FRAME_INTERVAL_MS)
        self.render_timer.timeout.connect(self.on_timer_tick)

        # 5. Timer tự động thoát an toàn (fallback)
        self.fallback_timer: Optional[QTimer] = None
        if AUTO_EXIT_SECONDS > 0:
            self.fallback_timer = QTimer(self)
            self.fallback_timer.setSingleShot(True)
            self.fallback_timer.timeout.connect(self.on_fallback_timeout)

    # --------------------------------------------------------------------------
    # KHỐI KHỞI TẠO CỬA SỔ & PHÍM TẮT (INITIALIZATION)
    # --------------------------------------------------------------------------
    def _setup_window_flags(self) -> None:
        """Thiết lập các cờ và thuộc tính trong suốt cho cửa sổ Qt."""
        # FramelessWindowHint: Loại bỏ hoàn toàn thanh tiêu đề và viền cửa sổ
        # WindowStaysOnTopHint: Luôn hiển thị trên cùng các ứng dụng khác
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )

        # Kích hoạt nền trong suốt của Qt
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        # Đảm bảo cửa sổ có thể nhận focus bàn phím
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def _setup_shortcuts(self) -> None:
        """Thiết lập các phím tắt toàn cục cho cửa sổ để thoát chương trình."""
        # Phím Esc
        self.shortcut_esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.shortcut_esc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_esc.activated.connect(lambda: self.exit_application("Phím Esc"))

        # Phím Ctrl+Q
        self.shortcut_ctrl_q = QShortcut(QKeySequence("Ctrl+Q"), self)
        self.shortcut_ctrl_q.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.shortcut_ctrl_q.activated.connect(lambda: self.exit_application("Phím Ctrl+Q"))

    def showEvent(self, event) -> None:
        """Sự kiện khi cửa sổ được hiển thị lên màn hình."""
        super().showEvent(event)

        # Áp dụng DWM Transparency trên Windows sau khi window handle đã hợp lệ
        hwnd = int(self.winId())
        apply_windows_transparency(hwnd)

        # Chiếm focus bàn phím để chắc chắn nhận được Esc / Ctrl+Q
        self.setFocus()
        self.activateWindow()
        self.raise_()

        # Bắt đầu vòng lặp vẽ 60 FPS
        if not self.render_timer.isActive():
            self.render_timer.start()

        # Khởi động fallback timer (nếu có cấu hình)
        if self.fallback_timer is not None and not self.fallback_timer.isActive():
            print(f"[An toàn] Tự động thoát sau {AUTO_EXIT_SECONDS}s (bấm Esc hoặc Ctrl+Q để thoát ngay).")
            self.fallback_timer.start(AUTO_EXIT_SECONDS * 1000)

    # --------------------------------------------------------------------------
    # KHỐI OPENGL VÀ LIVE2D VẼ KHUNG HÌNH (OPENGL RENDERING)
    # --------------------------------------------------------------------------
    def initializeGL(self) -> None:
        """
        Khởi tạo môi trường OpenGL và nạp Live2D Model.
        Hàm này được Qt tự động gọi một lần khi context OpenGL đã sẵn sàng.
        """
        print("[OpenGL] Đang khởi tạo OpenGL Context...")

        # 1. Khởi tạo con trỏ hàm OpenGL của Live2D Cubism SDK
        # Lưu ý: BẮT BUỘC gọi live2d.glInit() bên trong context OpenGL hợp lệ!
        live2d.glInit()

        # 2. Nạp Live2D Model
        target_path = resolve_model_path(MODEL_PATH)
        print(f"[Live2D] Đường dẫn model: {target_path}")

        if not os.path.exists(target_path):
            print(f"[LỖI] Không tìm thấy file model: {target_path}")
            QMessageBox.critical(self, "Lỗi", f"Không tìm thấy model:\n{target_path}")
            self.exit_application("Lỗi file model không tồn tại")
            return

        try:
            self.model = live2d.Model()
            # LoadModelJson nạp moc3, textures, physics, motions và tạo render shaders
            self.model.LoadModelJson(target_path, create_renderer=True)
            print("[Live2D] Nạp model thành công!")

            # 3. Bắt đầu chạy motion idle
            # Priority 1: Idle priority (không chặn các motion tương tác sau này)
            self.model.StartRandomMotion(MOTION_GROUP_IDLE, 1)

            # 4. Kích hoạt tự động chớp mắt và thở
            self.model.SetAutoBlink(True)
            self.model.SetAutoBreath(True)

        except Exception as e:
            print(f"[LỖI] Xảy ra ngoại lệ khi nạp Live2D Model: {e}")
            import traceback
            traceback.print_exc()
            self.exit_application("Lỗi nạp model Live2D")

    def resizeGL(self, width: int, height: int) -> None:
        """
        Đồng bộ kích thước viewport OpenGL khi cửa sổ thay đổi kích thước.
        """
        GL.glViewport(0, 0, width, height)

        if self.model is not None:
            # Báo cho Live2D Model kích thước canvas mới
            self.model.Resize(width, height)
            # Áp dụng tỉ lệ và vị trí đặt model ở góc dưới bên phải
            self.model.SetScale(MODEL_SCALE)
            self.model.SetOffset(MODEL_OFFSET_X, MODEL_OFFSET_Y)

    def paintGL(self) -> None:
        """
        Hàm vẽ từng khung hình của QOpenGLWidget.
        Được gọi liên tục mỗi chu kỳ 60 FPS từ QTimer.
        """
        # 1. XÓA BỘ ĐỆM MÀU VỚI ALPHA = 0.0 (TRONG SUỐT HOÀN TOÀN)
        # Đây là bước quyết định để nhìn xuyên thấy desktop và các cửa sổ khác.
        live2d.clearBuffer(0.0, 0.0, 0.0, 0.0)

        # 2. CẬP NHẬT VÀ VẼ LIVE2D MODEL
        if self.model is not None:
            # Nếu motion idle hiện tại đã kết thúc, tự động lặp lại một motion idle ngẫu nhiên
            if self.model.IsMotionFinished():
                self.model.StartRandomMotion(MOTION_GROUP_IDLE, 1)

            # Cập nhật logic animation (delta thời gian tự thích ứng)
            self.model.Update()

            # Vẽ model ra màn hình qua shader của Cubism SDK
            self.model.Draw()

    @Slot()
    def on_timer_tick(self) -> None:
        """Kích hoạt vẽ lại khung hình tiếp theo (~60 FPS)."""
        if not self.is_closing:
            self.update()

    # --------------------------------------------------------------------------
    # KHỐI XỬ LÝ PHÍM BÀN PHÍM VÀ THOÁT ỨNG DỤNG (INPUT & EXIT)
    # --------------------------------------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Bắt sự kiện phím bấm trực tiếp trên cửa sổ."""
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
        """Hàm kích hoạt khi hết thời gian tự động thoát an toàn."""
        self.exit_application(f"Hết thời gian chờ {AUTO_EXIT_SECONDS}s (Fallback Auto-Exit)")

    def exit_application(self, reason: str = "") -> None:
        """
        Hàm thoát an toàn: Dừng timer, giải phóng tài nguyên Live2D và thoát Qt.
        """
        if self.is_closing:
            return
        self.is_closing = True

        print(f"[Thoát] Yêu cầu thoát ứng dụng: {reason}")

        # 1. Dừng các timer
        if self.render_timer.isActive():
            self.render_timer.stop()
        if self.fallback_timer is not None and self.fallback_timer.isActive():
            self.fallback_timer.stop()

        # 2. Hủy renderer của model nếu context OpenGL còn hiệu lực
        try:
            self.makeCurrent()
            if self.model is not None:
                self.model.DestroyRenderer()
                self.model = None
            live2d.glRelease()
            self.doneCurrent()
        except Exception as e:
            print(f"[Dọn dẹp] Ngoại lệ khi giải phóng OpenGL: {e}")

        # 3. Đóng cửa sổ và thoát vòng lặp Qt
        self.close()
        QApplication.quit()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Đảm bảo dọn dẹp tài nguyên khi có sự kiện đóng cửa sổ."""
        self.exit_application("Sự kiện CloseEvent")
        event.accept()


# ==============================================================================
# ĐIỂM VÀO CHÍNH (ENTRY POINT)
# ==============================================================================
def main() -> None:
    """Hàm khởi tạo và khởi chạy ứng dụng."""
    print("=================================================================")
    print(" KHỞI ĐỘNG LIVE2D DESKTOP PET OVERLAY (SPIKE 1)")
    print(" Phiên bản: Python 3.11 | PySide6 6.12.0 | live2d-py 1.0.0")
    print(" Nhấn [Esc] hoặc [Ctrl+Q] để thoát chương trình bất cứ lúc nào.")
    print("=================================================================")

    # 1. Cấu hình QSurfaceFormat hỗ trợ Alpha Buffer (QUAN TRỌNG ĐỂ TRONG SUỐT)
    # Bắt buộc đặt trước khi tạo QApplication hoặc bất kỳ QOpenGLWidget nào.
    surface_format = QSurfaceFormat()
    surface_format.setAlphaBufferSize(8)      # 8-bit Alpha channel cho độ trong suốt
    surface_format.setDepthBufferSize(24)      # 24-bit Depth buffer
    surface_format.setStencilBufferSize(8)    # 8-bit Stencil buffer cho mask clipping
    surface_format.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
    surface_format.setSwapInterval(1)         # Bật VSync (giảm xé hình)
    QSurfaceFormat.setDefaultFormat(surface_format)

    # 2. Khởi tạo QApplication
    app = QApplication(sys.argv)

    # 3. Khởi tạo hệ thống Live2D Core
    live2d.init()

    # 4. Lấy kích thước toàn bộ màn hình chính
    screen = app.primaryScreen()
    screen_geometry = screen.geometry()
    print(f"[Màn hình] Kích thước màn hình chính: {screen_geometry.width()}x{screen_geometry.height()}")

    # 5. Tạo cửa sổ Overlay và định dạng kích thước phủ toàn màn hình
    overlay = Live2DOverlayWindow()
    overlay.setGeometry(screen_geometry)
    overlay.show()

    # 6. Chạy vòng lặp sự kiện Qt
    exit_code = app.exec()

    # 7. Giải phóng toàn bộ tài nguyên Live2D trước khi kết thúc tiến trình
    try:
        live2d.dispose()
        print("[Live2D] Đã giải phóng tài nguyên Live2D thành công.")
    except Exception as e:
        print(f"[Live2D] Ngoại lệ khi dispose: {e}")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
