"""
spike3_windows.py
-----------------
Thử nghiệm kỹ thuật (Spike 3) cho ứng dụng Desktop Pet:
- Liệt kê các cửa sổ cấp cao nhất (Top-level Windows) đang hiển thị trên Windows 10/11.
- Loại bỏ các cửa sổ thu nhỏ (minimized), cửa sổ hệ thống ẩn (cloaked/invisible),
  cửa sổ không có tiêu đề, và cửa sổ của chính chương trình/console.
- Mỗi 0.5 giây in ra: Tiêu đề, tọa độ (left, top, right, bottom), và đánh dấu cửa sổ
  nào đang active (foreground).
- Sử dụng GetWindowRect kết hợp DwmGetWindowAttribute (DWMWA_EXTENDED_FRAME_BOUNDS = 9)
  để lấy tọa độ chính xác thực tế của cửa sổ, loại bỏ phần viền bóng đổ vô hình (~7-8px)
  trên Windows 10/11.
- Bật Per-Monitor DPI Awareness v2 để tọa độ pixel vật lý khớp hoàn toàn với tọa độ
  của PySide6 / OpenGL overlay.
- Tính toán và ghi chú chi tiết vị trí tọa độ để nhân vật Desktop Pet "đứng trên thanh tiêu đề"
  (Title Bar) của cửa sổ đang active.
"""

import os
import sys
import time
import ctypes
from ctypes import wintypes
from typing import List, Optional, Tuple, NamedTuple

# ==============================================================================
# 1. BẬT PER-MONITOR DPI AWARENESS (ĐỒNG BỘ TỌA ĐỘ VỚI PYSIDE6)
# ==============================================================================
# Bắt buộc bật trước bất kỳ lệnh gọi API đồ họa hoặc cửa sổ nào.
# Tránh hiện tượng Windows tự ảo hóa DPI (DPI Virtualization) làm sai lệch tọa độ
# giữa tiến trình Win32 này và cửa sổ PySide6/QOpenGLWidget.
def enable_dpi_awareness() -> None:
    """Kích hoạt chế độ Per-Monitor DPI Awareness v2 trên Windows 10/11."""
    if sys.platform != "win32":
        return

    # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
    DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        # print("[DPI] Đã bật Per-Monitor DPI Awareness v2 thành công.")
        return
    except Exception:
        pass

    try:
        # Fallback Windows 8.1 / 10 bản cũ: PROCESS_PER_MONITOR_DPI_AWARE = 2
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        # print("[DPI] Đã bật Shcore SetProcessDpiAwareness thành công.")
        return
    except Exception:
        pass

    try:
        # Fallback Windows Vista / 7: SetProcessDPIAware
        ctypes.windll.user32.SetProcessDPIAware()
        # print("[DPI] Đã bật SetProcessDPIAware thành công.")
    except Exception:
        pass


# ==============================================================================
# 2. ĐỊNH NGHĨA CÁC CẤU TRÚC VÀ HẰNG SỐ WIN32 / DWM API
# ==============================================================================
user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi
kernel32 = ctypes.windll.kernel32

# DWMWA_EXTENDED_FRAME_BOUNDS: Lấy bounding box thực tế của cửa sổ không kèm viền bóng DWM
DWMWA_EXTENDED_FRAME_BOUNDS: int = 9

# DWMWA_CLOAKED: Kiểm tra cửa sổ có bị Windows ẩn đi (ở Virtual Desktop khác hoặc UWP suspended)
DWMWA_CLOAKED: int = 14

# Chiều cao thanh tiêu đề hệ thống (SM_CYCAPTION)
SM_CYCAPTION: int = 4


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]

    def to_tuple(self) -> Tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


class WindowInfo(NamedTuple):
    hwnd: int
    title: str
    rect: RECT
    is_foreground: bool
    # Tọa độ gợi ý để Pet đứng trên mép trên thanh tiêu đề: (x, y)
    pet_stand_pos: Tuple[int, int]


# ==============================================================================
# 3. HÀM TÍNH TOÁN: VỊ TRÍ NHÂN VẬT ĐỨNG TRÊN THANH TIÊU ĐỀ
# ==============================================================================
def calculate_pet_titlebar_stand_position(rect: RECT, align: str = "right_offset") -> Tuple[int, int]:
    """
    ============================================================================
    PHẦN NÀY DÙNG ĐỂ LÀM 'NHÂN VẬT ĐỨNG TRÊN THANH TIÊU ĐỀ':
    ============================================================================
    Nguyên lý:
    1. Trục Y (Độ cao):
       - Mép trên cùng của thanh tiêu đề cửa sổ chính là `rect.top`.
       - Để chân của Pet tiếp xúc với mặt trên của thanh tiêu đề:
         `pet_foot_y = rect.top`
       - Nếu muốn Pet ngồi lọt vào bên trong thanh tiêu đề:
         `pet_foot_y = rect.top + titlebar_height` (thường titlebar cao ~30px).

    2. Trục X (Vị trí ngang):
       - 'center': Đứng chính giữa thanh tiêu đề:
         `x = rect.left + rect.width / 2`
       - 'right_offset': Đứng lệch về góc trên bên phải của cửa sổ, né cụm nút
         Minimize / Maximize / Close (thường cụm nút này chiếm ~140px bên phải):
         `x = rect.right - 160`
       - 'left_offset': Đứng lệch bên trái (sau icon ứng dụng và tên app):
         `x = rect.left + 80`

    3. Quy đổi sang Live2D Model Offset trong PySide6:
       Khi đã có tọa độ pixel (X_screen, Y_screen), quy đổi sang hệ tọa độ NDC [-1, 1]
       của Live2D:
         x_ndc = (2.0 * X_screen / Screen_Width) - 1.0
         y_ndc = 1.0 - (2.0 * Y_screen / Screen_Height)
       Gán vào Live2D: `model.SetOffset(x_ndc, y_ndc)`.
    ============================================================================
    """
    foot_y = rect.top

    if align == "center":
        stand_x = int(rect.left + rect.width / 2)
    elif align == "left_offset":
        stand_x = int(rect.left + 80)
    else:  # "right_offset" (khuyến nghị cho desktop pet để không che tiêu đề)
        stand_x = int(rect.right - 160)

    # Đảm bảo stand_x không vượt ra ngoài biên trái của cửa sổ
    if stand_x < rect.left + 20:
        stand_x = rect.left + 20

    return (stand_x, foot_y)


# ==============================================================================
# 4. HÀM LẤY TỌA ĐỘ CHÍNH XÁC (DWM EXTENDED FRAME BOUNDS)
# ==============================================================================
def get_accurate_window_rect(hwnd: int) -> Optional[RECT]:
    """
    Lấy tọa độ cửa sổ chính xác bằng DwmGetWindowAttribute.
    
    Khắc phục lỗi viền bóng trên Windows 10/11:
    - GetWindowRect truyền thống sẽ cộng thêm khoảng 7-8 pixel vô hình của bóng đổ DWM.
    - DwmGetWindowAttribute với DWMWA_EXTENDED_FRAME_BOUNDS trả về đúng vùng nhìn thấy thật.
    """
    rect = RECT()
    hr = dwmapi.DwmGetWindowAttribute(
        hwnd,
        DWMWA_EXTENDED_FRAME_BOUNDS,
        ctypes.byref(rect),
        ctypes.sizeof(rect),
    )
    if hr == 0:
        return rect

    # Fallback nếu DWM không khả dụng
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return rect

    return None


# ==============================================================================
# 5. HÀM QUÉT VÀ LỌC DANH SÁCH CỬA SỔ (ENUMWINDOWS)
# ==============================================================================
# Danh sách các tiêu đề hoặc class hệ thống cần bỏ qua
IGNORED_TITLES = {
    "Program Manager",
    "Settings",
    "Windows Input Experience",
    "Task Switching",
    "Windows Shell Experience Host",
}


def ensure_default_desktop() -> None:
    """Đảm bảo thread hiện tại gắn kết với Desktop 'default' của người dùng."""
    try:
        h_desk = user32.OpenDesktopW("default", 0, False, 0x01FF)
        if h_desk:
            user32.SetThreadDesktop(h_desk)
    except Exception:
        pass


def get_top_level_windows() -> List[WindowInfo]:
    """
    Quét và trả về danh sách các cửa sổ hợp lệ:
    - Đang hiển thị (IsWindowVisible).
    - Không bị thu nhỏ (not IsIconic).
    - Không bị ẩn bởi DWM Cloak (không thuộc Virtual Desktop khác).
    - Có tiêu đề hợp lệ.
    - Không phải cửa sổ của chính chương trình/console.
    """
    ensure_default_desktop()

    foreground_hwnd = user32.GetForegroundWindow()
    console_hwnd = kernel32.GetConsoleWindow()
    current_pid = os.getpid()

    result: List[WindowInfo] = []

    def enum_window_callback(hwnd: int, lparam: int) -> bool:
        # 1. Bỏ qua nếu cửa sổ không hiển thị hoặc đang bị thu nhỏ xuống Taskbar
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True

        # 2. Bỏ qua cửa sổ bị DWM Cloaked (ở Virtual Desktop khác hoặc ứng dụng UWP chạy ngầm)
        cloaked = ctypes.c_int(0)
        hr = dwmapi.DwmGetWindowAttribute(
            hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
        )
        if hr == 0 and cloaked.value != 0:
            return True

        # 3. Bỏ qua cửa sổ của chính tiến trình này hoặc cửa sổ Console
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == current_pid or (console_hwnd and hwnd == console_hwnd):
            return True

        # 4. Kiểm tra tiêu đề cửa sổ
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True

        title_buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buf, length + 1)
        title = title_buf.value.strip()

        if not title or title in IGNORED_TITLES:
            return True

        # 5. Lấy tọa độ chính xác qua DWMWA_EXTENDED_FRAME_BOUNDS
        rect = get_accurate_window_rect(hwnd)
        if rect is None:
            return True

        # 6. Loại bỏ các cửa sổ có kích thước rác/quá nhỏ (ví dụ tooltip, background helper)
        if rect.width < 100 or rect.height < 60:
            return True

        is_fg = (hwnd == foreground_hwnd)
        pet_stand_pos = calculate_pet_titlebar_stand_position(rect, align="right_offset")

        result.append(WindowInfo(
            hwnd=hwnd,
            title=title,
            rect=rect,
            is_foreground=is_fg,
            pet_stand_pos=pet_stand_pos
        ))
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(enum_window_callback), 0)

    # Đưa cửa sổ Foreground lên đầu danh sách để dễ theo dõi
    result.sort(key=lambda w: not w.is_foreground)
    return result


# ==============================================================================
# 6. VÒNG LẶP CHÍNH (MAIN LOOP - MỖI 0.5 GIÂY)
# ==============================================================================
def main() -> None:
    # 1. Bật Per-Monitor DPI Awareness
    enable_dpi_awareness()

    print("=" * 80)
    print(" THEO DÕI VỊ TRÍ CỬA SỔ TOP-LEVEL TRÊN WINDOWS (SPIKE 3)")
    print(" - Cập nhật mỗi 0.5 giây. Nhấn Ctrl+C để dừng.")
    print(" - Dùng DWMWA_EXTENDED_FRAME_BOUNDS để loại bỏ phần viền bóng mờ.")
    print(" - Tính sẵn vị trí chân Pet đứng trên thanh tiêu đề (Stand Pos).")
    print("=" * 80)
    time.sleep(1.0)

    cycle_count = 0

    try:
        while True:
            cycle_count += 1
            windows = get_top_level_windows()

            # In tiêu đề mỗi chu kỳ
            timestamp = time.strftime("%H:%M:%S")
            print(f"\n--- [Chu kỳ #{cycle_count:04d} lúc {timestamp}] Tìm thấy {len(windows)} cửa sổ hợp lệ ---")
            print(f"{'TRẠNG THÁI':<11} | {'HWND':<10} | {'TỌA ĐỘ (L, T, R, B)':<24} | {'PET STAND (X, Y)':<18} | {'TIÊU ĐỀ'}")
            print("-" * 105)

            for win in windows:
                status = "[ACTIVE] *" if win.is_foreground else "         "
                rect_str = f"({win.rect.left}, {win.rect.top}, {win.rect.right}, {win.rect.bottom})"
                stand_str = f"({win.pet_stand_pos[0]}, {win.pet_stand_pos[1]})"

                # Cắt ngắn tiêu đề nếu quá dài để hiển thị trên 1 dòng
                short_title = win.title if len(win.title) <= 40 else win.title[:37] + "..."
                print(f"{status:<11} | 0x{win.hwnd:08X} | {rect_str:<24} | {stand_str:<18} | {short_title}")

            time.sleep(0.5)

    except KeyboardInterrupt:
        print("\n\n[Dừng] Đã nhận tín hiệu Ctrl+C. Kết thúc chương trình.")


if __name__ == "__main__":
    main()
