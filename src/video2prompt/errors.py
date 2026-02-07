"""项目级异常定义。"""


class Video2PromptError(Exception):
    """项目基础异常。"""


class ConfigError(Video2PromptError):
    """配置加载或校验失败。"""


class ParserError(Video2PromptError):
    """解析服务异常。"""


class ParserRetryableError(ParserError):
    """可重试的解析异常。"""


class GeminiError(Video2PromptError):
    """Gemini 服务异常。"""


class GeminiRetryableError(GeminiError):
    """可重试的 Gemini 异常。"""


class CircuitBreakerOpenError(Video2PromptError):
    """熔断触发。"""
