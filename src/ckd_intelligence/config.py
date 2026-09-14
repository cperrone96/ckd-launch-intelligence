"""Runtime configuration and database namespace contracts."""

import re
from enum import StrEnum
from typing import Self

from pydantic import computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseBackend(StrEnum):
    """Supported analytical persistence backends."""

    DUCKDB = "duckdb"
    POSTGRESQL = "postgresql"


class Settings(BaseSettings):
    """Environment-driven settings with a credential-free local default."""

    model_config = SettingsConfigDict(
        env_prefix="CKD_",
        extra="ignore",
        frozen=True,
    )

    database_backend: DatabaseBackend = DatabaseBackend.DUCKDB
    database_url: str = "duckdb:///data/ckd_intelligence.duckdb"
    raw_schemas: tuple[str, ...] = (
        "raw_nhanes",
        "raw_meps",
        "raw_partd",
        "raw_trials",
        "raw_synpuf",
    )
    observed_schema: str = "analytics_observed"
    synthetic_schema: str = "analytics_synthetic"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_schemas(self) -> tuple[str, ...]:
        """Return every raw and analytical namespace in creation order."""

        return (*self.raw_schemas, self.observed_schema, self.synthetic_schema)

    @model_validator(mode="after")
    def validate_unique_schemas(self) -> Self:
        """Fail closed if evidence namespaces overlap."""

        if len(self.all_schemas) != len(set(self.all_schemas)):
            raise ValueError("Schema names must be unique")
        if any(re.fullmatch(r"[a-z_][a-z0-9_]*", name) is None for name in self.all_schemas):
            raise ValueError("Schema names must be valid SQL identifiers")
        return self
