TIER_LIMITS = {
    "free": 5,
    "basic": 20,
    "pro": 50
}


def get_question_limit(tier):
    """
    Return the maximum number of questions allowed
    for the customer's subscription tier.
    """

    return TIER_LIMITS.get(tier.lower(), 5)


def get_questions_remaining(tier, questions_used):
    """
    Calculate how many questions the customer
    has left in the current browser session.
    """

    limit = get_question_limit(tier)

    return max(limit - questions_used, 0)


def can_ask_question(tier, questions_used):
    """
    Return True if the customer still has
    questions available.
    """

    return get_questions_remaining(tier, questions_used) > 0