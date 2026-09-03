"""LangChain SQL agent wiring for the basic Gemini-backed SQL assistant.

This module intentionally keeps the orchestration small for the basic
milestone: create a SQLDatabase over the approved BigQuery object, bind a
Gemini chat model, and let LangChain's SQL agent handle query planning.
"""

import os

from langchain_community.utilities import SQLDatabase
from langchain_community.agent_toolkits import create_sql_agent
from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

# Load .env so local development credentials (GOOGLE_APPLICATION_CREDENTIALS)
# and GEMINI_API_KEY are available when running locally.
load_dotenv()

# Use the project's BigQuery client wrapper to ensure credentials are set
# consistently across the app during local testing.
from db.bigquery_client import BigQueryClient


def create_demografy_agent():
    """Create the basic Demografy SQL agent.

    Returns:
        A LangChain SQL agent configured for Gemini and the approved
        BigQuery source.
    """
    try:
        BigQueryClient()
    except Exception:
        # If the wrapper cannot be created (missing google libs), let
        # SQLAlchemy/sqlalchemy-bigquery surface the error below.
        pass

    db = SQLDatabase.from_uri(
        "bigquery://demografy/prod_tables",
        include_tables=["a_master_view"]
    )

    # Gemini is authenticated with the API key from the environment. The
    # model is kept deterministic for SQL generation by using temperature=0.
    llm = ChatGoogleGenerativeAI(
        model="gemini-3.5-flash",
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
