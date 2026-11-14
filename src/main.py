"""
src/main.py
-----------
Điểm khởi chạy chính của ứng dụng Anime Desktop Pet:
- Kích hoạt Per-Monitor DPI Awareness v2 trên Windows 10/11.
- Cấu hình QSurfaceFormat hỗ trợ kênh alpha 8-bit và VSync cho cửa sổ trong suốt.
- Khởi tạo Cubism SDK (live2d.init()).
- Nạp nhân vật từ characters/<tên>/character.json.
- Phối hợp các hệ thống: Physics, StateMachine, Live2DView và Overlay.
- TÁI CẤU TRÚC HIỆU NĂNG: Cửa sổ Overlay chỉ có kích thước vừa khít nhân vật + lề 40px
  (thay vì phủ toàn màn hình gây lag), tự di chuyển theo tọa độ PetPhysics mỗi frame.
- Dọn dẹp tài nguyên và giải phóng Live2D khi kết thúc.
"""

import os
import sys

# Đảm bảo project root luôn nằm trong sys.path khi chạy từ bất kỳ thư mục nào
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import argparse
import ctypes

from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication

import live2d

from src.config.settings import AppSettings
from src.core.character import CharacterProfile
from src.core.physics import PetPhysics
from src.behavior.state_machine import PetStateMachine
from src.render.live2d_view import Live2DView
from src.render.overlay import Live2DPetOverlay


def enable_dpi_awareness() -> None:
    """Kích hoạt chế độ Per-Monitor DPI Awareness v2 trên Windows 10/11."""
    if sys.platform != "win32":
        return

    # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
    DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        print("[DPI] Đã kích hoạt Per-Monitor DPI Awareness v2 thành công.")
        return
    except Exception:
        pass

    try:
        # Fallback Windows 8.1 / 10 bản cũ: PROCESS_PER_MONITOR_DPI_AWARE = 2
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        print("[DPI] Đã kích hoạt Shcore SetProcessDpiAwareness thành công.")
    except Exception:
        pass


def configure_surface_format(vsync: bool = True) -> None:
    """
    Cấu hình QSurfaceFormat toàn cục với Alpha buffer 8-bit và điều khiển VSync.
    BẮT BUỘC thiết lập trước khi tạo QApplication hoặc bất kỳ QOpenGLWidget nào
    để đảm bảo khả năng hiển thị nền trong suốt trên Windows DWM.
    """
    fmt = QSurfaceFormat()
    fmt.setAlphaBufferSize(8)      # 8-bit Alpha channel cho độ trong suốt
    fmt.setDepthBufferSize(24)     # 24-bit Depth buffer
    fmt.setStencilBufferSize(8)   # 8-bit Stencil buffer cho mask clipping
    fmt.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
    fmt.setSwapInterval(1 if vsync else 0)  # 1: Bật VSync, 0: Tắt VSync để thử nghiệm
    QSurfaceFormat.setDefaultFormat(fmt)


def main() -> None:
    """Hàm khởi tạo và chạy ứng dụng chính."""
    # 1. Xử lý tham số dòng lệnh
    parser = argparse.ArgumentParser(description="Anime Desktop Pet - Tối ưu hóa hiệu năng cửa sổ nhỏ")
    parser.add_argument("--character", "-c", type=str, default="Hiyori",
                        help="Tên thư mục nhân vật trong characters/ (mặc định: Hiyori)")
    parser.add_argument("--auto-exit", type=int, default=0,
                        help="Tự động thoát sau N giây (dành cho kiểm thử/CI, mặc định 0: không thoát)")
    args = parser.parse_args()

    print("=================================================================")
    print(" ANIME DESKTOP PET - TÁI CẤU TRÚC OVERLAY CỬA SỔ NHỎ (TỐI ƯU FPS)")
    print(f" Nhân vật: {args.character}")
    print(" Thao tác:")
    print(" - Chuột: Di chuyển lại gần để mắt nhìn theo (kể cả khi chuột ở ngoài cửa sổ)")
    print(" - Click trái: Giật mình")
    print(" - Giữ chuột trái & kéo: Nhấc nhân vật lên; thả ra: rơi tự do")
    print(" - Click phải: Menu (Ngủ, Nhảy, Thoát)")
    print(" - Vùng trống (lề 40px): Click xuyên thấu xuống app bên dưới")
    print(" - Phím tắt: [Ctrl+Q] hoặc [Esc] để thoát khi cửa sổ hoạt động")
    print("=================================================================")

    # 2. Khởi tạo cấu hình ứng dụng
    settings = AppSettings(
        character_name=args.character,
        auto_exit_seconds=args.auto_exit
    )

    # 3. Bật DPI Awareness v2
    enable_dpi_awareness()

    # 4. Cấu hình QSurfaceFormat trước QApplication (đồng bộ VSync theo settings)
    configure_surface_format(vsync=settings.vsync)

    # 5. Khởi tạo Qt Application
    app = QApplication(sys.argv)

    # 6. Khởi tạo thư viện Live2D Core
    live2d.init()

    # 7. Khởi tạo Hồ sơ nhân vật
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    characters_dir = os.path.join(base_dir, settings.characters_dir)
    character_profile = CharacterProfile.load(characters_dir, settings.character_name)

    # Cập nhật scale tùy chỉnh của nhân vật nếu có
    if character_profile.scale:
        settings.default_scale = character_profile.scale

    # 8. Lấy kích thước màn hình chính (Logical Pixels)
    screen = app.primaryScreen()
    screen_geo = screen.geometry()
    screen_w = screen_geo.width()
    screen_h = screen_geo.height()
    dpr = screen.devicePixelRatio()
    print(f"[Màn hình] Kích thước: {screen_w}x{screen_h} (Logical Pixels), DPI Scale: {dpr * 100:.0f}%")

    # 9. Khởi tạo các module con (mỗi module một trách nhiệm)
    # PetPhysics hoàn toàn làm việc với hệ tọa độ màn hình (Logical Pixels)
    physics = PetPhysics(
        screen_width=screen_w,
        screen_height=screen_h,
        gravity=settings.gravity,
        floor_margin=settings.floor_margin_px
    )

    state_machine = PetStateMachine(
        fps_idle_timeout_sec=settings.fps_idle_timeout_sec
    )

    live2d_view = Live2DView(character=character_profile)

    # 10. Tạo và khởi chạy cửa sổ Overlay nhỏ (không phủ màn hình)
    overlay = Live2DPetOverlay(
        settings=settings,
        physics=physics,
        state_machine=state_machine,
        live2d_view=live2d_view
    )

    # Tính toán vị trí hình học ban đầu trước khi show (đặt tại vị trí ban đầu của pet)
    center_x, center_y, bottom_y = physics.get_screen_center_and_bottom()
    init_char_h = settings.character_height_px
    init_char_w = physics.state.width
    margin = settings.window_margin_px
    init_win_w = int(round(init_char_w + 2.0 * margin))
    init_win_h = int(round(init_char_h + 2.0 * margin))
    init_win_x = int(round(center_x - init_win_w / 2.0))
    init_win_y = int(round(bottom_y - (init_win_h - margin)))

    overlay.setGeometry(init_win_x, init_win_y, init_win_w, init_win_h)
    overlay.show()

    # 11. Chạy vòng lặp sự kiện Qt
    exit_code = app.exec()

    # 12. Giải phóng tài nguyên Live2D Core trước khi thoát tiến trình
    try:
        live2d.dispose()
        print("[Live2D] Đã giải phóng hoàn tất tài nguyên Live2D.")
    except Exception as e:
        print(f"[Live2D] Ngoại lệ khi dispose: {e}")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
