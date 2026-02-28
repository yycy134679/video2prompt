"""火山 Responses API 客户端。"""

from __future__ import annotations

from typing import Any

import httpx

from .errors import GeminiError, GeminiRetryableError


class VolcengineResponsesClient:
    """基于 file_id 的视频解读。"""

    def __init__(
        self,
        base_url: str,
        endpoint_id: str,
        api_key: str,
        timeout_seconds: int = 90,
        thinking_type: str = "enabled",
        reasoning_effort: str = "medium",
        max_completion_tokens: int | None = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.endpoint_id = endpoint_id.strip()
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.thinking_type = (thinking_type or "").strip().lower() or "enabled"
        self.reasoning_effort = (reasoning_effort or "").strip().lower() or "medium"
        self.max_completion_tokens = max_completion_tokens
        self._http_client = http_client
        self._last_observation: dict[str, Any] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "reasoning_tokens": 0,
            "cached_tokens": 0,
            "request_id": "",
            "api_mode": "responses",
        }

    async def create_response_with_file_id(self, file_id: str, prompt: str) -> str:
        close_client = False
        client = self._http_client
        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout_seconds)
            close_client = True

        url = f"{self.base_url}/responses"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {
            "model": self.endpoint_id,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_video", "file_id": file_id},
                        {"type": "input_text", "text": (prompt or "").strip()},
                    ],
                }
            ],
        }
        if self.thinking_type in {"enabled", "disabled", "auto"}:
            body["thinking"] = {"type": self.thinking_type}
        if self.thinking_type != "disabled" and self.reasoning_effort in {"minimal", "low", "medium", "high"}:
            body["reasoning_effort"] = self.reasoning_effort
        if self.max_completion_tokens is not None:
            body["max_completion_tokens"] = int(self.max_completion_tokens)

        try:
            resp = await client.post(url, headers=headers, json=body)
            if resp.status_code in {429, 500, 502, 503, 504}:
                raise GeminiRetryableError(f"Responses 状态码 {resp.status_code}: {resp.text[:500]}")
            if resp.status_code >= 400:
                raise GeminiError(f"Responses 状态码 {resp.status_code}: {resp.text[:500]}")

            payload = resp.json()
            text = self._extract_text(payload)
            if not text:
                raise GeminiError("Responses 返回为空")
            self._last_observation = {
                **self._last_observation,
                **self.extract_usage(payload),
                "request_id": self._extract_request_id(resp, payload),
                "api_mode": "responses",
            }
            return text
        except ValueError as exc:
            raise GeminiRetryableError(f"Responses JSON 解析失败: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise GeminiRetryableError(f"Responses 请求超时: {exc}") from exc
        except httpx.HTTPError as exc:
            raise GeminiRetryableError(f"Responses 请求异常: {exc}") from exc
        finally:
            if close_client:
                await client.aclose()

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
        # 兼容 output_text / message.content.text 两种结构
        output = payload.get("output") if isinstance(payload, dict) else None
        chunks: list[str] = []
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "output_text":
                    text = item.get("text")
                    if isinstance(text, str):
                        chunks.append(text)
                    continue
                content = item.get("content")
                if isinstance(content, list):
                    for part in content:
                        if not isinstance(part, dict):
                            continue
                        text = part.get("text")
                        if isinstance(text, str):
                            chunks.append(text)
                        elif isinstance(part.get("output_text"), str):
                            chunks.append(part["output_text"])
        if not chunks:
            # 兜底兼容 Chat 风格返回
            choices = payload.get("choices") if isinstance(payload, dict) else None
            if isinstance(choices, list) and choices:
                msg = choices[0].get("message") if isinstance(choices[0], dict) else None
                if isinstance(msg, dict):
                    content = msg.get("content")
                    if isinstance(content, str):
                        return content.strip()
        return "\n".join(chunks).strip()

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

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

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
            "api_mode": "responses",
        }
        return result
