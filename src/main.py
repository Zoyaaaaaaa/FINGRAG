import argparse
import json
import subprocess
import sys

from src.config.settings import get_settings
from src.ingestion import load_csv
from src.orchestrator import FinGraphRAG


def main() -> None:
    parser = argparse.ArgumentParser(description="FinGraphRAG")
    subparsers = parser.add_subparsers(dest="command", required=True)
    serve = subparsers.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    ingest = subparsers.add_parser("ingest")
    ingest.add_argument("csv")
    ask = subparsers.add_parser("ask")
    ask.add_argument("query")
    ask.add_argument("--session-id", default="default")
    ui = subparsers.add_parser("ui")
    args = parser.parse_args()
    settings = get_settings()

    if args.command == "serve":
        import uvicorn
        uvicorn.run("src.api:app", host=args.host, port=args.port, reload=False)
        return

    if args.command == "ui":
        subprocess.run([sys.executable, "-m", "streamlit", "run", "src/streamlit_app.py"])
        return

    system = FinGraphRAG(settings)
    if args.command == "ingest":
        print(json.dumps(load_csv(args.csv, settings, system.qdrant, system.neo4j), indent=2))
    else:
        print(json.dumps(system.query(args.query, args.session_id), indent=2, default=str))


if __name__ == "__main__":
    main()
