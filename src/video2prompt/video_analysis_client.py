"""视频解读客户端抽象接口。"""

from __future__ import annotations

from typing import Protocol


class VideoAnalysisClient(Protocol):
    """统一的视频解读客户端协议。"""

    async def interpret_video(
        self,
        video_uri: str,
        user_prompt: str,
        fps: float,
        fps_fallback: float | None = None,
    ) -> tuple[str, float]:
        """解读视频并返回文本与实际使用的 fps。"""

    def is_video_fetch_error_message(self, message: str) -> bool:
        """判断错误是否指向视频资源拉取失败。"""
