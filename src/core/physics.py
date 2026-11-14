"""
src/core/physics.py
-------------------
Quản lý mô phỏng vật lý của nhân vật trên màn hình:
- Tọa độ là PIXEL MÀN HÌNH thực tế (hoàn toàn tách biệt khỏi code vẽ OpenGL/Live2D).
- Nhân vật đứng trên đáy màn hình (sàn / taskbar).
- Mô phỏng trọng lực khi thả rơi tự do và dừng lại khi chạm sàn.
"""

from dataclasses import dataclass
from typing import Tuple, Callable, Optional


@dataclass
class PhysicsState:
    """Trạng thái động lực học tức thời của nhân vật."""
    x: float = 0.0              # Tọa độ tâm ngang của nhân vật (pixel màn hình)
    y: float = 0.0              # Tọa độ chân/đáy của nhân vật (pixel màn hình)
    vy: float = 0.0             # Vận tốc rơi theo trục dọc (pixel / giây)
    width: float = 300.0        # Chiều rộng ước tính của nhân vật
    height: float = 450.0       # Chiều cao ước tính của nhân vật
    is_dragged: bool = False    # Đang bị kéo bởi chuột
    is_falling: bool = False    # Đang rơi tự do do trọng lực


class PetPhysics:
    """
    Bộ xử lý vật lý độc lập cho Desktop Pet:
    - Trọng lực rơi tự do.
    - Va chạm sàn đáy màn hình.
    - Kéo nhấc và thả rơi.
    """

    def __init__(self,
                 screen_width: int = 1920,
                 screen_height: int = 1080,
                 gravity: float = 2400.0,
                 floor_margin: float = 10.0):
        self.screen_width: int = screen_width
        self.screen_height: int = screen_height
        self.gravity: float = gravity
        self.floor_margin: float = floor_margin

        # Vị trí sàn (đáy màn hình trừ đi khoảng đệm)
        self.floor_y: float = float(screen_height - floor_margin)

        # Trạng thái hiện tại: ban đầu đặt nhân vật ở góc phải đáy màn hình
        initial_x = screen_width * 0.82
        initial_y = self.floor_y
        self.state = PhysicsState(x=initial_x, y=initial_y)

        # Điểm lệch con trỏ khi bắt đầu kéo (để giữ nguyên vị trí bám tay)
        self._drag_offset_x: float = 0.0
        self._drag_offset_y: float = 0.0

        # Callback khi nhân vật chạm sàn sau khi rơi
        self.on_ground_hit: Optional[Callable[[], None]] = None

    def set_screen_bounds(self, width: int, height: int, floor_margin: Optional[float] = None) -> None:
        """Cập nhật lại kích thước màn hình khi có sự thay đổi độ phân giải."""
        self.screen_width = width
        self.screen_height = height
        if floor_margin is not None:
            self.floor_margin = floor_margin
        self.floor_y = float(height - self.floor_margin)

        # Đảm bảo nhân vật không bị rơi tụt xuống dưới sàn mới
        if self.state.y > self.floor_y and not self.state.is_dragged:
            self.state.y = self.floor_y
            self.state.vy = 0.0

    def update_dimensions(self, width: float, height: float) -> None:
        """Cập nhật kích thước khung bao của nhân vật (đo đạc từ Live2D Bounding Box)."""
        if width > 10.0 and height > 10.0:
            self.state.width = width
            self.state.height = height

    def start_drag(self, cursor_x: float, cursor_y: float) -> None:
        """Bắt đầu nhấc nhân vật lên bằng chuột."""
        self.state.is_dragged = True
        self.state.is_falling = False
        self.state.vy = 0.0

        # Tính khoảng lệch giữa con trỏ chuột và tọa độ nhân vật
        self._drag_offset_x = self.state.x - cursor_x
        self._drag_offset_y = self.state.y - cursor_y

    def drag_to(self, cursor_x: float, cursor_y: float) -> None:
        """Di chuyển nhân vật theo con trỏ chuột khi đang giữ chuột."""
        if not self.state.is_dragged:
            return

        target_x = cursor_x + self._drag_offset_x
        target_y = cursor_y + self._drag_offset_y

        # Giới hạn trong phạm vi màn hình
        half_w = self.state.width * 0.3
        self.state.x = max(half_w, min(self.screen_width - half_w, target_x))
        # Cho phép kéo lên cao, nhưng không kéo xuống sâu hơn sàn
        self.state.y = min(self.floor_y, target_y)

    def release_drag(self) -> bool:
        """
        Thả nhân vật sau khi kéo:
        - Nếu đang ở trên không -> bắt đầu rơi tự do (is_falling = True).
        - Nếu đã ở sàn -> đứng yên.
        Trả về True nếu nhân vật rơi.
        """
        self.state.is_dragged = False

        if self.state.y < self.floor_y - 2.0:
            self.state.is_falling = True
            self.state.vy = 0.0
            return True
        else:
            self.state.y = self.floor_y
            self.state.is_falling = False
            self.state.vy = 0.0
            return False

    def update(self, dt: float) -> None:
        """
        Cập nhật mô phỏng vật lý theo bước thời gian dt (giây):
        - Áp dụng gia tốc trọng lực khi rơi.
        - Xử lý va chạm khi tiếp đất.
        """
        if self.state.is_dragged:
            return

        if self.state.is_falling:
            # Gia tốc trọng lực
            self.state.vy += self.gravity * dt
            self.state.y += self.state.vy * dt

            # Kiểm tra va chạm sàn đáy màn hình
            if self.state.y >= self.floor_y:
                self.state.y = self.floor_y
                self.state.vy = 0.0
                self.state.is_falling = False

                # Gọi callback khi chạm đất
                if self.on_ground_hit is not None:
                    self.on_ground_hit()

    def get_screen_center_and_bottom(self) -> Tuple[float, float, float]:
        """
        Trả về:
        - center_x: Tâm ngang của nhân vật.
        - center_y: Tâm dọc của nhân vật (xấp xỉ).
        - bottom_y: Chân của nhân vật (tiếp xúc mặt sàn).
        """
        center_x = self.state.x
        bottom_y = self.state.y
        center_y = bottom_y - (self.state.height / 2.0)
        return center_x, center_y, bottom_y
