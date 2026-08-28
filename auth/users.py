"""Simple user utilities."""

def validate_user_id(user_id: str) -> bool:
    """Validate the provided user_id format.

    This is a placeholder.
    """
    if not user_id:
        return False
    # simple check for prototype IDs like 'user_001'
    return isinstance(user_id, str) and user_id.startswith("user_")
