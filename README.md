# Demografy Insights Chatbot

This repository contains an implementation of the MVP Insights Chatbot: a Streamlit
chat app that lets authenticated users ask natural-language questions about
Australian demographic data and get grounded, data-backed answers.

A Gemini-backed SQL agent ([agent/sql_agent.py](agent/sql_agent.py)) turns each
question into a read-only BigQuery query against the approved
`demografy.prod_tables.a_master_view` table, executes it, and generates a
natural-language answer from the actual returned rows — the model is never
allowed to answer from memory. Every generated query is validated at runtime
(read-only, approved table only, aliased columns, row-limited) before it can
reach BigQuery, and one bounded repair attempt is made if the first query
fails validation or execution.

What the chatbot can do

- Answer questions about suburbs, states, population, and the dataset's KPI
  scores (prosperity, diversity, migration footprint, learning level, social
  housing, resident equity/home ownership, rental access, resident anchor,
  household mobility, young family value), including blended/composite scores
  across multiple KPIs.
- Rank, filter, and compare suburbs or states (top N, above/below a threshold,
  highest/lowest average, etc.), with data-quality rules applied automatically
  (excluding non-geographic placeholder rows and near-empty areas).
- Decline out-of-scope questions (financial prices, current events, weather,
  general knowledge/math) instead of producing SQL for them.
- Enforce per-tier question limits per session via role-based access control
  (`auth/`), based on the authenticated user's plan (Free, Basic, Pro).

Example questions

- "Top 3 suburbs in VIC by diversity index"
- "Average prosperity score in Queensland"
- "Which Sydney suburb has the highest population density?"
- "Compare median age across Melbourne and Brisbane"
- "Which state has the highest average learning level?"
- "Suburbs where the average of learning level and resident equity is above 75%"

Chart generation

- When a query returns 5 or more rows, the app automatically renders an Altair
  chart alongside the answer — no need to explicitly ask for one.
- The chart type (bar, line, or scatter) is inferred from the shape of the
  returned columns (categorical vs. numeric vs. time-like), or from an
  explicit request in the question (e.g. "as a bar chart", "line graph",
  "scatter plot"; pie requests are rendered as bar charts). If the shape is
  ambiguous, the LLM is asked to pick a chart type as a fallback.
- Charts use brand styling: humanized axis labels, KPI columns automatically
  shown as percentages, and an underlying data table displayed beneath the
  chart.
- If the user explicitly asks for a chart but the result set is too small
  (fewer than 5 rows), the chatbot explains that there isn't enough data to
  chart instead of rendering one.

Quick start

- Copy `.env.example` to `.env` and fill in real credentials. Never commit secrets.
- Create and activate a Python virtual environment, then install dependencies.

macOS / Linux (bash / zsh):

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows (PowerShell):

```powershell
python -m venv .venv
. .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Windows (Command Prompt):

```cmd
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
```

- Run the Streamlit app locally after activation:

```bash
streamlit run app.py
```

Python version prerequisite

- Recommended: Install Python 3.9 or higher


Repository layout

- `app.py` — Streamlit entrypoint
- `agent/` — LangChain SQL agent scaffolding, prompts, and helper tools
- `auth/` — RBAC and user utilities (tier lookup)
- `db/` — BigQuery client wrapper
- `eval/` — Golden dataset and evaluation scaffolds
- `.streamlit/config.toml` — Streamlit theme and branding

Tracing and evaluation

- Golden dataset: [eval/golden_dataset.json](eval/golden_dataset.json) contains
  12 evaluation questions covering exact-match, tolerance, ordering,
  row-count, and state-match validation types, each paired with a
  hand-written `expected_sql` query against the real schema.
- Tracing: set `LANGCHAIN_TRACING_V2=true` plus `LANGSMITH_API_KEY` (or the
  legacy `LANGCHAIN_API_KEY`) in your `.env` to send SQL-generation,
  query-result, and answer-generation events to LangSmith
  ([eval/tracing.py](eval/tracing.py)). Optionally set `LANGSMITH_ENDPOINT`
  and `LANGSMITH_PROJECT`. Tracing is opt-in: with no flag or key set, the
  agent uses a no-op tracer and runs unaffected. The same tracer instruments
  both the live app and the eval pipeline, and also records each eval run's
  result per question when enabled.
- Running the eval pipeline: with your `.env` configured (BigQuery
  credentials and `GEMINI_API_KEY`), run:

```bash
python -m eval.run_eval
```

  This runs every golden question through the live `SQLAgent`, computes
  ground truth by executing each question's `expected_sql` directly against
  BigQuery, validates the agent's result against that ground truth, and asks
  an LLM judge ([eval/judge.py](eval/judge.py)) to score the natural-language
  answer from 1-5. A pass/fail line is printed per question, a summary
  (accuracy and average judge score) is printed at the end, and the full
  structured report is written to [eval/eval_report.json](eval/eval_report.json).
