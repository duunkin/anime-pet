"""
src/behavior/state_machine.py
-----------------------------
Máy trạng thái hữu hạn (Finite State Machine) quản lý hành vi của Desktop Pet:
- Các trạng thái: IDLE, DRAGGED, FALLING, STARTLED, SLEEPING, ACTION.
- Hành vi IDLE xoay vòng ngẫu nhiên (chớp mắt, ngủ gật nhẹ, hành động ngẫu nhiên).
- Quản lý FPS thích ứng: 60 FPS khi hoạt động, ~15 FPS khi nghỉ/ngủ lâu.
"""

from enum import Enum
import random
from typing import Callable, Optional


class PetState(Enum):
    """Các trạng thái cơ bản của nhân vật."""
    IDLE = "IDLE"           # Đứng yên nhàn rỗi, tương tác nhẹ
    DRAGGED = "DRAGGED"     # Đang bị nhấc và kéo bởi chuột
    FALLING = "FALLING"     # Đang rơi tự do xuống sàn
    STARTLED = "STARTLED"   # Bị giật mình khi click chuột trái
    SLEEPING = "SLEEPING"   # Đang ngủ (chọn từ menu chuột phải)
    ACTION = "ACTION"       # Thực hiện hành động đặc biệt (ví dụ Nhảy)


class PetStateMachine:
    """
    Quản lý luồng trạng thái, chu kỳ hành vi ngẫu nhiên và chính sách FPS thích ứng.
    """

    def __init__(self, fps_idle_timeout_sec: float = 6.0):
        self.state: PetState = PetState.IDLE
        self.fps_idle_timeout: float = fps_idle_timeout_sec

        # Thời gian đếm
        self.state_time: float = 0.0        # Thời gian đã ở trạng thái hiện tại
        self.idle_time: float = 0.0         # Thời gian không có tương tác người dùng
        self.is_high_fps: bool = True       # Cờ FPS cao (True = 60 FPS, False = 15 FPS)

        # Bộ đếm cho hành động ngẫu nhiên khi IDLE (8 đến 16 giây một lần)
        self._next_idle_action_interval: float = random.uniform(8.0, 16.0)
        self._idle_action_timer: float = 0.0

        # Thời lượng tối đa cho các trạng thái tạm thời
        self.startled_duration: float = 1.6
        self.action_duration: float = 4.0

        # Callbacks ra ngoài tầng render / app
        self.on_state_changed: Optional[Callable[[PetState, PetState], None]] = None
        self.on_fps_mode_changed: Optional[Callable[[bool], None]] = None
        self.on_trigger_behavior: Optional[Callable[[str], None]] = None

    def change_state(self, new_state: PetState) -> None:
        """Chuyển sang trạng thái mới và kích hoạt các xử lý tương ứng."""
        if self.state == new_state:
            return

        old_state = self.state
        self.state = new_state
        self.state_time = 0.0

        # Khi chuyển sang bất kỳ trạng thái hoạt động nào -> kích hoạt ngay FPS cao
        if new_state in (PetState.DRAGGED, PetState.FALLING, PetState.STARTLED, PetState.ACTION):
            self.wake_up_fps()

        print(f"[State Machine] Chuyển trạng thái: {old_state.value} -> {new_state.value}")

        if self.on_state_changed is not None:
            self.on_state_changed(old_state, new_state)

    def notify_interaction(self) -> None:
        """Được gọi khi người dùng có thao tác chuột (hover vào, click, kéo)."""
        self.idle_time = 0.0
        self.wake_up_fps()

    def wake_up_fps(self) -> None:
        """Kích hoạt lại chế độ 60 FPS ngay lập tức."""
        if not self.is_high_fps:
            self.is_high_fps = True
            print("[FPS] Tương tác phát hiện -> Chuyển sang 60 FPS mượt mà.")
            if self.on_fps_mode_changed is not None:
                self.on_fps_mode_changed(True)

    def _enter_low_fps(self) -> None:
        """Hạ xuống chế độ 15 FPS khi nhàn rỗi lâu để tiết kiệm tài nguyên."""
        if self.is_high_fps:
            self.is_high_fps = False
            print("[FPS] Không có thao tác sau thời gian chờ -> Hạ xuống 15 FPS tiết kiệm pin/GPU.")
            if self.on_fps_mode_changed is not None:
                self.on_fps_mode_changed(False)

    def trigger_left_click(self) -> None:
        """Xử lý sự kiện click chuột trái: Giật mình (STARTLED)."""
        self.notify_interaction()
        self.change_state(PetState.STARTLED)
        if self.on_trigger_behavior is not None:
            self.on_trigger_behavior("startled")

    def trigger_drag_start(self) -> None:
        """Bắt đầu nhấc và kéo nhân vật."""
        self.notify_interaction()
        self.change_state(PetState.DRAGGED)
        if self.on_trigger_behavior is not None:
            self.on_trigger_behavior("dragged")

    def trigger_drag_release(self, is_falling: bool) -> None:
        """Thả chuột sau khi kéo."""
        self.notify_interaction()
        if is_falling:
            self.change_state(PetState.FALLING)
        else:
            self.change_state(PetState.IDLE)
            if self.on_trigger_behavior is not None:
                self.on_trigger_behavior("idle")

    def trigger_land(self) -> None:
        """Nhân vật chạm sàn sau khi rơi."""
        self.change_state(PetState.IDLE)
        if self.on_trigger_behavior is not None:
            self.on_trigger_behavior("idle")

    def trigger_sleep_menu(self) -> None:
        """Người dùng chọn 'Ngủ' từ menu."""
        self.notify_interaction()
        self.change_state(PetState.SLEEPING)
        if self.on_trigger_behavior is not None:
            self.on_trigger_behavior("sleep")

    def trigger_dance_menu(self) -> None:
        """Người dùng chọn 'Nhảy' từ menu."""
        self.notify_interaction()
        self.change_state(PetState.ACTION)
        if self.on_trigger_behavior is not None:
            self.on_trigger_behavior("dance")

    def update(self, dt: float, motion_finished: bool = False) -> None:
        """
        Cập nhật logic trạng thái theo bước thời gian dt (giây):
        - Quản lý thời gian kết thúc của STARTLED và ACTION.
        - Xoay vòng hành vi ngẫu nhiên khi IDLE.
        - Điều phối chế độ FPS thích ứng.
        """
        self.state_time += dt
        self.idle_time += dt

        # 1. Quản lý trạng thái STARTLED: kết thúc sau thời gian hoặc khi animation xong
        if self.state == PetState.STARTLED:
            if self.state_time >= self.startled_duration or (motion_finished and self.state_time > 0.5):
                self.change_state(PetState.IDLE)
                if self.on_trigger_behavior is not None:
                    self.on_trigger_behavior("idle")

        # 2. Quản lý trạng thái ACTION (Nhảy): kết thúc sau thời gian hoặc khi animation xong
        elif self.state == PetState.ACTION:
            if self.state_time >= self.action_duration or (motion_finished and self.state_time > 1.0):
                self.change_state(PetState.IDLE)
                if self.on_trigger_behavior is not None:
                    self.on_trigger_behavior("idle")

        # 3. Quản lý trạng thái IDLE: xoay vòng ngẫu nhiên các cử chỉ
        elif self.state == PetState.IDLE:
            self._idle_action_timer += dt
            if self._idle_action_timer >= self._next_idle_action_interval:
                self._idle_action_timer = 0.0
                self._next_idle_action_interval = random.uniform(8.0, 16.0)

                # Chọn ngẫu nhiên giữa: ngủ gật nhẹ (ngái ngủ) hoặc đổi dáng cử động ngẫu nhiên
                action_choice = random.choice(["idle_motion", "drowsy"])
                if action_choice == "drowsy":
                    # Ngủ gật nhẹ / biểu cảm lơ đãng
                    if self.on_trigger_behavior is not None:
                        self.on_trigger_behavior("sleep")
                else:
                    # Chạy motion idle ngẫu nhiên khác
                    if self.on_trigger_behavior is not None:
                        self.on_trigger_behavior("idle")

        # 4. Điều phối FPS thích ứng: Nếu ở IDLE hoặc SLEEPING lâu -> hạ FPS
        if self.state in (PetState.IDLE, PetState.SLEEPING):
            if self.idle_time >= self.fps_idle_timeout:
                self._enter_low_fps()
        else:
            self.wake_up_fps()
