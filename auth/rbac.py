"""RBAC helpers for tier lookup.

Lookup the `tier` for a given `user_id` from `demografy.ref_tables.dev_customers`.
"""

def get_user_tier(user_id, client=None):
    """Return the tier for user_id.

    Placeholder: query the dev_customers table using `client` (BigQuery wrapper).
    For now, return 'free' as a default.
    """
    # TODO: implement real lookup
    return "free"
