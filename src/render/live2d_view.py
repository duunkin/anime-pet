"""
src/render/live2d_view.py
-------------------------
Quản lý tầng vẽ và tương tác trực tiếp với Live2D Cubism SDK (live2d-py):
- Khởi tạo OpenGL context cho Live2D (glInit).
- Nạp model và shader render.
- Đồng bộ vị trí từ hệ tọa độ pixel màn hình sang hệ tọa độ NDC của Live2D.
- Hitbox calculation cho cơ chế click xuyên thấu.
- Điều khiển cử động mắt và mặt nhìn theo con trỏ chuột khi con trỏ ở gần.
"""

from typing import Optional, Tuple
import os
import live2d
from OpenGL import GL

from src.core.character import CharacterProfile


class Live2DView:
    """
    Lớp điều khiển hiển thị và hoạt hình Live2D Model.
    """

    def __init__(self, character: CharacterProfile):
        self.character: CharacterProfile = character
        self.model: Optional[live2d.Model] = None

        # Khung bao giới hạn trong không gian model space (min_x, min_y, max_x, max_y)
        self.model_bounds: Optional[Tuple[float, float, float, float]] = None

        # Tọa độ nhìn hiện tại của mắt/mặt
        self._current_look_x: float = 0.0
        self._current_look_y: float = 0.0

    def initialize_gl(self) -> bool:
        """
        Khởi tạo môi trường OpenGL của Live2D và nạp model.
        BẮT BUỘC được gọi bên trong context OpenGL hợp lệ (ví dụ initializeGL của QOpenGLWidget).
        """
        print("[Live2D View] Khởi tạo OpenGL Shaders của Live2D SDK...")
        live2d.glInit()

        if not os.path.exists(self.character.model3_path):
            print(f"[Live2D View LỖI] Không tìm thấy file model: {self.character.model3_path}")
            return False

        try:
            self.model = live2d.Model()
            self.model.LoadModelJson(self.character.model3_path, create_renderer=True)
            print(f"[Live2D View] Nạp thành công model nhân vật: {self.character.name}")

            # Tính toán Bounding Box của nhân vật trong không gian model space
            self._compute_model_bounds()

            # Bật các cơ chế tự động của Cubism SDK
            self.model.SetAutoBlink(True)
            self.model.SetAutoBreath(True)

            # Phát motion idle ban đầu
            self.play_behavior("idle")

            return True
        except Exception as e:
            print(f"[Live2D View LỖI] Ngoại lệ khi nạp model: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _compute_model_bounds(self) -> None:
        """
        Quét các đỉnh drawable để tính Bounding Box bao quanh toàn bộ nhân vật.
        """
        if self.model is None:
            return

        self.model.Update()
        min_x, max_x = float('inf'), float('-inf')
        min_y, max_y = float('inf'), float('-inf')

        try:
            drawable_count = len(self.model.GetDrawableIds())
            for i in range(drawable_count):
                verts = self.model.GetDrawableVertices(i)
                for j in range(0, len(verts), 2):
                    vx, vy = verts[j], verts[j + 1]
                    if vx < min_x: min_x = vx
                    if vx > max_x: max_x = vx
                    if vy < min_y: min_y = vy
                    if vy > max_y: max_y = vy

            # Thêm đệm an toàn 5%
            pad_x = (max_x - min_x) * 0.05
            pad_y = (max_y - min_y) * 0.05
            self.model_bounds = (min_x - pad_x, min_y - pad_y, max_x + pad_x, max_y + pad_y)
        except Exception as exc:
            print(f"[Live2D View] Cảnh báo khi tính bounding box: {exc}")
            self.model_bounds = (-1.0, -1.0, 1.0, 1.0)

    def resize(self, width: int, height: int) -> None:
        """Đồng bộ viewport khi cửa sổ thay đổi kích thước."""
        GL.glViewport(0, 0, width, height)
        if self.model is not None:
            self.model.Resize(width, height)
            self.model.SetScale(self.character.scale)

    def set_screen_position(self, center_x: float, bottom_y: float, screen_w: int, screen_h: int) -> None:
        """
        Quy đổi tọa độ màn hình pixel (từ module Physics) sang tọa độ NDC của Live2D:
        - NDC X: [-1.0 (trái), 1.0 (phải)]
        - NDC Y: [-1.0 (đáy), 1.0 (đỉnh)]
        """
        if self.model is None or screen_w <= 0 or screen_h <= 0:
            return

        # Tính toán ước lượng vị trí tâm của nhân vật
        approx_height_px = screen_h * self.character.scale
        center_y = bottom_y - (approx_height_px * 0.5)

        # Chuyển đổi sang NDC
        ndc_x = (center_x / screen_w) * 2.0 - 1.0
        # Lưu ý: Trục Y của màn hình Windows hướng xuống, còn Live2D NDC hướng lên
        ndc_y = 1.0 - (center_y / screen_h) * 2.0

        self.model.SetOffset(ndc_x, ndc_y)

    def get_screen_bounds_physical(self, phys_w: float, phys_h: float) -> Optional[Tuple[float, float, float, float]]:
        """
        Tính toán tọa độ khung bao nhân vật trên màn hình vật lý (Physical Pixels)
        để phục vụ kiểm tra hit-test click-through.
        """
        if self.model is None or self.model_bounds is None:
            return None

        min_xm, min_ym, max_xm, max_ym = self.model_bounds
        try:
            mvp = self.model.GetMvp()
            # Column-major MVP matrix
            ndc_x1 = min_xm * mvp[0] + mvp[12]
            ndc_x2 = max_xm * mvp[0] + mvp[12]
            ndc_y1 = min_ym * mvp[5] + mvp[13]
            ndc_y2 = max_ym * mvp[5] + mvp[13]

            screen_x1 = (ndc_x1 + 1.0) / 2.0 * phys_w
            screen_x2 = (ndc_x2 + 1.0) / 2.0 * phys_w
            screen_y1 = (1.0 - ndc_y2) / 2.0 * phys_h
            screen_y2 = (1.0 - ndc_y1) / 2.0 * phys_h

            return (min(screen_x1, screen_x2), min(screen_y1, screen_y2),
                    max(screen_x1, screen_x2), max(screen_y1, screen_y2))
        except Exception:
            return None

    def update_look_at(self, cursor_phys_x: float, cursor_phys_y: float,
                       box: Optional[Tuple[float, float, float, float]],
                       max_distance_px: float) -> None:
        """
        Điều khiển hướng nhìn của mắt và quay đầu theo con trỏ chuột:
        - Khi con trỏ ở trong phạm vi max_distance_px: mắt và mặt nhìn theo.
        - Khi con trỏ ở xa: từ từ đưa mắt nhìn thẳng tự nhiên.
        """
        if self.model is None:
            return

        if box is None:
            target_x, target_y = 0.0, 0.0
        else:
            x1, y1, x2, y2 = box
            # Ước lượng vị trí vùng mắt / đầu (khoảng 30% từ đỉnh đầu xuống)
            eye_x = (x1 + x2) * 0.5
            eye_y = y1 + (y2 - y1) * 0.3

            dx = cursor_phys_x - eye_x
            dy = cursor_phys_y - eye_y
            dist = (dx * dx + dy * dy) ** 0.5

            if dist <= max_distance_px and max_distance_px > 0:
                # Chuẩn hóa về đoạn [-1.0, 1.0]
                target_x = max(-1.0, min(1.0, dx / (max_distance_px * 0.5)))
                # Con trỏ ở dưới -> mắt nhìn xuống (Y âm)
                target_y = max(-1.0, min(1.0, -dy / (max_distance_px * 0.5)))
            else:
                # Con trỏ ở xa -> nhìn chính diện
                target_x, target_y = 0.0, 0.0

        # Làm mượt chuyển động nhìn (lerp)
        smoothing = 0.25
        self._current_look_x += (target_x - self._current_look_x) * smoothing
        self._current_look_y += (target_y - self._current_look_y) * smoothing

        # 1. Thử gọi Drag của Cubism SDK
        try:
            self.model.Drag(self._current_look_x, self._current_look_y)
        except Exception:
            pass

        # 2. Bổ sung gán trực tiếp các tham số góc quay đầu và nhãn cầu mắt
        try:
            self.model.SetParamById("ParamAngleX", self._current_look_x * 20.0)
            self.model.SetParamById("ParamAngleY", self._current_look_y * 20.0)
            self.model.SetParamById("ParamEyeBallX", self._current_look_x * 0.8)
            self.model.SetParamById("ParamEyeBallY", self._current_look_y * 0.8)
        except Exception:
            pass

    def play_behavior(self, behavior: str, priority: int = 3) -> bool:
        """Kích hoạt hành vi cử động / biểu cảm theo bảng ánh xạ character."""
        return self.character.play_behavior(self.model, behavior, priority)

    def is_motion_finished(self) -> bool:
        """Kiểm tra xem motion hiện tại đã kết thúc hay chưa."""
        if self.model is None:
            return True
        try:
            return self.model.IsMotionFinished()
        except Exception:
            return True

    def set_hover_highlight(self, active: bool) -> None:
        """Hiệu ứng thị giác khi con trỏ hover trên nhân vật."""
        if self.model is None:
            return
        try:
            part_count = self.model.GetPartCount()
            r, g, b = (0.12, 0.12, 0.20) if active else (0.0, 0.0, 0.0)
            for i in range(part_count):
                self.model.SetPartScreenColor(i, r, g, b, 1.0)
        except Exception:
            pass

    def render_frame(self) -> None:
        """Xóa nền trong suốt, cập nhật logic và vẽ model."""
        # Xóa buffer với alpha = 0.0 để trong suốt hoàn toàn
        live2d.clearBuffer(0.0, 0.0, 0.0, 0.0)

        if self.model is not None:
            self.model.Update()
            self.model.Draw()

    def release(self) -> None:
        """Giải phóng tài nguyên OpenGL của model."""
        try:
            if self.model is not None:
                self.model.DestroyRenderer()
                self.model = None
            live2d.glRelease()
            print("[Live2D View] Đã giải phóng tài nguyên OpenGL.")
        except Exception as e:
            print(f"[Live2D View] Ngoại lệ khi giải phóng: {e}")
