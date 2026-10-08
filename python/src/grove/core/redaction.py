"""Keep embedded URL credentials out of diagnostics and command traces."""
import re


def redact(text: str) -> str:
    return re.sub(r"(https?://)[^/@\s]+@", r"\1[redacted]@", text)
