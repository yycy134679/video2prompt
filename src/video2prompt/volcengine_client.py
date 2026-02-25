"""火山方舟视频解读客户端。"""

from __future__ import annotations

from typing import Any

import httpx

from .errors import GeminiError, GeminiRetryableError


class VolcengineClient:
    """火山方舟 Chat Completions 视频理解客户端。"""

    DEFAULT_USER_PROMPT = "按要求解析视频并输出 sora 提示词"

    def __init__(
        self,
        base_url: str,
        endpoint_id: str,
        target_model: str,
        api_key: str,
        timeout_seconds: int = 90,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.endpoint_id = endpoint_id.strip()
        self.target_model = target_model.strip()
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client
        self._default_user_prompt = self.DEFAULT_USER_PROMPT

    def set_default_user_prompt(self, prompt: str) -> None:
        text = (prompt or "").strip()
        self._default_user_prompt = text or self.DEFAULT_USER_PROMPT

    def build_request_body(self, video_uri: str, user_prompt: str) -> dict[str, Any]:
        prompt_text = (user_prompt or "").strip() or self._default_user_prompt
        return {
            "model": self.endpoint_id,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "video_url", "video_url": {"url": video_uri}},
                        {"type": "text", "text": prompt_text},
                    ],
                }
            ],
        }

    async def interpret_video(
        self,
        video_uri: str,
        user_prompt: str,
        fps: float,
        fps_fallback: float | None = None,
    ) -> tuple[str, float]:
        del fps_fallback  # 火山接口暂无 fps 采样参数，保留签名用于兼容调度层。
        body = self.build_request_body(video_uri=video_uri, user_prompt=user_prompt)
        text = await self._request_and_extract(body)
        return text, fps

    async def _request_and_extract(self, body: dict[str, Any]) -> str:
        close_client = False
        client = self._http_client
        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout_seconds)
            close_client = True

        try:
            url = f"{self.base_url}/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            resp = await client.post(url, headers=headers, json=body)
            if resp.status_code in {429, 500, 502, 503, 504}:
                raise GeminiRetryableError(f"火山状态码 {resp.status_code}: {resp.text[:500]}")
            if resp.status_code >= 400:
                raise GeminiError(f"火山状态码 {resp.status_code}: {resp.text[:500]}")

            payload = resp.json()
            text = self._extract_text(payload)
            if not text.strip():
                raise GeminiError("火山返回为空")
            return text
        except httpx.TimeoutException as exc:
            raise GeminiRetryableError(f"火山请求超时: {exc}") from exc
        except httpx.HTTPError as exc:
            raise GeminiRetryableError(f"火山请求异常: {exc}") from exc
        except ValueError as exc:
            raise GeminiRetryableError(f"火山返回 JSON 解析失败: {exc}") from exc
        finally:
            if close_client:
                await client.aclose()

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        choices = payload.get("choices") if isinstance(payload, dict) else None
        if not isinstance(choices, list) or not choices:
            return ""
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            return ""
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if not isinstance(content, list):
            return ""

        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
                continue
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str):
                chunks.append(text)
        return "\n".join(chunks).strip()

    def is_video_fetch_error_message(self, message: str) -> bool:
        lowered = message.lower()
        keys = (
            "video_url",
            "cannot access",
            "failed to fetch",
            "error while connecting",
            "connecting",
            "download",
            "url",
            "fileuri",
            "视频",
            "资源",
            "拉取",
            "403",
            "forbid",
            "openresty",
            "text/html",
            "mime type",
            "mimetype",
            "exceeds the limit",
        )
        return any(key in lowered for key in keys)
