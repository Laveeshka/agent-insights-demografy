import base64

import altair as alt
import pandas as pd
import streamlit as st

from auth.rbac import (
    get_question_limit,
    get_questions_remaining,
    can_ask_question
)
from auth.users import authenticate_user

from db.bigquery_client import BigQueryClient
from agent.sql_agent import create_demografy_agent
from agent.tools import map_agent_result_to_message
from agent.tools import build_chart_data

# ---------------------------------------------------
# PAGE CONFIGURATION
# ---------------------------------------------------

st.set_page_config(
    page_title="Demografy Insights",
    page_icon="💬",
    layout="wide"
)


def _b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


LOGO_ICON_B64 = _b64("assets/logo_icon.png")

EXAMPLE_QUESTIONS = [
    "Average prosperity score in Queensland",
    "Which Sydney suburb has the highest population density?",
    "Compare median age across Melbourne and Brisbane",
    "Suburbs where the average of learning level and resident equity is above 75%",
]

# Brand mauve accent (same tone as the assistant chat avatar) used for chart marks.
CHART_MAUVE = "#cb6ce6"


def _humanize(column_name: str) -> str:
    """Turn a SQL alias like 'diversity_index' into 'Diversity Index'."""
    return str(column_name).replace("_", " ").title()


def _is_percent_metric(column_name: str) -> bool:
    """KPI columns are percentages; population/row counts are not."""
    lowered = str(column_name).lower()
    return "population" not in lowered and "count" not in lowered


def _as_percent(series: pd.Series, column_name: str) -> pd.Series:
    """Scale a 0-1 fraction KPI column up to percentage points (e.g. diversity
    index) so it reads like the rest of the percentage-scale KPIs. Non-KPI
    numeric columns (population, counts) are left untouched."""
    if _is_percent_metric(column_name) and len(series) and series.abs().max() <= 1.5:
        return series * 100
    return series


def render_chart(chart: dict) -> None:
    """Render a chart with brand styling: transparent background, mauve
    marks, humanized column labels, and KPI values shown as percentages
    instead of raw 0-1 fractions."""
    if not chart or not chart.get("enough_rows"):
        return

    df = pd.DataFrame(chart["data"] or [])
    x_col, y_col, chart_type = chart["x"], chart["y"], chart["chart_type"]

    for col in (x_col, y_col):
        if pd.api.types.is_numeric_dtype(df[col]):
            df[col] = _as_percent(df[col], col)

    df = df.rename(columns={col: _humanize(col) for col in df.columns})
    x_label, y_label = _humanize(x_col), _humanize(y_col)
    y_title = f"{y_label} (%)" if _is_percent_metric(y_col) else y_label
    y_tooltip_format = ".2f" if _is_percent_metric(y_col) else ",.0f"

    base = alt.Chart(df)
    if chart_type == "scatter":
        x_title = f"{x_label} (%)" if _is_percent_metric(x_col) else x_label
        mark = base.mark_circle(size=90, color=CHART_MAUVE).encode(
            x=alt.X(f"{x_label}:Q", title=x_title, axis=alt.Axis(titleLimit=1000)),
            y=alt.Y(f"{y_label}:Q", title=y_title, axis=alt.Axis(titleLimit=1000)),
            tooltip=list(df.columns),
        )
    else:
        encode_kwargs = dict(
            x=alt.X(f"{x_label}:N", title=x_label, sort="-y", axis=alt.Axis(titleLimit=1000)),
            y=alt.Y(f"{y_label}:Q", title=y_title, axis=alt.Axis(titleLimit=1000)),
            tooltip=[
                alt.Tooltip(f"{x_label}:N", title=x_label),
                alt.Tooltip(f"{y_label}:Q", title=y_label, format=y_tooltip_format),
            ],
        )
        mark = (
            base.mark_line(color=CHART_MAUVE, point=True).encode(**encode_kwargs)
            if chart_type == "line"
            else base.mark_bar(color=CHART_MAUVE).encode(**encode_kwargs)
        )

    styled = (
        mark.properties(background="transparent", height=320, width="container", padding={"left": 10, "top": 10, "right": 10, "bottom": 5})
        .configure_view(strokeWidth=0)
        .configure_axis(labelColor="#272d2d", titleColor="#272d2d", gridColor="#e4e1ec")
    )
    st.altair_chart(styled, use_container_width=True)
    st.dataframe(df, use_container_width=True)

# ---------------------------------------------------
# SHARED STYLING (applies to both screens)
# ---------------------------------------------------

st.markdown(
    """
    <style>
    /* CSS-only st.markdown calls (this one included) render a <style> tag
       inline as their only content. The <style> itself has zero visual
       height, but its stElementContainer is still a real flex item in
       Streamlit's vertical block, so the block's fixed flex "gap" still
       reserves a full gap slot around it -- stacking up as visible empty
       space above the top bar. display:none removes it from flow entirely
       so it no longer counts toward the gap. */
    div[data-testid="stElementContainer"]:has(div[data-testid="stMarkdownContainer"] > style:only-child) {
        display: none !important;
    }

    /* Hide Streamlit's own top toolbar (Deploy button + menu) on both screens */
    [data-testid="stHeader"] { display: none; }

    /* Chat message bubbles: light tint of the Main Colour (Medium Slate Blue)
       instead of Streamlit's default grey, and brand-coloured avatar badges
       instead of the default red/yellow */
    [data-testid="stChatMessage"] {
        background: #f1e8fc;
        border-radius: 14px;
    }
    [data-testid="stChatMessageAvatarUser"] {
        background-color: #5e17eb !important;
    }
    [data-testid="stChatMessageAvatarAssistant"] {
        background-color: #cb6ce6 !important;
    }

    /* Top bar: brand gradient, "a little more still" calibration, and its
       own scoped button/progress styling so it doesn't affect other buttons */
    .st-key-topbar {
        background: linear-gradient(135deg, #dce9fa 0%, #ecd0f8 100%);
        border-radius: 16px;
        padding: 14px 18px 16px;
        margin-bottom: 22px;
    }
    .st-key-topbar div.stButton > button {
        background: transparent;
        border: 1.5px solid rgba(39,45,45,.35);
        color: #272d2d;
        border-radius: 999px;
        padding: 0.35rem 1rem;
        font-size: 13px;
        font-weight: 700;
    }
    .st-key-topbar div.stButton > button:hover {
        background: rgba(255,255,255,.55);
        border-color: #272d2d;
    }
    .st-key-topbar div[data-testid="stProgress"] {
        margin-top: 2px;
    }
    .topbar-who {
        display: flex;
        align-items: center;
        font-weight: 700;
        font-size: 14.5px;
        color: #272d2d;
        padding-top: 6px;
    }
    .topbar-who img { height: 20px; margin-right: 9px; }
    .topbar-plan { display: flex; align-items: center; gap: 10px; margin: 12px 0 6px; }
    .topbar-plan .tier-pill {
        background: #fff; color: #5e17eb; font-size: 11px; font-weight: 800;
        text-transform: uppercase; letter-spacing: .03em;
        padding: 3px 10px; border-radius: 999px; flex-shrink: 0;
    }
    .topbar-plan .plan-text { font-size: 12.5px; font-weight: 700; color: #272d2d; }

    /* Example-question cards (only present before the first message) */
    .st-key-examples div.stButton > button {
        width: 100%; text-align: left; white-space: normal; height: auto;
        min-height: 58px; display: flex; align-items: center;
        background: #fff; border: 1.5px solid #e4e1ec; border-radius: 13px;
        padding: 12px 14px; font-size: 13.5px; font-weight: 500; color: #272d2d;
    }
    .st-key-examples div.stButton > button:hover { border-color: #9a66ee; }

    /* Greeting */
    .chat-greeting { text-align: center; margin-bottom: 22px; }
    .chat-greeting h2 { font-size: 25px; font-weight: 700; color: #272d2d; margin-bottom: 4px; }
    .chat-greeting p { font-size: 14.5px; color: #5b6070; margin: 0; }

    /* Usage warning banners (brand annotation colours) */
    .warn-caution, .warn-alert {
        padding: 12px 14px; border-radius: 10px; font-size: 13.3px;
        line-height: 1.5; margin-bottom: 16px;
    }
    .warn-caution { background: #fff8e1; border: 1px solid #ffe082; color: #6b5000; }
    .warn-alert   { background: #fdece7; border: 1px solid #f6b8a4; color: #9a3412; }
    .warn-caution b, .warn-alert b { display: block; margin-bottom: 1px; }

    /* Login-only styling lives in the conditional block below */
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

    st.markdown(
        """
        <style>
        .stApp {
            background: #faf9fc;
        }
        .st-key-login-card {
            max-width: 400px;
            margin: 6vh auto 40px auto;
            background: radial-gradient(120% 100% at 50% -10%, #eef3fc 0%, #faf0fd 55%, #ffffff 100%);
            border-radius: 20px;
            padding: 40px 36px 32px;
            box-shadow: 0 12px 32px -12px rgba(0,60,150,.20);
        }
        .st-key-login-card [data-testid="stElementContainer"],
        .st-key-login-card [data-testid="stFullScreenFrame"],
        .st-key-login-card [data-testid="stFullScreenFrame"] > div {
            width: 100% !important;
            max-width: none !important;
        }
        .st-key-login-card [data-testid="stImage"] {
            display: flex !important; justify-content: center !important;
            width: 100% !important; max-width: none !important;
        }
        .st-key-login-card [data-testid="stImage"] img { margin: 0 auto; display: block; }
        .st-key-login-card [data-testid="stTextInputRootElement"] {
            background: #fff !important;
            border: 1.5px solid #e4e1ec !important;
            border-radius: 11px !important;
            height: 48px !important;
        }
        .st-key-login-card [data-testid="stTextInputField"] {
            background: #fff !important;
        }
        .st-key-login-card div.stButton > button {
            width: 100%; height: 48px; background: #5e17eb; color: #fff; border: none;
            border-radius: 11px; font-weight: 700; font-size: 15px;
            box-shadow: 0 10px 20px -8px rgba(94,23,235,.45);
        }
        .st-key-login-card div.stButton > button:hover { background: #4d13bf; }
        .login-title { text-align: center; font-size: 20px; font-weight: 700; color: #272d2d; margin: 4px 0 4px; }
        .login-sub { text-align: center; font-size: 13.5px; color: #5b6070; margin-bottom: 22px; }
        .login-alert {
            margin-top: 14px; padding: 10px 12px; border-radius: 10px;
            font-size: 13px; line-height: 1.5; background: #fdece7;
            border: 1px solid #f6b8a4; color: #9a3412;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    with st.container(key="login-card"):

        st.image("assets/logo.png", width=160)
        st.markdown('<div class="login-title">Welcome back</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="login-sub">Explore demographic trends, suburb growth, and KPI-driven insights - powered by BigQuery + Gemini</div>',
            unsafe_allow_html=True
        )

        user_id = st.text_input(
            "User ID",
            placeholder="Example: user_003",
            label_visibility="collapsed"
        )

        login_button = st.button("Sign in", type="primary", use_container_width=True)

        if login_button:
            if not user_id:
                st.warning("Please enter your user id")

            else:
                # Create BigQuery client and authenticate the user
                try:
                    bq_client = BigQueryClient()
                except Exception as exc:
                    st.error(f"Unable to initialize BigQuery client: {exc}")
                    st.stop()

                auth_result = authenticate_user(user_id.strip(), bq_client)

                if not auth_result.get("authenticated"):
                    st.markdown(
                        f'<div class="login-alert">'
                        f'{auth_result.get("error") or "User not found or account is inactive."}'
                        f'</div>',
                        unsafe_allow_html=True
                    )
                else:
                    # Store a simple user snapshot for the session (user_id + tier)
                    st.session_state.logged_in = True
                    st.session_state.user = {
                        "user_id": auth_result.get("user_id"),
                        "tier": auth_result.get("tier"),
                    }
                    st.session_state.questions_used = 0
                    st.session_state.messages = []
                    # Keep client and agent in session state for reuse
                    st.session_state.bigquery_client = bq_client
                    st.session_state.agent = create_demografy_agent(bq_client)

                    st.rerun()

    st.stop()

# ---------------------------------------------------
#  USER IS NOW LOGGED IN
# ---------------------------------------------------

current_user = st.session_state.user

user_id = current_user["user_id"]
customer_tier = current_user["tier"]

# ---------------------------------------------------
# QUESTION LIMIT / PLAN INFORMATION
# ---------------------------------------------------

question_limit = get_question_limit(customer_tier)

questions_remaining = get_questions_remaining(
    customer_tier,
    st.session_state.questions_used
)

display_tier = customer_tier.title()

# ---------------------------------------------------
# CHAT BACKGROUND
# ---------------------------------------------------

st.markdown(
    """
    <style>
    .stApp {
        background: #ffffff;
    }
    .block-container {
        max-width: 900px;
        min-height: calc(100vh - 110px);
        margin: 0 auto;
        padding: 32px 32px 12px;
        background: linear-gradient(135deg, #eef3fc 0%, #faf0fd 55%, #faf9fc 100%);
        border-radius: 24px 24px 0 0;
    }
    [data-testid="stBottom"] > div {
        background: #ffffff;
    }
    [data-testid="stBottomBlockContainer"] {
        max-width: 900px;
        margin: 0 auto;
        padding: 16px 32px 24px;
        background: linear-gradient(135deg, #eef3fc 0%, #faf0fd 55%, #faf9fc 100%);
        border-radius: 0 0 24px 24px;
    }
    [data-testid="stChatInput"] > div {
        background: #fff !important;
        border-color: #e4e1ec !important;
    }
    [data-testid="stChatInputTextArea"] {
        background: #fff !important;
    }
    [data-testid="stChatInputSubmitButton"] {
        background: #5e17eb !important;
        color: #fff !important;
    }
    [data-testid="stChatInputSubmitButton"]:not(:disabled):hover {
        background: #4d13bf !important;
    }

    /* Scrollable chat area: fills the space between the top bar and the
       input bar, so long conversations scroll internally instead of
       pushing the input off screen. Transparent so the page gradient
       shows through instead of a boxed-in white panel. */
    .st-key-chat-scroll {
        height: calc(100vh - 330px) !important;
        min-height: 260px;
    }
    .st-key-chat-scroll > div {
        background: transparent !important;
        padding-bottom: 24px;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# ---------------------------------------------------
# TOP BAR: brand + plan/questions counter + sign out
# ---------------------------------------------------

with st.container(key="topbar"):

    top_left, top_right = st.columns([5, 1])

    with top_left:
        st.markdown(
            f'<div class="topbar-who">'
            f'<img src="data:image/png;base64,{LOGO_ICON_B64}">Demografy Insights'
            f'</div>',
            unsafe_allow_html=True
        )

    with top_right:
        if st.button("Sign out", key="signout_btn"):
            st.session_state.logged_in = False
            st.session_state.user = None
            st.session_state.messages = []
            st.session_state.questions_used = 0
            st.rerun()

    st.markdown(
        f'<div class="topbar-plan">'
        f'<span class="tier-pill">{display_tier}</span>'
        f'<span class="plan-text">{questions_remaining} of {question_limit} questions left</span>'
        f'</div>',
        unsafe_allow_html=True
    )

    st.progress(
        min(st.session_state.questions_used / question_limit, 1.0)
    )

# ---------------------------------------------------
# SCROLLABLE CHAT AREA (history, greeting/examples, limit warnings)
# ---------------------------------------------------

chat_area = st.container(key="chat-scroll", height=500, border=False, autoscroll=True)

with chat_area:

    # ---------------------------------------------------
    # DISPLAY CHAT HISTORY
    # ---------------------------------------------------

    for message in st.session_state.messages:

        with st.chat_message(message["role"]):
            st.write(message["content"])
            if message.get("chart"):
                render_chart(message["chart"])

    # ---------------------------------------------------
    # GREETING + EXAMPLE QUESTIONS (only before the first question)
    # ---------------------------------------------------

    example_clicked = None

    if not st.session_state.messages:

        st.markdown(
            f'<div class="chat-greeting">'
            f'<h2>Hi, {user_id} 👋</h2>'
            f'<p>Ask questions about Australian demographic data.</p>'
            f'</div>',
            unsafe_allow_html=True
        )

        with st.container(key="examples"):
            for row_start in range(0, len(EXAMPLE_QUESTIONS), 2):
                row_cols = st.columns(2)
                row_questions = EXAMPLE_QUESTIONS[row_start:row_start + 2]
                for j, question in enumerate(row_questions):
                    with row_cols[j]:
                        if st.button(question, key=f"example_{row_start + j}", use_container_width=True):
                            example_clicked = question

    # ---------------------------------------------------
    # QUESTION LIMIT WARNINGS
    # ---------------------------------------------------

    if questions_remaining == 2:
        st.markdown(
            f'<div class="warn-caution"><b>2 questions left</b>'
            f'You\'re on the {display_tier} plan ({question_limit} questions per session).</div>',
            unsafe_allow_html=True
        )

    elif questions_remaining == 1:
        upgrade_note = (
            "This is the last question available in your Pro plan for this session."
            if customer_tier == "pro"
            else "Upgrade your plan for a higher question allowance."
        )
        st.markdown(
            f'<div class="warn-alert"><b>This is your last question</b>{upgrade_note}</div>',
            unsafe_allow_html=True
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
) or example_clicked

# ---------------------------------------------------
# HANDLE QUESTION
# ---------------------------------------------------

if user_question:

    st.session_state.messages.append({"role": "user", "content": user_question})

    with chat_area:
        with st.chat_message("user"):
            st.write(user_question)

    # Ensure BigQuery client and agent exist in the session
    if "bigquery_client" not in st.session_state:
        try:
            st.session_state.bigquery_client = BigQueryClient()
        except Exception as exc:
            st.error(f"Unable to initialize BigQuery client: {exc}")
            st.stop()

    if "agent" not in st.session_state:
        st.session_state.agent = create_demografy_agent(st.session_state.bigquery_client)

    # Count the question
    st.session_state.questions_used += 1

    # Ask the SQL agent and display the result
    try:
        result = st.session_state.agent.answer_question(user_question)
    except Exception as exc:
        result = {"answer": None, "sql": None, "rows": [], "error": f"Agent error: {exc}"}

    # Map internal errors / empty results to human-friendly messages
    answer_text = map_agent_result_to_message(result)
    chart = build_chart_data(user_question, result.get("rows") or [])
    if not chart["enough_rows"] and len(result.get("rows") or []) >= 5:
        chart = build_chart_data(user_question, result.get("rows") or [], llm=st.session_state.agent.llm)
    if chart["requested"] and not chart["enough_rows"]:
        answer_text = (
            f"{answer_text}\n\n"
            "Not enough returned data to create a useful chart."
        )

    st.session_state.messages.append({"role": "assistant", "content": answer_text})
    if chart["enough_rows"]:
        st.session_state.messages[-1]["chart"] = chart

    with chat_area:
        with st.chat_message("assistant"):
            st.write(answer_text)
            render_chart(chart)

    # Refresh the page so the top bar counter changes
    st.rerun()
