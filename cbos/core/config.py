"""CBOS Configuration"""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class StreamConfig(BaseSettings):
    """Configuration for streaming transport layer"""

    # Directory for typescript files from script -f
    stream_dir: Path = Path.home() / "claude_streams"

    # Enable flush mode for script (-f flag)
    stream_flush: bool = True

    # Maximum buffer size to keep per session (bytes)
    max_buffer_size: int = 100_000

    class Config:
        env_prefix = "CBOS_STREAM_"


class CBOSConfig(BaseSettings):
    """Main CBOS configuration"""

    # API settings
    api_host: str = "127.0.0.1"
    api_port: int = 32205

    # Logging
    log_level: str = "INFO"

    # Claude command configuration
    claude_command: str = "claude"  # Can be full path like /home/user/.local/bin/claude
    claude_env_vars: str = ""  # Space-separated KEY=VALUE pairs, e.g., "MAX_THINKING_TOKENS=32000 NO_COLOR=1"

    # Stream settings
    stream: StreamConfig = StreamConfig()

    model_config = SettingsConfigDict(
        env_prefix="CBOS_",
        env_file=str(Path.home() / ".cbos" / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Global config instance
_config: CBOSConfig | None = None


def get_config() -> CBOSConfig:
    """Get or create the global config instance"""
    global _config
    if _config is None:
        _config = CBOSConfig()
        # Ensure stream directory exists
        _config.stream.stream_dir.mkdir(parents=True, exist_ok=True)
    return _config
