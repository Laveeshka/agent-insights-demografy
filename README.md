# Demografy Insights Chatbot

This repository contains an implementation of the MVP Insights Chatbot.

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

- Golden dataset: `eval/golden_dataset.json` contains the first 5 evaluation questions using the real schema. 
- Optional LangSmith tracing: set `LANGSMITH_API_KEY` in your `.env` to enable tracing.