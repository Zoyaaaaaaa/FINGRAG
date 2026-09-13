from pathlib import Path
from typing import Any

import pandas as pd

from src.config.settings import Settings
from src.tools.neo4j_tools import Neo4jClient
from src.tools.qdrant_tools import QdrantStore


def load_csv(
    path: str,
    settings: Settings,
    qdrant: QdrantStore,
    neo4j: Neo4jClient,
    *,
    skip_qdrant: bool = False,
    with_edges: bool = True,
) -> dict[str, int]:
    """Ingest one CSV.

    *skip_qdrant*: when True, does NOT embed/upsert to Qdrant — use for the
      one-shot edge migration so the existing 532-point (now deterministic)
      collection is not touched/duplicated.
    *with_edges*: when True, also MERGEs :Company nodes + typed relationships
      (PARTNERS_WITH / LICENSES_TECHNOLOGY_FROM / HAS_STAKE_IN ...). MERGE is
      idempotent so re-running adds 0 dupes.
    """
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")
    # stock_report.csv has a stray comma in one row — csv module handles it
    # better than pandas default; try pandas first, fall back to csv
    try:
        frame = pd.read_csv(csv_path, on_bad_lines='warn').fillna("")
        rows = frame.to_dict(orient="records")
    except Exception:
        import csv as _csv
        with csv_path.open(encoding="utf-8-sig") as f:
            rows = list(_csv.DictReader(f))
    documents: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        text = " | ".join(f"{key}: {value}" for key, value in row.items() if str(value).strip())
        documents.append({"text": text, "metadata": {"source": csv_path.name, "row": index}})
    if skip_qdrant:
        count = 0
    else:
        count = qdrant.upsert(documents)
    graph_count = neo4j.upsert_rows(rows, csv_path.name)
    edge_info: dict[str, int] = {}
    if with_edges:
        edge_info = neo4j.upsert_with_edges(rows, csv_path.name)
    return {
        "rows": len(rows),
        "qdrant_points": count,
        "neo4j_nodes": graph_count,
        "neo4j_rels": edge_info.get("rels", 0),
        "neo4j_companies": edge_info.get("nodes", 0),
    }
