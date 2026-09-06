"""Robot Image Upload（Step 7）：上传 / 替换 / 删除机器人外观图。

需求 §6：这张图是**用户自己的机器人**，不能写死、不能塞假机器人占位图。
没有图的时候前端显示 "No robot image / Upload your robot"。

安全取舍（这是本地单机工具，但也别留洞）：
  - 白名单扩展名 + **magic bytes 校验**（只看扩展名的话，一个 .png 里塞
    可执行文件也过得去）；
  - 落盘文件名用 uuid 重新生成，**不采用用户给的原始文件名**（防路径穿越）；
  - 单张 8MB 上限；
  - 删除只删 uploads 目录内的文件，解析不出就当没这事。
"""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

ALLOWED_EXT = (".png", ".jpg", ".jpeg", ".webp")
MAX_BYTES = 8 * 1024 * 1024
_URL_PREFIX = "/api/robot/image/"

_DEFAULT_DIR = Path(__file__).resolve().parent.parent / "store" / "uploads"


def _sniff(data: bytes) -> Optional[str]:
    """按文件头判断真实类型；认不出 → None（拒绝）。"""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


class ImageStore:
    def __init__(self, upload_dir: Optional[str] = None) -> None:
        self.dir = Path(upload_dir) if upload_dir else _DEFAULT_DIR
        self.dir.mkdir(parents=True, exist_ok=True)

    def save(self, data: bytes, filename: str = "") -> tuple:
        """存图 → (imageUrl, error)。error 非空就是没存成。"""
        if not data:
            return "", "空文件"
        if len(data) > MAX_BYTES:
            return "", f"图片超过 {MAX_BYTES // 1024 // 1024}MB 上限"
        ext_ext = Path(filename or "").suffix.lower()
        real = _sniff(data)
        if real is None:
            return "", "不是有效的 PNG / JPG / WEBP 文件"
        if ext_ext and ext_ext not in ALLOWED_EXT:
            return "", f"不支持的格式：{ext_ext}"
        name = f"{uuid.uuid4().hex}{real}"
        (self.dir / name).write_bytes(data)
        return f"{_URL_PREFIX}{name}", ""

    def resolve(self, image_url: Optional[str]) -> Optional[Path]:
        """URL → 本地路径；解析不出来返回 None（不抛异常给路由层添乱）。"""
        if not image_url or not image_url.startswith(_URL_PREFIX):
            return None
        name = image_url[len(_URL_PREFIX):]
        if "/" in name or "\\" in name or name.startswith("."):
            return None                                  # 路径穿越
        p = self.dir / name
        return p if p.exists() else None

    def delete(self, image_url: Optional[str]) -> bool:
        p = self.resolve(image_url)
        if p is None:
            return False
        try:
            p.unlink()
            return True
        except OSError:
            return False

    def clear(self, image_url: Optional[str]) -> bool:
        """换图/删图时清掉旧文件。删不掉也不算错误（只是留个孤儿文件）。"""
        return self.delete(image_url)
