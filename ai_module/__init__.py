"""Optional AI assistance with any provider (API key) instead of a cluster worker."""
from ai_module.provider import (  # noqa: F401
    PROVIDERS, AIError, complete, complete_json, get_settings, is_enabled,
    public_settings, save_settings, stream,
)
