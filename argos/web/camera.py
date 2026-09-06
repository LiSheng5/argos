"""Camera Stream（Step 8）：第一阶段只做 MJPEG over HTTP。

## 现状：ArgOS 现在一个像素都没有

真机 Go2 的图要走宇树 `VideoClient.GetImageSample()`（DDS/RPC，返回 JPEG），
但那要真机在手；ArgOS 里也一行没接。所以第一阶段按需求 §8 的做法：
**先支持外部 MJPEG 源 + 本机摄像头，WebRTC 以后再说**。

| mode | 行为 |
|---|---|
| `url`  | 转发外部 MJPEG（手机 IP 摄像头 / 另一台机器上的 Go2 流 / 任何 http MJPEG） |
| `usb`  | 本机摄像头（需要 opencv，没装会明确报错，不静默黑屏） |
| `none` | 明确 404 + `No camera signal`，**不给假画面** |

不做的事：不假装"这是机器人的视角"。来源是什么就是什么，配置里写着。
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional

from argos.web.models import CameraConfig

_BOUNDARY = b"--frame"


class CameraUnavailable(Exception):
    """没有可用的相机源（前端据此显示 No camera signal）。"""


class CameraService:
    def __init__(self, store) -> None:
        self.store = store

    def config(self) -> CameraConfig:
        return self.store.get_camera()

    def set_config(self, cfg: CameraConfig) -> CameraConfig:
        return self.store.set_camera(cfg)

    def status(self) -> dict:
        cfg = self.config()
        if cfg.mode == "url" and cfg.url:
            return {"mode": "url", "available": True, "url": cfg.url,
                    "message": "外部 MJPEG 源"}
        if cfg.mode == "usb":
            return {"mode": "usb", "available": _cv2() is not None,
                    "index": cfg.usbIndex,
                    "message": ("本机摄像头" if _cv2() is not None
                                else "未安装 opencv：pip install opencv-python")}
        return {"mode": "none", "available": False,
                "message": "No camera source configured"}

    # ── 流 ──────────────────────────────────────────────

    async def stream(self) -> AsyncIterator[bytes]:
        """产出 MJPEG 分片（multipart/x-mixed-replace; boundary=frame）。"""
        cfg = self.config()
        if cfg.mode == "url" and cfg.url:
            async for chunk in self._relay(cfg.url):
                yield chunk
            return
        if cfg.mode == "usb":
            async for part in self._usb(cfg.usbIndex):
                yield part
            return
        raise CameraUnavailable("No camera source configured")

    async def _relay(self, url: str) -> AsyncIterator[bytes]:
        """原样转发上游 MJPEG：不重新组帧，避免解析各家不同的分片格式。"""
        try:
            import httpx
        except ImportError as exc:
            raise CameraUnavailable("缺 httpx，无法转发外部流") from exc
        async with httpx.AsyncClient(timeout=None) as client:
            try:
                async with client.stream("GET", url) as resp:
                    async for chunk in resp.aiter_bytes():
                        yield chunk
            except Exception as exc:
                raise CameraUnavailable(f"拉取外部相机失败：{exc}") from exc

    async def _usb(self, index: int) -> AsyncIterator[bytes]:
        cv2 = _cv2()
        if cv2 is None:
            raise CameraUnavailable(
                "未安装 opencv：pip install opencv-python")
        cap = await asyncio.to_thread(cv2.VideoCapture, int(index))
        try:
            if not cap.isOpened():
                raise CameraUnavailable(f"打不开摄像头 #{index}")
            while True:
                ok, frame = await asyncio.to_thread(cap.read)
                if not ok or frame is None:
                    break
                enc_ok, buf = cv2.imencode(".jpg", frame)
                if not enc_ok:
                    continue
                yield _part(buf.tobytes())
                await asyncio.sleep(1.0 / 15.0)
        finally:
            try:
                cap.release()
            except Exception:
                pass

    # ── 单帧 ────────────────────────────────────────────

    async def snapshot(self) -> Optional[bytes]:
        """给不支持 MJPEG 的地方用（比如生成缩略图）。"""
        cfg = self.config()
        if cfg.mode == "usb":
            cv2 = _cv2()
            if cv2 is None:
                return None
            cap = await asyncio.to_thread(cv2.VideoCapture, int(cfg.usbIndex))
            try:
                ok, frame = await asyncio.to_thread(cap.read)
                if not ok:
                    return None
                enc_ok, buf = cv2.imencode(".jpg", frame)
                return buf.tobytes() if enc_ok else None
            finally:
                cap.release()
        if cfg.mode == "url" and cfg.url:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=5.0) as client:
                    async with client.stream("GET", cfg.url) as resp:
                        data = b""
                        async for chunk in resp.aiter_bytes():
                            data += chunk
                            if len(data) > 256 * 1024:
                                break
                return _first_jpeg(data)
            except Exception:
                return None
        return None


def _part(jpeg: bytes) -> bytes:
    return (b"--frame\r\nContent-Type: image/jpeg\r\n"
            b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
            + jpeg + b"\r\n")


def _first_jpeg(data: bytes) -> Optional[bytes]:
    start = data.find(b"\xff\xd8\xff")
    if start < 0:
        return None
    end = data.find(b"\xff\xd9", start)
    if end < 0:
        return None
    return data[start:end + 2]


def _cv2():
    try:
        import cv2
        return cv2
    except Exception:
        return None
