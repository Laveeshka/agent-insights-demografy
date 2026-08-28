"""BigQuery client wrapper.

This module should wrap authentication and querying of BigQuery.
"""
import os

class BigQueryClient:
    def __init__(self, credentials_path=None, project=None):
        self.credentials_path = credentials_path or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        self.project = project or os.getenv("BIGQUERY_PROJECT")

    def query(self, sql: str):
        """Execute SQL and return rows.

        Placeholder: integrate google-cloud-bigquery client here.
        """
        raise NotImplementedError("BigQuery query execution not implemented in scaffold")
