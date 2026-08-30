import streamlit as st


# Page configuration
st.set_page_config(
    page_title="Demografy Insights Chatbot",
    page_icon="💬",
    layout="centered"
)


# App title
st.title("Demografy Insights Chatbot")

st.write(
    "Ask questions about Australian demographic data."
)


# Store conversation history
if "messages" not in st.session_state:
    st.session_state.messages = []


# Display previous messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])


# Chat input
user_question = st.chat_input(
    "Ask a demographic question..."
)


# Process the user's question
if user_question:

    # Save and display user message
    st.session_state.messages.append(
        {
            "role": "user",
            "content": user_question
        }
    )

    with st.chat_message("user"):
        st.write(user_question)


    # Temporary response for Week 1
    response = (
        "Thanks for your question. "
        "The Demografy data agent will be connected here."
    )


    # Save and display assistant response
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": response
        }
    )

    with st.chat_message("assistant"):
        st.write(response)