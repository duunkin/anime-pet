"""
src/core/character.py
---------------------
Quản lý hồ sơ và tài nguyên của nhân vật Live2D:
- Nạp file cấu hình `characters/<tên>/character.json`.
- Ánh xạ hành vi ứng dụng (idle, startled, sleep, dance, dragged...) sang motion / expression.
- Cơ chế gọi an toàn: nếu thiếu mapping hoặc file không tồn tại thì bỏ qua êm, không crash.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Any, Tuple
import os
import json


@dataclass
class CharacterProfile:
    """
    Hồ sơ thông tin nhân vật, bao gồm đường dẫn model và bảng ánh xạ hành vi.
    """
    name: str
    model3_path: str
    scale: float = 0.65
    motion_map: Dict[str, str] = field(default_factory=dict)
    expression_map: Dict[str, str] = field(default_factory=dict)

    # Cache thông tin các motion có sẵn từ model3.json: {tên_file_chuẩn_hóa: (group, index)}
    _file_to_motion_index: Dict[str, Tuple[str, int]] = field(default_factory=dict, repr=False)
    # Danh sách các nhóm motion có sẵn trong model
    _available_motion_groups: Dict[str, int] = field(default_factory=dict, repr=False)
    # Danh sách các expression có sẵn
    _available_expressions: list[str] = field(default_factory=list, repr=False)

    @classmethod
    def load(cls, character_dir: str, character_name: str) -> "CharacterProfile":
        """
        Nạp cấu hình nhân vật từ thư mục `characters/<tên>/character.json`.
        Nếu không có file character.json, tự động quét tìm file *.model3.json dự phòng.
        """
        target_dir = os.path.join(character_dir, character_name)
        config_path = os.path.join(target_dir, "character.json")

        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                raw_model_path = data.get("model3_path", f"{character_name}.model3.json")
                if not os.path.isabs(raw_model_path):
                    model_path = os.path.abspath(os.path.join(target_dir, raw_model_path))
                else:
                    model_path = raw_model_path

                profile = cls(
                    name=data.get("name", character_name),
                    model3_path=model_path,
                    scale=float(data.get("scale", 0.65)),
                    motion_map=data.get("motion_map", {}),
                    expression_map=data.get("expression_map", {})
                )
                profile._inspect_model_json()
                return profile
            except Exception as e:
                print(f"[Character] Lỗi khi đọc {config_path}: {e}. Đang dùng fallback tự động.")

        # Fallback: Tự động tìm kiếm file *.model3.json trong thư mục
        fallback_model_path = ""
        if os.path.exists(target_dir):
            for file_name in os.listdir(target_dir):
                if file_name.endswith(".model3.json"):
                    fallback_model_path = os.path.abspath(os.path.join(target_dir, file_name))
                    break

        default_profile = cls(
            name=character_name,
            model3_path=fallback_model_path,
            scale=0.65,
            motion_map={"idle": "Idle", "startled": "TapBody"},
            expression_map={}
        )
        default_profile._inspect_model_json()
        return default_profile

    def _inspect_model_json(self) -> None:
        """Đọc file .model3.json để tạo bảng tra cứu nhanh các motion và expression."""
        if not self.model3_path or not os.path.exists(self.model3_path):
            return

        try:
            with open(self.model3_path, "r", encoding="utf-8") as f:
                model_data = json.load(f)

            file_refs = model_data.get("FileReferences", {})
            motions_dict = file_refs.get("Motions", {})

            for group_name, motion_list in motions_dict.items():
                self._available_motion_groups[group_name] = len(motion_list)
                for idx, m in enumerate(motion_list):
                    rel_file = m.get("File", "").replace("\\", "/").lower()
                    if rel_file:
                        self._file_to_motion_index[rel_file] = (group_name, idx)
                        # Lưu cả tên file rút gọn (không có đường dẫn thư mục)
                        base_file = os.path.basename(rel_file).lower()
                        self._file_to_motion_index[base_file] = (group_name, idx)

            expressions_list = file_refs.get("Expressions", [])
            for exp in expressions_list:
                name = exp.get("Name")
                if name:
                    self._available_expressions.append(name)

        except Exception as e:
            print(f"[Character] Lỗi đọc nội dung file model3.json ({self.model3_path}): {e}")

    def play_behavior(self, live2d_model: Any, behavior: str, priority: int = 3) -> bool:
        """
        Kích hoạt hành vi của nhân vật (motion hoặc expression) tương ứng với behavior.
        Nếu thiếu mapping hoặc không thực thi được: bỏ qua êm dịu, trả về False, không làm crash app.
        """
        if live2d_model is None:
            return False

        # 1. Kiểm tra expression_map trước (nếu có biểu cảm cho hành vi này)
        exp_target = self.expression_map.get(behavior)
        if exp_target:
            try:
                live2d_model.SetExpression(exp_target)
            except Exception as e:
                # Bỏ qua êm nếu gọi biểu cảm thất bại
                print(f"[Character] Bỏ qua lỗi SetExpression ({exp_target}): {e}")

        # 2. Kiểm tra motion_map
        motion_target = self.motion_map.get(behavior)
        if not motion_target:
            # Không có ánh xạ cho hành vi này -> bỏ qua êm dịu
            return False

        try:
            # Trường hợp A: Target là tên một nhóm motion (Group) đã có sẵn trong model (ví dụ "Idle", "TapBody")
            if motion_target in self._available_motion_groups:
                live2d_model.StartRandomMotion(motion_target, priority)
                return True

            # Trường hợp B: Target là đường dẫn file motion (ví dụ "motions/Hiyori_m05.motion3.json")
            clean_target = motion_target.replace("\\", "/").lower()
            base_target = os.path.basename(clean_target)

            if clean_target in self._file_to_motion_index:
                grp, idx = self._file_to_motion_index[clean_target]
                live2d_model.StartMotion(grp, idx, priority)
                return True
            elif base_target in self._file_to_motion_index:
                grp, idx = self._file_to_motion_index[base_target]
                live2d_model.StartMotion(grp, idx, priority)
                return True

            # Trường hợp C: Nạp file motion bổ sung bên ngoài nếu có phương thức LoadExtraMotion
            character_dir = os.path.dirname(self.model3_path)
            candidate_path = os.path.join(character_dir, motion_target)
            if os.path.exists(candidate_path) and hasattr(live2d_model, "LoadExtraMotion"):
                extra_group = f"Extra_{behavior}"
                idx = live2d_model.LoadExtraMotion(extra_group, candidate_path)
                live2d_model.StartMotion(extra_group, idx, priority)
                return True

            # Trường hợp D: Thử gọi trực tiếp như group name
            live2d_model.StartRandomMotion(motion_target, priority)
            return True

        except Exception as exc:
            # Bỏ qua êm theo đúng yêu cầu đề bài
            print(f"[Character] Bỏ qua êm khi phát hành vi '{behavior}' ({motion_target}): {exc}")
            return False
