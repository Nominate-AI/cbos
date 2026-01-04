"""CBOS Configuration"""

from pathlib import Path
from pydantic_settings import BaseSettings


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

    # Stream settings
    stream: StreamConfig = StreamConfig()

    class Config:
        env_prefix = "CBOS_"


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
