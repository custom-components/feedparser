"""Compatibility shims across supported Home Assistant versions."""

# Home Assistant 2026.9 replaced voluptuous with probatio, an API-compatible fork,
# and its flow/schema helpers are now typed against probatio. Prefer it, and fall
# back to voluptuous on older releases.
try:
    import probatio as vol
except ImportError:  # Home Assistant < 2026.9
    import voluptuous as vol  # type: ignore[no-redef]

__all__ = ["vol"]
