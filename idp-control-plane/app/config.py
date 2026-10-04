"""Environment-backed settings (spec section 32).

Everything configurable lives here; no other module reads os.environ.
Phase 1 only needs the values below. Later phases add DATABASE_URL, GITOPS_*,
registry, kubeconfig, auth and CORS settings.
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Apps are served at https://<app-name>.<platform_domain>  (spec section 16).
    # Required: there is deliberately no default, we never invent your domain.
    platform_domain: str = Field(pattern=r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")

    # Pipeline worker threads. 1 = deployments run one at a time and the rest
    # wait in `pending`. That is the safe default: they share one Git working
    # tree and one Docker daemon.
    job_workers: int = Field(default=1, ge=1, le=8)


@lru_cache
def get_settings() -> Settings:
    return Settings()
