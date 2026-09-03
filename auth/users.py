TEST_USERS = {
    "user_001": {
        "email": "free@example.com",
        "tier": "free",
        "is_active": True
    },
    "user_002": {
        "email": "basic@example.com",
        "tier": "basic",
        "is_active": True
    },
    "user_003": {
        "email": "pro@example.com",
        "tier": "pro",
        "is_active": True
    },
    "user_004": {
        "email": "inactive@example.com",
        "tier": "pro",
        "is_active": False
    }
}


def validate_user(user_id):
    """
    Validate a test user.

    Later this function will query
    demografy.ref_tables.dev_customers.
    """

    user = TEST_USERS.get(user_id)

    # User ID does not exist
    if user is None:
        return None

    # User exists but account is inactive
    if not user["is_active"]:
        return None

    # Valid active user
    return {
        "user_id": user_id,
        "email": user["email"],
        "tier": user["tier"]
    }