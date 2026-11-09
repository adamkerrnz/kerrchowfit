class ToolError(Exception):
    """A failure reported to the page with the same codes the claude.ai runtime uses."""

    def __init__(self, code: str, message: str, retryable: bool = False, retry_after_ms: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.retry_after_ms = retry_after_ms

    def as_dict(self) -> dict:
        d = {"code": self.code, "message": self.message}
        if self.retryable:
            d["retryable"] = True
        if self.retry_after_ms:
            d["retryAfterMs"] = self.retry_after_ms
        return d
