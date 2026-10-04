"""Environment-backed settings (spec section 32).

Everything configurable lives here; no other module reads os.environ.
Later phases add GITOPS_*, registry, kubeconfig, auth and CORS settings.
"""
from functools import lru_cache

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(url: str) -> str:
    """Accept the usual PostgreSQL URL spellings, return one SQLAlchemy can use.

    `postgresql://...` is what the VM bootstrap writes to /etc/idp/database.env
    and what most tooling expects. SQLAlchemy needs the driver named, so we add
    `+psycopg` (psycopg 3). PostgreSQL only: the spec rules out SQLite.
    """
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    if url.startswith("postgresql+psycopg://"):
        return url
    # Deliberately does not echo the value: it contains the password.
    raise ValueError(
        "DATABASE_URL must be a PostgreSQL URL like "
        "postgresql://user:password@host:5432/dbname (SQLite is not supported)"
    )


class Settings(BaseSettings):
    # hide_input_in_errors: a bad DATABASE_URL must not print its password.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    # Required: there is deliberately no default, so we never guess credentials.
    database_url: SecretStr

    # Apps are served at https://<app-name>.<platform_domain>  (spec section 16).
    # Required: there is deliberately no default, we never invent your domain.
    platform_domain: str = Field(pattern=r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")

    # Pipeline worker threads. 1 = deployments run one at a time and the rest
    # wait in `pending`. That is the safe default: they share one Git working
    # tree and one Docker daemon.
    job_workers: int = Field(default=1, ge=1, le=8)

    # Cloning developer repositories (clone.py). Limits protect the VM's time
    # and disk from a hostile or accidental giant repository.
    git_binary: str = "git"
    clone_timeout_seconds: int = Field(default=60, ge=5, le=600)
    clone_max_mib: int = Field(default=100, ge=1, le=2048)

    @field_validator("database_url", mode="before")
    @classmethod
    def _postgres_only(cls, v):
        if isinstance(v, SecretStr):
            v = v.get_secret_value()
        return normalize_database_url(v)


@lru_cache
def get_settings() -> Settings:
    return Settings()
