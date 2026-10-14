"""Warehouse adapter layer: ONLY renders dbt profiles (targets dev + prod) and declares capabilities.
All data access goes through dbt itself (factory_tools.warehouse -> `dbt show`), never through
files on disk, so swapping DuckDB for Databricks is a profile change only."""
import os

class DuckDBAdapter:
    name = "duckdb"; dialect = "duckdb"
    single_writer = True   # duckdb file locks: avoid querying while the droid is building

    def profiles_yml(self, profile: str, worktree: str, prod_project: str) -> str:
        return f"""{profile}:
  target: dev
  outputs:
    dev:
      type: duckdb
      path: '{worktree}/warehouse.duckdb'
      threads: 4
    prod:   # baseline for compare: the main branch's warehouse, opened read-only
      type: duckdb
      path: '{prod_project}/jaffle_shop.duckdb'
      config_options:
        access_mode: READ_ONLY
      threads: 4
"""

class DatabricksAdapter:
    """pip install dbt-databricks; env DATABRICKS_HOST / DATABRICKS_HTTP_PATH / DATABRICKS_TOKEN.
    Each task builds into its own dev schema; `prod` target reads the production schema."""
    name = "databricks"; dialect = "databricks"; single_writer = False

    def profiles_yml(self, profile, worktree, prod_project):
        schema = "dbt_factory_" + os.path.basename(worktree).replace("-", "_")
        common = """      type: databricks
      host: "{{ env_var('DATABRICKS_HOST') }}"
      http_path: "{{ env_var('DATABRICKS_HTTP_PATH') }}"
      token: "{{ env_var('DATABRICKS_TOKEN') }}"
      catalog: "{{ env_var('DATABRICKS_CATALOG', 'main') }}"
      threads: 4"""
        return f"""{profile}:
  target: dev
  outputs:
    dev:
{common}
      schema: "{schema}"
    prod:
{common}
      schema: "{{{{ env_var('DATABRICKS_PROD_SCHEMA', 'analytics') }}}}"
"""

ADAPTERS = {"duckdb": DuckDBAdapter(), "databricks": DatabricksAdapter()}
def get_adapter(name=None): return ADAPTERS[name or os.environ.get("DBT_FACTORY_ADAPTER", "duckdb")]
