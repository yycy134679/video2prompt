"""火山批量 Chat API 客户端。"""

from __future__ import annotations

from typing import Any

import httpx

from .errors import GeminiError, GeminiRetryableError


class VolcengineBatchClient:
    """封装 /batch/chat/completions 调用。"""

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

    async def batch_chat(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """提交批量请求并返回逐条结果。"""
        if not items:
            return []

        close_client = False
        client = self._http_client
        if client is None:
            client = httpx.AsyncClient(timeout=self.timeout_seconds)
            close_client = True

        url = f"{self.base_url}/batch/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        requests_payload = []
        for item in items:
            req: dict[str, Any] = {
                "custom_id": str(item.get("custom_id", "")),
                "model": self.endpoint_id,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "video_url",
                                "video_url": {
                                    "url": item.get("video_url", ""),
                                    "fps": float(item.get("fps", 1.0)),
                                },
                            },
                            {"type": "text", "text": str(item.get("prompt", ""))},
                        ],
                    }
                ],
            }
            if self.thinking_type in {"enabled", "disabled", "auto"}:
                req["thinking"] = {"type": self.thinking_type}
            if self.thinking_type != "disabled" and self.reasoning_effort in {"minimal", "low", "medium", "high"}:
                req["reasoning_effort"] = self.reasoning_effort
            if self.max_completion_tokens is not None:
                req["max_completion_tokens"] = int(self.max_completion_tokens)
            requests_payload.append(req)

        body = {"requests": requests_payload}
        try:
            resp = await client.post(url, headers=headers, json=body)
            if resp.status_code in {429, 500, 502, 503, 504}:
                raise GeminiRetryableError(f"Batch Chat 状态码 {resp.status_code}: {resp.text[:500]}")
            if resp.status_code >= 400:
                raise GeminiError(f"Batch Chat 状态码 {resp.status_code}: {resp.text[:500]}")

            payload = resp.json()
            results = self._extract_results(payload)
            if not results:
                raise GeminiError(f"Batch Chat 返回为空或无法解析: {payload}")
            return results
        except ValueError as exc:
            raise GeminiRetryableError(f"Batch Chat JSON 解析失败: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise GeminiRetryableError(f"Batch Chat 请求超时: {exc}") from exc
        except httpx.HTTPError as exc:
            raise GeminiRetryableError(f"Batch Chat 请求异常: {exc}") from exc
        finally:
            if close_client:
                await client.aclose()

    def _extract_results(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        # 文档版本差异下做宽松解析：优先 results/data，再回退数组顶层。
        candidates: list[Any] = []
        if isinstance(payload, dict):
            for key in ("results", "data", "responses", "output"):
                value = payload.get(key)
                if isinstance(value, list):
                    candidates = value
                    break
        elif isinstance(payload, list):
            candidates = payload

        parsed: list[dict[str, Any]] = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            custom_id = str(item.get("custom_id", "")).strip()
            usage = self._extract_usage(item)
            request_id = self._extract_request_id(item)

            text = ""
            # 兼容 item.message / item.response / item.choices 等结构
            message = item.get("message")
            if isinstance(message, dict):
                text = self._extract_message_text(message)
            if not text and isinstance(item.get("response"), dict):
                text = self._extract_text_from_response(item["response"])
                if not usage:
                    usage = self._extract_usage(item["response"])
                if not request_id:
                    request_id = self._extract_request_id(item["response"])
            if not text and isinstance(item.get("choices"), list):
                text = self._extract_choices_text(item["choices"])

            if not text:
                continue
            parsed.append(
                {
                    "custom_id": custom_id,
                    "text": text,
                    "usage": usage or {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "reasoning_tokens": 0,
                        "cached_tokens": 0,
                    },
                    "request_id": request_id,
                    "api_mode": "batch",
                }
            )
        return parsed

    def _extract_text_from_response(self, payload: dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            return ""
        choices = payload.get("choices")
        if isinstance(choices, list):
            text = self._extract_choices_text(choices)
            if text:
                return text
        output = payload.get("output")
        if isinstance(output, list):
            chunks: list[str] = []
            for item in output:
                if isinstance(item, dict):
                    content = item.get("content")
                    if isinstance(content, list):
                        for part in content:
                            if isinstance(part, dict) and isinstance(part.get("text"), str):
                                chunks.append(part["text"])
            return "\n".join(chunks).strip()
        return ""

    @staticmethod
    def _extract_choices_text(choices: list[Any]) -> str:
        if not choices:
            return ""
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            return ""
        return VolcengineBatchClient._extract_message_text(message)

    @staticmethod
    def _extract_message_text(message: dict[str, Any]) -> str:
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if not isinstance(content, list):
            return ""
        chunks: list[str] = []
        for part in content:
            if isinstance(part, str):
                chunks.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                chunks.append(part["text"])
        return "\n".join(chunks).strip()

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _extract_usage(self, payload: dict[str, Any]) -> dict[str, int]:
        usage = payload.get("usage") if isinstance(payload, dict) else None
        if not isinstance(usage, dict):
            return {}
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

    @staticmethod
    def _extract_request_id(payload: dict[str, Any]) -> str:
        if not isinstance(payload, dict):
            return ""
        for key in ("request_id", "id"):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return ""
