"""项目级异常定义。"""


class Video2PromptError(Exception):
    """项目基础异常。"""


class ConfigError(Video2PromptError):
    """配置加载或校验失败。"""


class ParserError(Video2PromptError):
    """解析服务异常。"""


class ParserClientSideError(ParserError):
    """用户输入或本地状态问题导致的解析异常，不应计入熔断。"""


class ParserRetryableError(ParserError):
    """可重试的解析异常。"""


class ParserCookieRequiredError(ParserClientSideError):
    """缺少抖音 Cookie。"""


class ParserUnsupportedContentError(ParserClientSideError):
    """当前版本不支持的抖音内容类型。"""


class ParserCookieRetryableError(ParserRetryableError):
    """Cookie 失效、风控或验证码导致的可重试异常。"""


class ModelError(Video2PromptError):
    """模型服务异常。"""


class ModelRetryableError(ModelError):
    """可重试的模型异常。"""


class CircuitBreakerOpenError(Video2PromptError):
    """熔断触发。"""
