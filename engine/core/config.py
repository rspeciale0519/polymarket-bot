"""
Configuration loader.

Loads static config from .env on startup.
Hot-reloadable settings are polled from the bot_settings DB table
by the settings_poller module — this module just handles the env/startup side.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from engine.core.types import EngineConfig, Mode


def load_config(env_path: str | None = None) -> EngineConfig:
    """Load configuration from environment variables."""
    if env_path:
        load_dotenv(env_path)
    else:
        load_dotenv()

    mode_str = os.getenv("ENGINE_MODE", "paper").lower()
    try:
        mode = Mode(mode_str)
    except ValueError:
        mode = Mode.PAPER

    return EngineConfig(
        mode=mode,
        kalshi_api_key_id=os.getenv("KALSHI_API_KEY_ID", ""),
        kalshi_private_key_path=os.getenv("KALSHI_PRIVATE_KEY_PATH", ""),
        kalshi_env=os.getenv("KALSHI_ENV", "demo"),
        database_url=os.getenv("DATABASE_URL", ""),
        telegram_token=os.getenv("TELEGRAM_TOKEN", ""),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
        paper_starting_capital_cents=int(
            os.getenv("PAPER_STARTING_CAPITAL_CENTS", "10000")
        ),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )


def apply_db_settings(config: EngineConfig, settings: dict[str, str]) -> EngineConfig:
    """
    Apply settings from the bot_settings DB table onto the config.

    Only hot-reloadable fields are updated. Returns a new config instance.
    Static fields (API keys, DB URL, mode) are NOT overwritten.
    """
    field_map: dict[str, tuple[str, type]] = {
        "max_position_per_market": ("max_position_per_market", int),
        "global_exposure_limit_cents": ("global_exposure_limit_cents", int),
        "daily_loss_limit_cents": ("daily_loss_limit_cents", int),
        "drawdown_limit": ("drawdown_limit", float),
        "base_gamma": ("base_gamma", float),
        "sigma": ("sigma", float),
        "min_spread_cents": ("min_spread_cents", int),
        "order_size": ("order_size", int),
        "signal_weight": ("signal_weight", float),
        "min_volume": ("min_volume", int),
        "max_market_spread_cents": ("max_market_spread_cents", int),
        "min_time_to_expiry_seconds": ("min_time_to_expiry_seconds", int),
        "paper_milestone_days": ("paper_milestone_days", int),
        "settings_poll_interval_seconds": ("settings_poll_interval_seconds", int),
        "reconciliation_interval_seconds": ("reconciliation_interval_seconds", int),
        "snapshot_interval_seconds": ("snapshot_interval_seconds", int),
    }

    # Mode is special — it CAN be changed from dashboard but requires care
    mode_str = settings.get("mode")
    if mode_str:
        try:
            config.mode = Mode(mode_str.lower())
        except ValueError:
            pass

    for db_key, (attr_name, cast_fn) in field_map.items():
        raw = settings.get(db_key)
        if raw is not None:
            try:
                setattr(config, attr_name, cast_fn(raw))
            except (ValueError, TypeError):
                pass

    return config


def validate_config(config: EngineConfig) -> list[str]:
    """Validate config and return list of errors (empty = valid)."""
    errors: list[str] = []

    if config.mode == Mode.LIVE:
        if not config.kalshi_api_key_id:
            errors.append("KALSHI_API_KEY_ID required for live trading")
        if not config.kalshi_private_key_path:
            errors.append("KALSHI_PRIVATE_KEY_PATH required for live trading")
        key_path = Path(config.kalshi_private_key_path)
        if config.kalshi_private_key_path and not key_path.exists():
            errors.append(f"Private key file not found: {key_path}")

    if not config.database_url:
        errors.append("DATABASE_URL is required")

    if config.max_position_per_market < 1:
        errors.append("max_position_per_market must be >= 1")

    if config.daily_loss_limit_cents < 1:
        errors.append("daily_loss_limit_cents must be >= 1")

    if not 0.0 < config.drawdown_limit < 1.0:
        errors.append("drawdown_limit must be between 0 and 1")

    if config.min_spread_cents < 1:
        errors.append("min_spread_cents must be >= 1")

    return errors
