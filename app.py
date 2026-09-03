import streamlit as st

from auth.rbac import (
    get_question_limit,
    get_questions_remaining,
    can_ask_question
)
from agent.sql_agent import create_demografy_agent

# Instantiate the Demografy agent at startup (eager creation).
# Store it in session_state so it survives Streamlit reruns.
try:
    if "demografy_agent" not in st.session_state:
        st.session_state.demografy_agent = create_demografy_agent()
except ModuleNotFoundError as e:
    # Missing dependencies — keep a None placeholder and let the handler
    # show a helpful message when a user asks a question.
    st.session_state.demografy_agent = None
    st.session_state.demografy_agent_error = (
        "The SQL agent dependencies are not installed. "
        "Run `pip install -r requirements.txt` in your virtualenv. "
        f"Details: {e}"
    )
except Exception as e:
    st.session_state.demografy_agent = None
    st.session_state.demografy_agent_error = (
        "Failed to create the Demografy agent at startup: "
        f"{e}"
    )


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

    </style>
    """,
    unsafe_allow_html=True
)


# ---------------------------------------------------
# SESSION STATE
# ---------------------------------------------------

if "messages" not in st.session_state:
    st.session_state.messages = []

if "questions_used" not in st.session_state:
    st.session_state.questions_used = 0


# ---------------------------------------------------
# TEMPORARY USER
# ---------------------------------------------------
#
# Later this value will come from BigQuery:
# demografy.ref_tables.dev_customers
#
# Change this to:
#
# "free"
# "basic"
# "pro"
#
# to test the different plans.
# ---------------------------------------------------

customer_tier = "pro"


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

    try:
        st.image(
            "assets/logo.png",
            width=180
        )
    except:
        st.title("Demografy")

    st.divider()

    st.subheader("Your Plan")

    if customer_tier == "pro":
        display_tier = "Advanced / Pro"
    else:
        display_tier = customer_tier.title()

    st.markdown(
        f"""
        <div class="plan-badge">
            {display_tier}
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown("### Question allowance")

    st.metric(
        label="Questions remaining",
        value=questions_remaining
    )

    st.write(
        f"{st.session_state.questions_used} used "
        f"of {question_limit}"
    )

    progress = (
        st.session_state.questions_used
        / question_limit
    )

    st.progress(min(progress, 1.0))

    st.caption(
        "Question allowance resets with a new session."
    )


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
        "You have reached your question limit "
        "for this session."
    )

    st.info(
        "Please upgrade your plan or start a new "
        "session to continue asking questions."
    )


user_question = st.chat_input(
    "Ask a demographic question...",
    disabled=input_disabled
)


# ---------------------------------------------------
# HANDLE QUESTION
# ---------------------------------------------------

if user_question:

    # Add user message
    st.session_state.messages.append(
        {
            "role": "user",
            "content": user_question
        }
    )

    with st.chat_message("user"):
        st.write(user_question)


    # -----------------------------------------------
    # COUNT THE QUESTION
    # -----------------------------------------------

    st.session_state.questions_used += 1


    # -----------------------------------------------
    # RUN SQL AGENT
    # Use the LangChain SQL agent to answer the question.
    # Create the agent lazily to avoid startup cost when not needed.
    # -----------------------------------------------

    agent = st.session_state.get("demografy_agent")

    if agent is None:
        # Startup failed earlier — show captured error or a generic message.
        response = st.session_state.get(
            "demografy_agent_error",
            "The Demografy data agent is not available."
        )
    else:
        try:
            # AgentExecutor / LangChain agents expose a simple `run` method.
            response = agent.run(user_question)
        except Exception as e:
            response = (
                "Sorry — the data agent failed to answer your question. "
                f"Error: {e}"
            )

    # Normalize agent responses into a readable string for the UI.
    def _format_agent_response(r):
        if isinstance(r, list):
            out = []
            for item in r:
                if isinstance(item, dict) and "text" in item:
                    out.append(item["text"])
                else:
                    out.append(str(item))
            return "\n\n".join(out)
        if isinstance(r, dict):
            return r.get("text") or r.get("output") or str(r)
        return str(r)

    response = _format_agent_response(response)


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