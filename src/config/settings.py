"""
src/config/settings.py
----------------------
Quản lý cấu hình toàn bộ ứng dụng Anime Desktop Pet.
Sử dụng dataclass để đảm bảo tính tường minh, có type hinting và không dùng biến toàn cục lộn xộn.
"""

from dataclasses import dataclass, field
import os


@dataclass
class AppSettings:
    """
    Chứa toàn bộ thông số cấu hình của ứng dụng Desktop Pet.
    """
    # Tên thư mục nhân vật mặc định trong characters/
    character_name: str = "Hiyori"
    characters_dir: str = "characters"

    # Tần số quét khung hình (FPS)
    target_fps: int = 60          # FPS khi hoạt động hoặc có tương tác
    idle_fps: int = 15            # FPS thấp khi ở trạng thái nghỉ / ngủ lâu để tiết kiệm điện và CPU/GPU
    fps_idle_timeout_sec: float = 6.0  # Thời gian không thao tác (giây) để hạ về FPS thấp

    # Thông số vật lý (tính theo pixel màn hình)
    gravity: float = 2400.0       # Gia tốc trọng lực (pixels / s^2)
    drag_threshold_px: float = 10.0  # Khoảng cách tối thiểu để phân biệt click thường và kéo thả
    floor_margin_px: float = 10.0 # Khoảng cách an toàn so với đáy màn hình / taskbar

    # Tương tác mắt nhìn chuột
    eye_tracking_distance_px: float = 500.0  # Khoảng cách con trỏ (pixel) mà pet bắt đầu chú ý nhìn theo
    cursor_poll_interval_ms: int = 30       # Tần số kiểm tra vị trí con trỏ chuột (~33 Hz)

    # Tỉ lệ hiển thị mặc định của model
    default_scale: float = 0.65

    # Tự động thoát an toàn (fallback) sau N giây (0 = chạy vô thời hạn)
    auto_exit_seconds: int = 0

    def get_character_config_path(self, character_name: str | None = None) -> str:
        """Lấy đường dẫn đầy đủ tới file character.json của nhân vật."""
        name = character_name or self.character_name
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        return os.path.join(base_dir, self.characters_dir, name, "character.json")
