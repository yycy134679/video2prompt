"""火山 Responses API 客户端。"""

from __future__ import annotations

from typing import Any

import httpx

from .errors import ModelError, ModelRetryableError
from .review_result import DEFAULT_REVIEW_PROMPT


class VolcengineResponsesClient:
    """火山原生 Responses 视频理解客户端。"""

    DEFAULT_USER_PROMPT = DEFAULT_REVIEW_PROMPT

    def __init__(
        self,
        base_url: str,
        endpoint_id: str,
        api_key: str,
        timeout_seconds: int = 90,
        thinking_type: str = "enabled",
        reasoning_effort: str = "medium",
        max_output_tokens: int | None = None,
        stream: bool = False,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.endpoint_id = endpoint_id.strip()
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.thinking_type = (thinking_type or "").strip().lower() or "enabled"
        self.reasoning_effort = (reasoning_effort or "").strip().lower() or "medium"
        self.max_output_tokens = max_output_tokens
        self.stream = bool(stream)
        self._http_client = http_client
        self._default_user_prompt = self.DEFAULT_USER_PROMPT
        self._last_observation: dict[str, Any] = self._empty_observation()

    def set_default_user_prompt(self, prompt: str) -> None:
        text = (prompt or "").strip()
        self._default_user_prompt = text or self.DEFAULT_USER_PROMPT

    async def interpret_video(
        self,
        video_uri: str,
        user_prompt: str,
        fps: float,
        fps_fallback: float | None = None,
    ) -> tuple[str, float]:
        del fps_fallback
        body = self._build_request_body(
            input_items=self._build_video_url_input(video_url=video_uri, prompt=user_prompt, fps=fps)
        )
        text = await self._request_and_extract(body=body, api_mode="video_url")
        return text, fps

    async def create_response_with_file_id(self, file_id: str, prompt: str) -> str:
        body = self._build_request_body(input_items=self._build_file_id_input(file_id=file_id, prompt=prompt))
        return await self._request_and_extract(body=body, api_mode="file_id")

    def _build_request_body(self, input_items: list[dict[str, Any]]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.endpoint_id,
            "input": input_items,
        }
        if self.thinking_type in {"enabled", "disabled", "auto"}:
            body["thinking"] = {"type": self.thinking_type}
        if self.thinking_type != "disabled" and self.reasoning_effort in {"minimal", "low", "medium", "high"}:
            body["reasoning"] = {"effort": self.reasoning_effort}
        if self.max_output_tokens is not None:
            body["max_output_tokens"] = int(self.max_output_tokens)
        if self.stream:
            body["stream"] = True
        return body

    def _build_video_url_input(self, video_url: str, prompt: str, fps: float) -> list[dict[str, Any]]:
        prompt_text = (prompt or "").strip() or self._default_user_prompt
        return [
            {
                "role": "user",
                "content": [
                    {"type": "input_video", "video_url": video_url, "fps": fps},
                    {"type": "input_text", "text": prompt_text},
                ],
            }
        ]

    def _build_file_id_input(self, file_id: str, prompt: str) -> list[dict[str, Any]]:
        prompt_text = (prompt or "").strip() or self._default_user_prompt
        return [
            {
                "role": "user",
                "content": [
                    {"type": "input_video", "file_id": file_id},
                    {"type": "input_text", "text": prompt_text},
                ],
            }
        ]

    async def _request_and_extract(self, body: dict[str, Any], api_mode: str) -> str:
        self._last_observation = self._empty_observation(api_mode=api_mode)
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

        try:
            if self.stream:
                return await self._request_stream_and_extract(
                    client=client,
                    url=url,
                    headers=headers,
                    body=body,
                    api_mode=api_mode,
                )

            resp = await client.post(url, headers=headers, json=body)
            if resp.status_code in {429, 500, 502, 503, 504}:
                raise ModelRetryableError(f"Responses 状态码 {resp.status_code}: {resp.text[:500]}")
            if resp.status_code >= 400:
                raise ModelError(f"Responses 状态码 {resp.status_code}: {resp.text[:500]}")

            payload = resp.json()
            text = self._extract_text(payload)
            if not text:
                raise ModelError("Responses 返回为空")
            self._last_observation = {
                **self._last_observation,
                **self.extract_usage(payload),
                "request_id": self._extract_request_id(resp, payload),
                "api_mode": api_mode,
            }
            return text
        except ValueError as exc:
            raise ModelRetryableError(f"Responses JSON 解析失败: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise ModelRetryableError(f"Responses 请求超时: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ModelRetryableError(f"Responses 请求异常: {exc}") from exc
        finally:
            if close_client:
                await client.aclose()

    async def _request_stream_and_extract(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: dict[str, str],
        body: dict[str, Any],
        api_mode: str,
    ) -> str:
        chunks: list[str] = []
        usage: dict[str, int] = {}
        request_id = ""
        completed_response: dict[str, Any] = {}

        async with client.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code in {429, 500, 502, 503, 504}:
                raise ModelRetryableError(f"Responses 状态码 {resp.status_code}: {resp.text[:500]}")
            if resp.status_code >= 400:
                raise ModelError(f"Responses 状态码 {resp.status_code}: {resp.text[:500]}")

            request_id = self._extract_request_id(resp, {})
            async for line in resp.aiter_lines():
                event = self._parse_sse_line(line)
                if not event:
                    continue

                event_type = str(event.get("type", "")).strip()
                if event_type == "response.output_text.delta":
                    delta = event.get("delta")
                    if isinstance(delta, str):
                        chunks.append(delta)
                elif event_type == "response.completed":
                    response_payload = event.get("response")
                    if isinstance(response_payload, dict):
                        completed_response = response_payload
                        usage = self.extract_usage(response_payload)
                        request_id = self._extract_request_id(resp, response_payload) or request_id

                if not usage:
                    latest_usage = self.extract_usage(event)
                    if any(latest_usage.values()):
                        usage = latest_usage
                request_id = self._extract_request_id(resp, event) or request_id

        self._last_observation = {
            **self._last_observation,
            "prompt_tokens": int(usage.get("prompt_tokens", 0)),
            "completion_tokens": int(usage.get("completion_tokens", 0)),
            "reasoning_tokens": int(usage.get("reasoning_tokens", 0)),
            "cached_tokens": int(usage.get("cached_tokens", 0)),
            "request_id": request_id,
            "api_mode": api_mode,
        }

        text = "".join(chunks).strip()
        if not text and completed_response:
            text = self._extract_text(completed_response)
        if not text:
            raise ModelError("Responses 流式返回为空")
        return text

    @staticmethod
    def _parse_sse_line(line: str) -> dict[str, Any] | None:
        text = (line or "").strip()
        if not text or not text.startswith("data:"):
            return None
        payload = text[5:].strip()
        if not payload or payload == "[DONE]":
            return None
        try:
            data = httpx.Response(status_code=200, content=payload).json()
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> str:
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
        prompt_tokens = usage.get("prompt_tokens")
        if prompt_tokens is None:
            prompt_tokens = usage.get("input_tokens")
        completion_tokens = usage.get("completion_tokens")
        if completion_tokens is None:
            completion_tokens = usage.get("output_tokens")

        return {
            "prompt_tokens": self._safe_int(prompt_tokens),
            "completion_tokens": self._safe_int(completion_tokens),
            "reasoning_tokens": self._safe_int(
                usage.get("reasoning_tokens")
                if usage.get("reasoning_tokens") is not None
                else completion_details.get("reasoning_tokens")
                if isinstance(completion_details, dict)
                else output_details.get("reasoning_tokens")
                if isinstance((output_details := usage.get("output_tokens_details")), dict)
                else 0
            ),
            "cached_tokens": self._safe_int(
                usage.get("cached_tokens")
                if usage.get("cached_tokens") is not None
                else prompt_details.get("cached_tokens")
                if isinstance(prompt_details, dict)
                else input_details.get("cached_tokens")
                if isinstance((input_details := usage.get("input_tokens_details")), dict)
                else 0
            ),
        }

    def consume_last_observation(self) -> dict[str, Any]:
        result = dict(self._last_observation)
        self._last_observation = self._empty_observation()
        return result

    @staticmethod
    def _empty_observation(api_mode: str = "responses") -> dict[str, Any]:
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "reasoning_tokens": 0,
            "cached_tokens": 0,
            "request_id": "",
            "api_mode": api_mode,
        }

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
