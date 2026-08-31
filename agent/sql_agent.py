"""LangChain SQL agent wiring for the basic Gemini-backed SQL assistant.

This module intentionally keeps the orchestration small for the basic
milestone: create a SQLDatabase over the approved BigQuery object, bind a
Gemini chat model, and let LangChain's SQL agent handle query planning.
"""

import os

from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent
from langchain_google_genai import ChatGoogleGenerativeAI


def create_demografy_agent():
    """Create the basic Demografy SQL agent.

    Returns:
        A LangChain SQL agent configured for Gemini and the approved
        BigQuery source.
    """
    # Restrict reflection and table exposure to the single approved object.
    # This narrows what the agent can inspect, but true read-only protection
    # must still come from the BigQuery credentials used at runtime.
    db = SQLDatabase.from_uri(
        "bigquery://demografy/prod_tables",
        include_tables=["a_master_view"],
        view_support=True,
    )

    # Gemini is authenticated with the API key from the environment. The
    # model is kept deterministic for SQL generation by using temperature=0.
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash-lite",
        google_api_key=os.getenv("GEMINI_API_KEY"),
        temperature=0,
    )

    # Keep the SQL agent configuration minimal for this milestone.
    # The few-shot prefix stays commented out for the later prompt milestone.
    agent = create_sql_agent(
        llm=llm,
        db=db,
        agent_type="openai-tools",
        # prefix=FEW_SHOT_PREFIX,  # Reserved for the later few-shot milestone.
        verbose=True,
    )
    return agent
