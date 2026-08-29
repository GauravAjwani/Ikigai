from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Ikigai"
    host: str = "0.0.0.0"
    port: int = 43177

    gemini_api_key: str = ""
    google_cloud_project: str = ""
    google_cloud_location: str = "us-central1"
    vertex_enabled: bool = False

    gate_model: str = "gemini-3.5-flash-lite"
    probe_model: str = "gemini-3.5-flash-lite"
    adjudicate_model: str = "gemini-3.5-flash"
    embed_model: str = "gemini-embedding-001"
    fallback_gate_model: str = "gemini-2.5-flash-lite"
    fallback_adjudicate_model: str = "gemini-2.5-flash"

    daily_budget_usd: float = 10.0
    hard_budget_usd: float = 40.0
    watcher_confidence_threshold: float = 0.72
    rank_threshold: float = 0.42
    max_slack_searches: int = 2
    max_rank_candidates: int = 10

    firestore_collection: str = "ikigai_decisions"
    meter_collection: str = "ikigai_meter"

    slack_bot_token: str = ""
    slack_signing_secret: str = ""
    slack_app_token: str = ""
    slack_user_token: str = ""

    # USD per 1M tokens (Vertex global, Aug 2026)
    lite_in: float = 0.30
    lite_out: float = 2.50
    flash_in: float = 1.50
    flash_out: float = 9.00
    embed_in: float = 0.15

    def gemini_ready(self) -> bool:
        return bool(self.gemini_api_key or self.vertex_enabled or self.google_cloud_project)

    def gcp_ready(self) -> bool:
        return bool(self.google_cloud_project)

    def slack_ready(self) -> bool:
        return bool(self.slack_bot_token and self.slack_signing_secret)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if not s.gemini_api_key:
        s.gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
    if not s.google_cloud_project:
        s.google_cloud_project = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    if os.environ.get("IKIGAI_VERTEX", os.environ.get("PRECEDENT_VERTEX", "")).lower() in {
        "1",
        "true",
        "yes",
    }:
        s.vertex_enabled = True
    return s
