import streamlit as st

from auth.rbac import (
    get_question_limit,
    get_questions_remaining,
    can_ask_question
)

from auth.users import validate_user

# ---------------------------------------------------
# PAGE CONFIGURATION
# ---------------------------------------------------

st.set_page_config(
    page_title="Demografy Insights",
    page_icon="💬",
    layout="wide"
)

# ---------------------------------------------------
# CUSTOM DEMOGRAFY STYLING
# ---------------------------------------------------

st.markdown(
    """
    <style>

    .main-title {
        font-size: 38px;
        font-weight: 700;
        margin-bottom: 0px;
    }

    .subtitle {
        font-size: 17px;
        color: #6B7280;
        margin-bottom: 30px;
    }

    .plan-badge {
        display: inline-block;
        padding: 6px 12px;
        border-radius: 20px;
        background-color: #7C3AED;
        color: white;
        font-size: 13px;
        font-weight: 600;
    }

    .question-counter {
        padding: 14px;
        border-radius: 10px;
        background-color: #F5F3FF;
        margin-top: 10px;
        margin-bottom: 15px;
    }
    
/* Make Streamlit buttons clearly visible */
div.stButton > button {
    background-color: #7C3AED;
    color: white;
    border: none;
    border-radius: 8px;
    padding: 0.5rem 1rem;
    font-weight: 600;
}

/* Make text input border visible */
div[data-baseweb="input"] {
    border: 1px solid #D1D5DB;
    border-radius: 8px;
}
    </style>
    """,
    unsafe_allow_html=True
)


# ---------------------------------------------------
# SESSION STATE
# ---------------------------------------------------

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "user" not in st.session_state:
    st.session_state.user = None

if "messages" not in st.session_state:
    st.session_state.messages = []

if "questions_used" not in st.session_state:
    st.session_state.questions_used = 0
    
# ---------------------------------------------------
# LOGIN SCREEN
# ---------------------------------------------------

if not st.session_state.logged_in:

    st.image("assets/logo.png", width=180)

    st.write("Sign in to access demographic insights.")

    user_id = st.text_input(
        "User ID",
        placeholder="Example: user_003"
    )

    login_button = st.button(
        "Sign in",
        type="primary"
    )

    if login_button:
        if not user_id:
            st.warning("Please enter your User ID.")

        else:
            user = validate_user(user_id.strip())

            if user is None:
                st.error("User not found or account is inactive.")

            else:
                st.session_state.logged_in = True
                st.session_state.user = user
                st.session_state.questions_used = 0
                st.session_state.messages = []

                st.rerun()

    st.stop()
    
# ---------------------------------------------------
#  USER IS NOW LOGGED IN
# ---------------------------------------------------

customer_tier = st.session_state.user["tier"]

# ---------------------------------------------------
# LOGGED-IN USER DETAILS
# ---------------------------------------------------

current_user = st.session_state.user

user_id = current_user["user_id"]
email = current_user["email"]
customer_tier = current_user["tier"]


# ---------------------------------------------------
# QUESTION LIMIT
# ---------------------------------------------------

question_limit = get_question_limit(customer_tier)

questions_remaining = get_questions_remaining(
    customer_tier,
    st.session_state.questions_used
)


# ---------------------------------------------------
# PLAN INFORMATION
# ---------------------------------------------------

question_limit = get_question_limit(customer_tier)

questions_remaining = get_questions_remaining(
    customer_tier,
    st.session_state.questions_used
)

# ---------------------------------------------------
# SIDEBAR
# ---------------------------------------------------

with st.sidebar:

    st.title("Demografy")

    st.write("Signed in as")

    st.write(
        f"**{st.session_state.user['email']}**"
    )

    st.caption(
        f"User ID: {st.session_state.user['user_id']}"
    )

    st.divider()

    st.subheader("Your Plan")

    display_tier = customer_tier.title()

    if customer_tier == "pro":
        display_tier = "Advanced / Pro"

    st.write(f"**{display_tier}**")

    st.metric(
        "Questions remaining",
        questions_remaining
    )

    st.write(
        f"{st.session_state.questions_used} "
        f"used of {question_limit}"
    )

    st.progress(
        min(
            st.session_state.questions_used
            / question_limit,
            1.0
        )
    )

    if st.button("Log out"):

        st.session_state.logged_in = False
        st.session_state.user = None
        st.session_state.messages = []
        st.session_state.questions_used = 0

        st.rerun()

# ---------------------------------------------------
# MAIN APPLICATION
# ---------------------------------------------------

st.markdown(
    """
    <div class="main-title">
        Demografy Insights
    </div>

    <div class="subtitle">
        Ask questions about Australian demographic data.
    </div>
    """,
    unsafe_allow_html=True
)

# ---------------------------------------------------
# DISPLAY CHAT HISTORY
# ---------------------------------------------------

for message in st.session_state.messages:

    with st.chat_message(message["role"]):

        st.write(message["content"])


# ---------------------------------------------------
# QUESTION LIMIT WARNINGS
# ---------------------------------------------------

if customer_tier == "pro" and questions_remaining == 5:

    st.warning(
        "You have 5 questions remaining in your "
        "Advanced / Pro plan for this session."
    )

elif customer_tier == "basic" and questions_remaining == 5:

    st.warning(
        "You have 5 questions remaining in your "
        "Basic plan for this session."
    )

elif customer_tier == "free" and questions_remaining == 1:

    st.warning(
        "You have only 1 question remaining "
        "in your Free plan."
    )
    
# ---------------------------------------------------
# CHAT INPUT
# ---------------------------------------------------

input_disabled = not can_ask_question(
    customer_tier,
    st.session_state.questions_used
)

if input_disabled:

    st.error(
        "You have reached your question limit for this session."
    )

    if customer_tier == "free":
        st.info(
            "You've used all 5 questions included in your Free plan. "
            "Upgrade your plan for a higher question allowance."
        )

    elif customer_tier == "basic":
        st.info(
            "You've used all 20 questions included in your Basic plan. "
            "Upgrade to Pro for a higher question allowance."
        )

    elif customer_tier == "pro":
        st.info(
            "You've used all 50 questions available in your Pro plan "
            "for this session."
        )


# IMPORTANT:
# user_question must be defined on every run
user_question = st.chat_input(
    "Ask a demographic question...",
    disabled=input_disabled
)

# ---------------------------------------------------
# HANDLE QUESTION
# ---------------------------------------------------

if user_question:

    st.session_state.messages.append(
        {
            "role": "user",
            "content": user_question
        }
    )

    with st.chat_message("user"):
        st.write(user_question)

    st.session_state.questions_used += 1

    response = (
        "Thanks for your question. "
        "The Demografy data agent will process this question "
        "once the AI agent is connected."
    )

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": response
        }
    )

    with st.chat_message("assistant"):
        st.write(response)

    st.rerun()
    
    # -----------------------------------------------
    # COUNT THE QUESTION
    # -----------------------------------------------

    st.session_state.questions_used += 1


    # -----------------------------------------------
    # TEMPORARY RESPONSE
    #
    # Later LangChain / Gemini will replace this.
    # -----------------------------------------------

    response = (
        "Thanks for your question. "
        "The Demografy data agent will process "
        "this question once the AI agent is connected."
    )


    # Add assistant response
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": response
        }
    )

    with st.chat_message("assistant"):
        st.write(response)


    # Refresh the page so sidebar counter changes
    st.rerun()