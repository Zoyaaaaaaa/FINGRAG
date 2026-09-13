# FinGraphRAG

FinGraphRAG is a CSV-powered financial GraphRAG service using Gemini, LangGraph, LangSmith, Qdrant Cloud, Neo4j, and in-process conversation memory.

## What Is Ready

- `src/ingestion.py` reads any CSV and writes its rows to Qdrant and Neo4j.
- `src/orchestrator.py` runs a LangGraph workflow: query understanding, hybrid retrieval, context construction, and Gemini synthesis.
- `src/api.py` exposes `/health`, `/query`, and `/memory/{session_id}`.
- `src/streamlit_app.py` provides an interactive web UI for querying and visualization.
- `src/main.py` provides `serve`, `ingest`, `ask`, and `ui` commands.
- LangSmith tracing is enabled automatically when its key is present.
- No Docker, local database process, or CSS file is required by the backend.

## Project Structure

```text
fingraphrag/
  .env                         # You provide this; never commit it
  pyproject.toml
  SYSTEM_ARCHITECTURE.md       # Complete system architecture documentation
  src/
    api.py                     # FastAPI application
    main.py                    # CLI
    ingestion.py               # Generic CSV loader
    orchestrator.py            # LangGraph + Gemini workflow
    streamlit_app.py           # Interactive web UI
    config/settings.py
    memory/conversation_memory.py
    models/schemas.py
    tools/qdrant_tools.py
    tools/neo4j_tools.py
```

## `.env` Values

Create `fingraphrag/.env` with the credentials and cloud endpoints you provide:

```env
# Gemini
GOOGLE_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.0-flash
EMBEDDING_MODEL=models/text-embedding-004
EMBEDDING_DIMENSIONS=768

# Qdrant Cloud
QDRANT_URL=https://your-cluster.cloud.qdrant.io
QDRANT_API_KEY=your_qdrant_api_key
QDRANT_COLLECTION=financial_documents

# Neo4j Aura or another reachable Neo4j instance
NEO4J_URI=neo4j+s://your-instance.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_neo4j_password
NEO4J_DATABASE=neo4j

# LangSmith
LANGCHAIN_API_KEY=your_langsmith_api_key
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=fin-graph-rag

# Optional tuning
MEMORY_WINDOW_SIZE=10
CHUNK_SIZE=1200
CHUNK_OVERLAP=150
```

Qdrant Cloud and Neo4j must be reachable from the machine running this project. The application does not create those hosted accounts or services.

## Install

From PowerShell:

```powershell
cd C:\Users\Os\Documents\PP\fingraphrag
..\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

For a new virtual environment instead:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

## Load Your CSV

Place the CSV anywhere accessible. The loader preserves every non-empty column as searchable text and stores the original filename and row number as metadata.

```powershell
python -m src.main ingest "C:\path\to\your\financial_data.csv"
```

Expected output:

```json
{
  "rows": 100,
  "qdrant_points": 100,
  "neo4j_nodes": 100
}
```

## Run the API

```powershell
python -m src.main serve
```

The API runs at `http://127.0.0.1:8000`. Interactive API documentation is at `http://127.0.0.1:8000/docs`.

## Run the Streamlit UI

```powershell
python -m src.main ui
```

The Streamlit UI will launch in your browser at `http://localhost:8501`. The UI provides:

- **Interactive Query Interface**: Submit financial queries and get AI-powered answers
- **Real-time System Health**: Monitor status of Gemini, Qdrant, Neo4j, and LangSmith
- **Conversation Management**: Multi-session support with memory management
- **Advanced Analytics**: Query trends, intent analysis, performance metrics
- **Visualization**: Interactive charts and graphs for query analysis
- **Source References**: View retrieved documents and graph results
- **Architecture Overview**: Visual representation of the system flow

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Query it from PowerShell:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/query `
  -ContentType "application/json" `
  -Body '{"query":"What is the revenue trend for the company?","session_id":"demo"}'
```

## Run One Query Without the API

```powershell
python -m src.main ask "Which companies are connected to the semiconductor industry?"
```

Clear one conversation session through the API:

```powershell
Invoke-RestMethod -Method Delete http://127.0.0.1:8000/memory/demo
```

## Notes

- The first ingestion creates the Qdrant collection with `EMBEDDING_DIMENSIONS`; keep that value aligned with the selected Gemini embedding model.
- Neo4j rows are stored as `FinancialEntity` nodes. Existing relationship modeling can be added once the CSV schema is known.
- Conversation memory is process-local and resets when the API process restarts.
- The response includes the retrieval plan, intent, and source payloads for provenance.
- Never place API keys in the CSV, source code, or `code.md`.
