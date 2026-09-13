"""One-shot migration: add :Company + relationship edges to Neo4j without touching Qdrant.

Run once:  python scripts/add_edges.py
Re-running is safe (MERGE is idempotent) — second run creates 0 new nodes/rels
and Qdrant is never touched (skip_qdrant=True).

Prints before/after counts so you can verify no duplication.
"""
import sys
from pathlib import Path

# allow `python scripts/add_edges.py` from project root or anywhere
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config.settings import get_settings
from src.ingestion import load_csv
from src.tools.neo4j_tools import Neo4jClient
from src.tools.qdrant_tools import QdrantStore


def main():
    settings = get_settings()
    qdrant = QdrantStore(settings)
    neo4j = Neo4jClient(settings)

    # Before
    with neo4j.driver.session(database=neo4j.active_database) as s:
        nodes_before = s.run("MATCH (n) RETURN count(n) AS c").data()[0]["c"]
        rels_before = s.run("MATCH ()-[r]->() RETURN count(r) AS c").data()[0]["c"]
        q_before = qdrant.client.count(collection_name=settings.qdrant_collection, exact=False).count if qdrant.client else 0
    print(f"Before: neo4j nodes={nodes_before} rels={rels_before} | qdrant points={q_before}")

    csvs = [
        "src/data/stock_company.csv",
        "src/data/stock_report.csv",
        # Stock_industry_grouped is industry-level, not company×partner edges — skip for now
        # add it with a separate :OPERATES_IN edge type if you want later
    ]
    total_rels = 0
    for csv in csvs:
        res = load_csv(csv, settings, qdrant, neo4j, skip_qdrant=True, with_edges=True)
        print(f"  {csv}: rows={res['rows']} neo4j_nodes={res['neo4j_nodes']} companies_touched={res['neo4j_companies']} rels={res['neo4j_rels']} (qdrant skipped)")
        total_rels += res["neo4j_rels"]

    with neo4j.driver.session(database=neo4j.active_database) as s:
        nodes_after = s.run("MATCH (n) RETURN count(n) AS c").data()[0]["c"]
        rels_after = s.run("MATCH ()-[r]->() RETURN count(r) AS c").data()[0]["c"]
        q_after = qdrant.client.count(collection_name=settings.qdrant_collection, exact=False).count if qdrant.client else 0
        by_type = s.run("MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c ORDER BY c DESC").data()
        sample = s.run("MATCH (a)-[r]->(b) RETURN a.name AS a, type(r) AS t, b.name AS b LIMIT 8").data()
    print(f"After: neo4j nodes={nodes_after} rels={rels_after} | qdrant points={q_after} (must equal before)")
    print(f"Rels by type: {by_type}")
    print(f"Sample edges: {sample}")
    print("\nVerify no Qdrant duplication: q_after == q_before ->", q_after == q_before)
    print("Re-running this script again should report rels= same but nodes/rels counts unchanged (MERGE).")


if __name__ == "__main__":
    main()
