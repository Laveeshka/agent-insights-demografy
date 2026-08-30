"""BigQuery client wrapper.

Simple wrapper around `google.cloud.bigquery.Client` that respects the
`GOOGLE_APPLICATION_CREDENTIALS` and `BIGQUERY_PROJECT` environment variables.
"""
import os
from typing import Iterable

from google.cloud import bigquery


class BigQueryClient:
    def __init__(self, credentials_path: str | None = None, project: str | None = None):
        """Create a BigQuery client."""
        self.credentials_path = credentials_path or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        self.project = project or os.getenv("BIGQUERY_PROJECT")

        if self.credentials_path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = self.credentials_path

        if bigquery is None:
            raise RuntimeError("google-cloud-bigquery is not installed")

        self.client = bigquery.Client(project=self.project) if self.project else bigquery.Client()

    def query(self, sql: str, timeout: int = 30) -> list[object]:
        """Execute SQL and return result rows as a list.

        Raises: exceptions from the BigQuery client on failure.
        """
        query_job = self.client.query(sql, timeout=timeout)
        return list(query_job.result())

    def list_tables(self, dataset: str) -> Iterable[str]:
        """List table IDs in a dataset (e.g. 'prod_tables')."""
        dataset_ref = self.client.dataset(dataset)
        tables = self.client.list_tables(dataset_ref)
        return [t.table_id for t in tables]

    def get_table_schema(self, table_full_name: str) -> list[dict]:
        """Return the schema of `table_full_name` as a list of dicts.

        Example return element: {"name": "sa2_name", "type": "STRING", "mode": "NULLABLE", "description": "..."}
        ``table_full_name`` should be fully qualified, e.g. `demografy.prod_tables.a_master_view`.
        """
        table = self.client.get_table(table_full_name)
        schema = []
        for field in table.schema:
            schema.append({
                "name": field.name,
                "type": field.field_type,
                "mode": field.mode,
                "description": field.description,
            })
        return schema

    def sample_rows(self, table_full_name: str, limit: int = 10) -> list[dict]:
        """Return up to `limit` sample rows from the table as list of dicts.

        Uses a simple `SELECT * FROM <table> LIMIT <limit>` query. Useful for
        quick inspection of state values and KPI ranges during Week 1.
        """
        sql = f"SELECT * FROM `{table_full_name}` LIMIT {int(limit)}"
        rows = self.query(sql)
        return [dict(r) for r in rows]

