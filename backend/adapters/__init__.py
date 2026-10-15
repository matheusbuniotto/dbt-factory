"""Legacy adapter registry: dialect + capabilities only. Per-task dbt profiles are rendered from the
project's OWN profiles.yml by projects.render_task_profile (dev isolated per task, prod read-only). All data
access goes through dbt itself (factory_tools.warehouse -> `dbt show`), never through files on disk."""

import os


class Adapter:
    def __init__(self, name, dialect, single_writer=False):
        self.name, self.dialect, self.single_writer = name, dialect, single_writer


ADAPTERS = {
    "duckdb": Adapter("duckdb", "duckdb", single_writer=True),  # duckdb file locks: no queries while building
    "databricks": Adapter("databricks", "databricks"),
    "snowflake": Adapter("snowflake", "snowflake"),
    "bigquery": Adapter("bigquery", "bigquery"),
    "postgres": Adapter("postgres", "postgres"),
}


def get_adapter(name=None):
    return ADAPTERS.get(name or os.environ.get("DBT_FACTORY_ADAPTER", "duckdb"), ADAPTERS["duckdb"])
