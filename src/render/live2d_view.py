"""
src/render/live2d_view.py
-------------------------
Quản lý tầng vẽ và tương tác trực tiếp với Live2D Cubism SDK (live2d-py):
- Khởi tạo OpenGL context cho Live2D (glInit).
- Nạp model và shader render.
- Thiết lập bố cục trong cửa sổ nhỏ: Canh chỉnh model khớp chính xác với lề (margin 40px mỗi phía).
- Tính toán Hitbox theo không gian Physical Pixels cục bộ của cửa sổ nhỏ.
- Điều khiển cử động mắt và mặt nhìn theo con trỏ chuột (kể cả khi con trỏ ở xa ngoài cửa sổ).
"""

from typing import Optional, Tuple
import os
import math
import live2d
from OpenGL import GL

from src.core.character import CharacterProfile


class Live2DView:
    """
    Lớp điều khiển hiển thị và hoạt hình Live2D Model bên trong cửa sổ overlay nhỏ.
    """

    def __init__(self, character: CharacterProfile):
        self.character: CharacterProfile = character
        self.model: Optional[live2d.Model] = None

        # Khung bao giới hạn trong không gian model space (min_x, min_y, max_x, max_y)
        self.model_bounds: Optional[Tuple[float, float, float, float]] = None

        # Hướng nhìn mục tiêu và hướng nhìn hiện tại của mắt/mặt
        self._target_look_x: float = 0.0
        self._target_look_y: float = 0.0
        self._current_look_x: float = 0.0
        self._current_look_y: float = 0.0

    def initialize_gl(self) -> bool:
        """
        Khởi tạo môi trường OpenGL của Live2D và nạp model.
        BẮT BUỘC được gọi bên trong context OpenGL hợp lệ (initializeGL của QOpenGLWidget).
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
        Quét các đỉnh drawable để tính Bounding Box bao quanh toàn bộ nhân vật
        trong không gian tọa độ Model Space.
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

            # Thêm đệm an toàn 5% cho tóc/quần áo khi cử động
            pad_x = (max_x - min_x) * 0.05
            pad_y = (max_y - min_y) * 0.05
            self.model_bounds = (min_x - pad_x, min_y - pad_y, max_x + pad_x, max_y + pad_y)
        except Exception as exc:
            print(f"[Live2D View] Cảnh báo khi tính bounding box: {exc}")
            self.model_bounds = (-0.5, -1.0, 0.5, 1.0)

    def get_model_aspect_ratio(self) -> float:
        """
        Trả về tỉ lệ bề ngang / bề cao (width / height) của nhân vật từ model_bounds.
        """
        if self.model_bounds is None:
            return 0.45
        mb_w = self.model_bounds[2] - self.model_bounds[0]
        mb_h = self.model_bounds[3] - self.model_bounds[1]
        if mb_h <= 0.001:
            return 0.45
        return mb_w / mb_h

    def setup_layout(self, logical_w: int, logical_h: int, dpr: float, margin_px: float = 40.0) -> None:
        """
        Cấu hình kích thước viewport và căn chỉnh vị trí model trong cửa sổ nhỏ:
        
        Quy đổi DPI:
        - logical_w, logical_h: Kích thước cửa sổ Qt (Logical Pixels).
        - dpr: Tỉ lệ Device Pixel Ratio (ví dụ 1.25 trên màn hình 125% DPI).
        - phys_w = logical_w * dpr, phys_h = logical_h * dpr: Kích thước OpenGL Framebuffer (Physical Pixels).
        - margin_phys = margin_px * dpr: Lề 40px quy đổi sang Physical Pixels.
        
        Nhân vật sẽ được đặt chính xác:
        - Cách mép trên đúng margin_phys.
        - Cách mép dưới đúng margin_phys.
        - Cách mép trái đúng margin_phys.
        - Cách mép phải đúng margin_phys.
        """
        if self.model is None or logical_w <= 0 or logical_h <= 0:
            return

        # 1. Kích thước vật lý của Viewport OpenGL (Physical Pixels)
        phys_w = int(round(logical_w * dpr))
        phys_h = int(round(logical_h * dpr))
        margin_phys = margin_px * dpr

        GL.glViewport(0, 0, phys_w, phys_h)
        self.model.Resize(phys_w, phys_h)

        if self.model_bounds is None:
            self._compute_model_bounds()

        mb = self.model_bounds
        if mb is None:
            return

        mb_w = mb[2] - mb[0]
        mb_h = mb[3] - mb[1]
        mb_left = mb[0]
        mb_bottom = mb[1]

        # 2. Chiều cao mong muốn của nhân vật trong viewport vật lý
        char_phys_h = max(10.0, phys_h - 2.0 * margin_phys)

        # 3. Tính scale để nhân vật khớp đúng chiều cao char_phys_h
        # Trong Cubism SDK: MVP[5] = (2.0 / canvas_h) * scale
        # Chiều cao pixel = mb_h * MVP[5] / 2.0 * phys_h = (mb_h / canvas_h) * scale * phys_h
        # Do đó: scale = (char_phys_h / phys_h) * (canvas_h / mb_h)
        canvas_w, canvas_h = self.model.GetCanvasSize()
        scale = (char_phys_h / phys_h) * (canvas_h / mb_h)
        self.model.SetScale(scale)
        self.model.Update()

        # 4. Tính offset để nhân vật cách đúng lề 40px ở 4 phía
        # Cubism SDK tự nhân offset_x với aspect ratio (phys_h / phys_w)
        mvp = self.model.GetMvp()
        aspect = float(phys_h) / float(phys_w)

        # Trục X: Căn mép trái cách lề trái đúng margin_phys
        target_ndc_x = 2.0 * (margin_phys / phys_w) - 1.0
        off_x = (target_ndc_x - mb_left * mvp[0]) / aspect

        # Trục Y: Căn mép dưới cách lề dưới đúng margin_phys
        target_ndc_y = 2.0 * (margin_phys / phys_h) - 1.0
        off_y = target_ndc_y - mb_bottom * mvp[5]

        self.model.SetOffset(off_x, off_y)
        self.model.Update()

    def get_screen_bounds_physical(self, phys_w: float, phys_h: float) -> Optional[Tuple[float, float, float, float]]:
        """
        Tính toán tọa độ khung bao nhân vật trong KHÔNG GIAN CỤC BỘ CỦA CỬA SỔ (Local Physical Pixels).
        Trả về (left, top, right, bottom) phục vụ kiểm tra hit-test và eye-tracking.
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

    def set_look_target(self, cursor_local_phys_x: float, cursor_local_phys_y: float,
                        box: Optional[Tuple[float, float, float, float]],
                        max_distance_px: float) -> None:
        """
        Xác định hướng nhìn mục tiêu từ vị trí chuột trong Local Physical Pixels:
        - cursor_local_phys_x, cursor_local_phys_y: Tọa độ cục bộ của cửa sổ (Physical Pixels).
        - box: Bounding box nhân vật trong cửa sổ (Local Physical Pixels).
        - max_distance_px: Khoảng cách tối đa để pet chú ý nhìn theo (Physical Pixels).
        Chỉ lưu vào self._target_look_x / self._target_look_y, không làm mượt hay gọi Drag tại đây.
        """
        if box is None:
            self._target_look_x, self._target_look_y = 0.0, 0.0
            return

        x1, y1, x2, y2 = box
        # Ước lượng vị trí mắt/đầu nhân vật (~30% từ đỉnh đầu xuống)
        eye_x = (x1 + x2) * 0.5
        eye_y = y1 + (y2 - y1) * 0.3

        # Khoảng cách vector từ mắt tới chuột trên màn hình
        dx = cursor_local_phys_x - eye_x
        dy = cursor_local_phys_y - eye_y
        dist = (dx * dx + dy * dy) ** 0.5

        if dist <= max_distance_px and max_distance_px > 0:
            # Chuẩn hóa về đoạn [-1.0, 1.0]
            self._target_look_x = max(-1.0, min(1.0, dx / (max_distance_px * 0.5)))
            # Con trỏ ở dưới -> mắt nhìn xuống (Y âm trong Cubism Drag)
            self._target_look_y = max(-1.0, min(1.0, -dy / (max_distance_px * 0.5)))
        else:
            # Con trỏ ở xa -> nhìn chính diện
            self._target_look_x, self._target_look_y = 0.0, 0.0

    def update_look(self, dt: float, look_speed: float = 12.0, use_manual_params: bool = False) -> None:
        """
        Làm mượt hướng nhìn theo thời gian (độc lập FPS) và cập nhật vào model Live2D:
        - k = 1.0 - exp(-dt * look_speed)
        - model.Drag(current_x, current_y)
        - Chỉ gán SetParamById khi use_manual_params = True.
        Được gọi MỖI FRAME trong paintGL.
        """
        if self.model is None:
            return

        # Làm mượt độc lập FPS
        k = 1.0 - math.exp(-dt * look_speed)
        self._current_look_x += (self._target_look_x - self._current_look_x) * k
        self._current_look_y += (self._target_look_y - self._current_look_y) * k

        # 1. Điều khiển hướng nhìn bằng Drag của Cubism SDK
        try:
            self.model.Drag(self._current_look_x, self._current_look_y)
        except Exception:
            pass

        # 2. Gán trực tiếp các tham số nếu cờ use_manual_params được kích hoạt
        if use_manual_params:
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
