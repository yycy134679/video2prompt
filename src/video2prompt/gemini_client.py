"""Gemini 客户端。"""

from __future__ import annotations

from typing import Any

import httpx

from .errors import GeminiError, GeminiRetryableError


class GeminiClient:
    """Gemini 原生格式客户端。"""

    DEFAULT_USER_PROMPT = "按要求解析视频并输出 sora 提示词"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: int = 90,
        thinking_level: str = "high",
        media_resolution: str = "media_resolution_medium",
        http_client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.thinking_level = self._normalize_thinking_level(thinking_level)
        self.media_resolution = self._normalize_media_resolution(media_resolution)
        self._http_client = http_client
        self._default_user_prompt = self.DEFAULT_USER_PROMPT

    def set_default_user_prompt(self, prompt: str) -> None:
        text = (prompt or "").strip()
        self._default_user_prompt = text or self.DEFAULT_USER_PROMPT

    def build_request_body(self, video_uri: str, user_prompt: str, fps: float) -> dict[str, Any]:
        prompt_text = (user_prompt or "").strip() or self._default_user_prompt
        return {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {
                            "fileData": {
                                "mimeType": "video/mp4",
                                "fileUri": video_uri,
                            },
                            "videoMetadata": {"fps": fps},
                        },
                        {"text": prompt_text},
                    ],
                }
            ],
            "generationConfig": {
                "thinkingConfig": {
                    "thinkingLevel": self.thinking_level,
                },
                "mediaResolution": self.media_resolution,
            },
        }

    async def interpret_video(
        self,
        video_uri: str,
        user_prompt: str,
        fps: float,
        fps_fallback: float | None = None,
    ) -> tuple[str, float]:
        try_fps = [fps]
        if fps_fallback is not None and fps_fallback != fps:
            try_fps.append(fps_fallback)

        last_error: Exception | None = None
        for idx, current_fps in enumerate(try_fps):
            body = self.build_request_body(video_uri=video_uri, user_prompt=user_prompt, fps=current_fps)
            try:
                text = await self._request_and_extract(body)
                return text, current_fps
            except GeminiError as exc:
                last_error = exc
                # 仅在首轮且判定为 fps 参数问题时才降级
                if idx == 0 and self._is_fps_related_error(str(exc)) and len(try_fps) > 1:
                    continue
                raise

        if last_error is not None:
            raise last_error
        raise GeminiError("Gemini 解读失败")

    async def _request_and_extract(self, body: dict[str, Any]) -> str:
        close_client = False
        client = self._http_client
        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout_seconds)
            close_client = True

        try:
            url = f"{self.base_url}/v1beta/models/{self.model}:generateContent"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            resp = await client.post(url, headers=headers, json=body)
            if resp.status_code in {429, 500, 502, 503, 504}:
                raise GeminiRetryableError(f"Gemini 状态码 {resp.status_code}: {resp.text[:500]}")
            if resp.status_code >= 400:
                raise GeminiError(f"Gemini 状态码 {resp.status_code}: {resp.text[:500]}")

            payload = resp.json()
            text = self._extract_text(payload)
            if not text.strip():
                raise GeminiError("Gemini 返回为空")
            return text
        except httpx.TimeoutException as exc:
            raise GeminiRetryableError(f"Gemini 请求超时: {exc}") from exc
        except httpx.HTTPError as exc:
            raise GeminiRetryableError(f"Gemini 请求异常: {exc}") from exc
        except ValueError as exc:
            raise GeminiRetryableError(f"Gemini 返回 JSON 解析失败: {exc}") from exc
        finally:
            if close_client:
                await client.aclose()

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        candidates = payload.get("candidates") if isinstance(payload, dict) else None
        if not isinstance(candidates, list):
            return ""

        chunks: list[str] = []
        for cand in candidates:
            content = cand.get("content") if isinstance(cand, dict) else None
            parts = content.get("parts") if isinstance(content, dict) else None
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "\n".join(chunks).strip()

    @staticmethod
    def _is_fps_related_error(message: str) -> bool:
        lowered = message.lower()
        keys = ("videometadata", "fps", "invalid_argument", "unknown field")
        return any(key in lowered for key in keys)

    @staticmethod
    def is_video_fetch_error_message(message: str) -> bool:
        lowered = message.lower()
        keys = (
            "fetch",
            "resource",
            "cannot access",
            "failed to fetch",
            "download",
            "url",
            "fileuri",
        )
        return any(key in lowered for key in keys)

    @staticmethod
    def _normalize_thinking_level(value: str) -> str:
        return (value or "").strip().lower() or "high"

    @staticmethod
    def _normalize_media_resolution(value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            normalized = "media_resolution_medium"
        if normalized.upper().startswith("MEDIA_RESOLUTION_"):
            return normalized.upper()
        lowered = normalized.lower()
        if lowered.startswith("mediaresolution_"):
            lowered = lowered.replace("mediaresolution_", "media_resolution_", 1)
        return lowered.upper()
