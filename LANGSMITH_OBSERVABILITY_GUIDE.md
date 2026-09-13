# LangSmith Observability Setup for FinGraphRAG

This project already includes the LangSmith SDK and tracing hooks. The important part is to make sure the environment variables are loaded in a way that works with both the project’s config and LangSmith’s expected names.

## 1) Required environment variables

Use these in the project environment or in `src/.env`:

```env
GOOGLE_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.0-flash
EMBEDDING_MODEL=models/text-embedding-004
EMBEDDING_DIMENSIONS=768

QDRANT_URL=https://your-cluster.cloud.qdrant.io
QDRANT_API_KEY=your_qdrant_api_key
QDRANT_COLLECTION=financial_documents

NEO4J_URI=neo4j+s://your-instance.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_neo4j_password
NEO4J_DATABASE=neo4j

LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY=your_langsmith_api_key
LANGSMITH_PROJECT=FINGRAPHRAG

# Optional compatibility aliases used by this app
LANGCHAIN_API_KEY=your_langsmith_api_key
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=FINGRAPHRAG
```

> The app supports both `LANGSMITH_*` and `LANGCHAIN_*` names. This is intentional because some LangChain/LangSmith integrations expect one naming convention or the other.

## 2) How the project loads them

The app loads `.env` automatically from:

- `fingraphrag/.env`
- `fingraphrag/src/.env`

and then hydrates the runtime environment for LangSmith at startup.

## 3) Run the app with tracing enabled

From PowerShell:

```powershell
cd C:\Users\Os\Documents\PP\fingraphrag
..\.venv\Scripts\Activate.ps1
python -m src.main ask "Which companies are connected to the semiconductor industry?"
```

This triggers the LangGraph workflow and emits spans to LangSmith if the API key is valid.

## 4) Check health and trace status

```powershell
python -m src.main serve
```

Then open:

- http://127.0.0.1:8000/docs
- http://127.0.0.1:8000/health

Example:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Expected output includes:

```json
{
  "langsmith": "enabled"
}
```

## 5) What gets traced

This app uses `@traceable` on the main workflow nodes, so LangSmith records:

- query understanding
- retrieval step
- context construction
- answer synthesis

The trace output shows the LLM call, retrieval behavior, and decision flow for each request.

## 6) Best practices for observability

- Keep one canonical project name such as `FINGRAPHRAG`.
- Use separate environments for dev and prod if you run multiple apps.
- Review traces for latency, token usage, prompt quality, and retrieval quality.
- Validate that `LANGSMITH_API_KEY` is not expired.
- Do not commit `.env` files to source control.

## 7) Troubleshooting

If no traces appear:

1. Confirm the key is valid in LangSmith.
2. Confirm `LANGSMITH_TRACING=true` and/or `LANGCHAIN_TRACING_V2=true`.
3. Confirm the app is running in the same environment where the variables are loaded.
4. Run this command to print the actual runtime values:

```powershell
python -c "import os; print(os.getenv('LANGSMITH_API_KEY')); print(os.getenv('LANGCHAIN_API_KEY')); print(os.getenv('LANGSMITH_PROJECT')); print(os.getenv('LANGCHAIN_PROJECT'))"
```

## 8) Next recommended work

1. Validate the app runs end-to-end with tracing enabled.
2. Query the API several times and inspect traces in the LangSmith dashboard.
3. Add request IDs and session IDs to logs for easier debugging.
4. Add a small prompt/latency dashboard for production monitoring.

## 9) Useful commands summary

```powershell
cd C:\Users\Os\Documents\PP\fingraphrag
..\.venv\Scripts\Activate.ps1
python -m src.main ask "Which companies are connected to the semiconductor industry?"
python -m src.main serve
Invoke-RestMethod http://127.0.0.1:8000/health
```

This gives you working LangSmith tracing plus a clean observability baseline for the application.
