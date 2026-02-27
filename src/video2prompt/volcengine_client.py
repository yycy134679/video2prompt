"""火山方舟视频解读客户端。"""

from __future__ import annotations

import json
from typing import Any

import httpx

from .errors import GeminiError, GeminiRetryableError
from .review_result import DEFAULT_REVIEW_PROMPT


class VolcengineClient:
    """火山方舟 Chat Completions 视频理解客户端。"""

    DEFAULT_USER_PROMPT = DEFAULT_REVIEW_PROMPT

    def __init__(
        self,
        base_url: str,
        endpoint_id: str,
        target_model: str,
        api_key: str,
        timeout_seconds: int = 90,
        thinking_type: str = "enabled",
        max_completion_tokens: int | None = None,
        stream_usage: bool = False,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.endpoint_id = endpoint_id.strip()
        self.target_model = target_model.strip()
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.thinking_type = (thinking_type or "").strip().lower() or "enabled"
        self.max_completion_tokens = max_completion_tokens
        self.stream_usage = bool(stream_usage)
        self._http_client = http_client
        self._default_user_prompt = self.DEFAULT_USER_PROMPT
        self._last_observation: dict[str, Any] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "reasoning_tokens": 0,
            "cached_tokens": 0,
            "request_id": "",
            "api_mode": "chat",
        }

    def set_default_user_prompt(self, prompt: str) -> None:
        text = (prompt or "").strip()
        self._default_user_prompt = text or self.DEFAULT_USER_PROMPT

    def build_request_body(self, video_uri: str, user_prompt: str, fps: float) -> dict[str, Any]:
        prompt_text = (user_prompt or "").strip() or self._default_user_prompt
        body: dict[str, Any] = {
            "model": self.endpoint_id,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "video_url", "video_url": {"url": video_uri, "fps": fps}},
                        {"type": "text", "text": prompt_text},
                    ],
                }
            ],
        }
        if self.thinking_type in {"enabled", "disabled", "auto"}:
            body["thinking"] = {"type": self.thinking_type}
        if self.max_completion_tokens is not None:
            body["max_completion_tokens"] = int(self.max_completion_tokens)
        if self.stream_usage:
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}
        return body

    async def interpret_video(
        self,
        video_uri: str,
        user_prompt: str,
        fps: float,
        fps_fallback: float | None = None,
    ) -> tuple[str, float]:
        del fps_fallback  # 保留签名以兼容现有调度层（Gemini 仍使用该参数）。
        self._last_observation = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "reasoning_tokens": 0,
            "cached_tokens": 0,
            "request_id": "",
            "api_mode": "chat",
        }
        body = self.build_request_body(video_uri=video_uri, user_prompt=user_prompt, fps=fps)
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
            if self.stream_usage:
                return await self._request_stream_and_extract(client=client, url=url, headers=headers, body=body)

            resp = await client.post(url, headers=headers, json=body)
            self._raise_for_status(resp)

            payload = resp.json()
            self._last_observation = {
                **self._last_observation,
                **self.extract_usage(payload),
                "request_id": self._extract_request_id(resp, payload),
                "api_mode": "chat",
            }
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

    async def _request_stream_and_extract(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
    ) -> str:
        chunks: list[str] = []
        usage: dict[str, int] = {}
        request_id = ""

        async with client.stream("POST", url, headers=headers, json=body) as resp:
            self._raise_for_status(resp)
            request_id = self._extract_request_id(resp, {})
            async for line in resp.aiter_lines():
                text_line = (line or "").strip()
                if not text_line or not text_line.startswith("data:"):
                    continue
                data = text_line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except ValueError:
                    continue

                chunk = self._extract_stream_text(event)
                if chunk:
                    chunks.append(chunk)
                if not usage:
                    usage = self.extract_usage(event)
                elif any(int(usage.get(key, 0)) == 0 for key in usage):
                    # 流式 usage 可能分段出现，后续事件补全非零字段。
                    latest = self.extract_usage(event)
                    for key, value in latest.items():
                        if value > 0:
                            usage[key] = value
                request_id = self._extract_request_id(resp, event) or request_id

        self._last_observation = {
            **self._last_observation,
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
            "reasoning_tokens": int(usage.get("reasoning_tokens", 0)),
            "cached_tokens": int(usage.get("cached_tokens", 0)),
            "request_id": request_id,
            "api_mode": "chat",
        }

        text = "".join(chunks).strip()
        if not text:
            raise GeminiError("火山流式返回为空")
        return text

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        code, detail = self._extract_error_code_and_detail(resp)
        message = f"火山状态码 {resp.status_code}: {detail}"
        if resp.status_code in {429, 500, 502, 503, 504}:
            raise GeminiRetryableError(message)
        raise GeminiError(message)

    @staticmethod
    def _extract_error_code_and_detail(resp: httpx.Response) -> tuple[str, str]:
        code = ""
        message = ""
        request_id = VolcengineClient._extract_request_id(resp, {})
        raw = resp.text[:500]
        try:
            payload = resp.json()
        except ValueError:
            payload = {}

        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                code = str(error.get("code", "")).strip()
                message = str(error.get("message", "")).strip()
                request_id = str(error.get("request_id", "")).strip() or request_id
            request_id = str(payload.get("request_id", "")).strip() or request_id
            if not message:
                message = str(payload.get("message", "")).strip()

        parts = []
        if code:
            parts.append(f"code={code}")
        if message:
            parts.append(message)
        if request_id:
            parts.append(f"request_id={request_id}")
        if not parts and raw:
            parts.append(raw)
        return code, " | ".join(parts)

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

    @staticmethod
    def _extract_stream_text(payload: dict[str, Any]) -> str:
        choices = payload.get("choices") if isinstance(payload, dict) else None
        if not isinstance(choices, list) or not choices:
            return ""
        choice = choices[0] if isinstance(choices[0], dict) else {}
        delta = choice.get("delta")
        if isinstance(delta, dict):
            content = delta.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                chunks: list[str] = []
                for item in content:
                    if isinstance(item, str):
                        chunks.append(item)
                    elif isinstance(item, dict):
                        text = item.get("text")
                        if isinstance(text, str):
                            chunks.append(text)
                return "".join(chunks)
        message = choice.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
        return ""

    @staticmethod
    def _extract_request_id(resp: httpx.Response, payload: dict[str, Any]) -> str:
        request_id = (
            resp.headers.get("x-request-id")
            or resp.headers.get("x-tt-logid")
            or resp.headers.get("x-log-id")
            or ""
        ).strip()
        if not isinstance(payload, dict):
            return request_id
        for key in ("request_id", "id"):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        error = payload.get("error")
        if isinstance(error, dict):
            val = error.get("request_id")
            if isinstance(val, str) and val.strip():
                return val.strip()
        return request_id

    def extract_usage(self, payload: dict[str, Any]) -> dict[str, int]:
        usage = payload.get("usage") if isinstance(payload, dict) else None
        if not isinstance(usage, dict):
            return {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "reasoning_tokens": 0,
                "cached_tokens": 0,
            }
        prompt_details = usage.get("prompt_tokens_details")
        completion_details = usage.get("completion_tokens_details")
        return {
            "prompt_tokens": self._safe_int(usage.get("prompt_tokens")),
            "completion_tokens": self._safe_int(usage.get("completion_tokens")),
            "reasoning_tokens": self._safe_int(
                usage.get("reasoning_tokens")
                if usage.get("reasoning_tokens") is not None
                else completion_details.get("reasoning_tokens")
                if isinstance(completion_details, dict)
                else 0
            ),
            "cached_tokens": self._safe_int(
                usage.get("cached_tokens")
                if usage.get("cached_tokens") is not None
                else prompt_details.get("cached_tokens")
                if isinstance(prompt_details, dict)
                else 0
            ),
        }

    def consume_last_observation(self) -> dict[str, Any]:
        result = dict(self._last_observation)
        self._last_observation = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "reasoning_tokens": 0,
            "cached_tokens": 0,
            "request_id": "",
            "api_mode": "chat",
        }
        return result

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

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
            "input_video",
            "file_id",
            "file not active",
            "responses",
        )
        return any(key in lowered for key in keys)
