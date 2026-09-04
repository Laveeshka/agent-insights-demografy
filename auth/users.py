"""Backend user lookup and login utilities."""

import os
from typing import Any

from google.cloud import bigquery


CUSTOMERS_TABLE = "ref_tables.dev_customers"
SUPPORTED_TIERS = {"free", "basic", "pro"}

def validate_user_id(user_id: str) -> bool:
    """Validate the provided user_id format.

    This is a placeholder.
    """
    if not user_id:
        return False
    # simple check for prototype IDs like 'user_001'
    return isinstance(user_id, str) and user_id.startswith("user_")


def authenticate_user(user_id: str, bigquery_client: Any) -> dict:
    """Look up a user and return an authenticated tier snapshot."""
    normalized_user_id = user_id.strip() if isinstance(user_id, str) else ""
    if not validate_user_id(normalized_user_id):
        return {
            "authenticated": False,
            "user_id": None,
            "is_active": False,
            "tier": None,
            "error": "Invalid user ID.",
        }

    project = os.getenv("BIGQUERY_PROJECT", "demografy")
    query = f"""
        SELECT user_id, is_active, tier
        FROM `{project}.{CUSTOMERS_TABLE}`
        WHERE user_id = @user_id
        LIMIT 1
    """

    try:
        rows = bigquery_client.query(
            query,
            query_parameters=[
                bigquery.ScalarQueryParameter(
                    "user_id",
                    "STRING",
                    normalized_user_id,
                )
            ],
        )
    except Exception as exc:
        return {
            "authenticated": False,
            "user_id": normalized_user_id,
            "is_active": False,
            "tier": None,
            "error": f"Unable to verify user: {exc}",
        }

    if not rows:
        return {
            "authenticated": False,
            "user_id": normalized_user_id,
            "is_active": False,
            "tier": None,
            "error": "User was not found.",
        }

    customer = dict(rows[0])
    if not customer.get("is_active", False):
        return {
            "authenticated": False,
            "user_id": normalized_user_id,
            "is_active": False,
            "tier": customer.get("tier"),
            "error": "Your account is inactive. Please contact support.",
        }

    tier = str(customer.get("tier") or "").strip().lower()
    if tier not in SUPPORTED_TIERS:
        return {
            "authenticated": False,
            "user_id": normalized_user_id,
            "is_active": True,
            "tier": tier or None,
            "error": "Your account has an invalid subscription tier. Please contact support.",
        }

    return {
        "authenticated": True,
        "user_id": normalized_user_id,
        "is_active": True,
        "tier": tier,
        "error": None,
    }
