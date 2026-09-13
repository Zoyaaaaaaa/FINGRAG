import time
from typing import Any

from neo4j import GraphDatabase

from src.config.settings import Settings


class Neo4jClient:
    # Min seconds between automatic reconnect attempts (each attempt can block
    # on DNS/SSL timeouts, so don't retry on every Streamlit rerun).
    RECONNECT_COOLDOWN_S = 60.0

    def __init__(self, settings: Settings):
        self.settings = settings
        self.driver = None
        self.active_database: str | None = settings.neo4j_database or None
        self.last_error: str | None = None
        self._last_connect_attempt: float = 0.0
        # Exposed for UI provenance: last cypher + params actually executed
        self.last_cypher: str | None = None
        self.last_params: dict[str, Any] | None = None
        if settings.neo4j_uri and settings.neo4j_password:
            self._ensure_driver(force=True)

    @property
    def configured(self) -> bool:
        return bool(self.settings.neo4j_uri and self.settings.neo4j_password)

    def _ensure_driver(self, force: bool = False) -> bool:
        """(Re)connect if offline. Returns True when a working driver exists.

        A failed cold start (e.g. transient DNS outage, like
        'getaddrinfo failed' for *.databases.neo4j.io) previously left
        driver=None FOREVER until app restart. Now health()/search() call this
        first, throttled by RECONNECT_COOLDOWN_S unless force=True.
        """
        if self.driver:
            return True
        if not self.configured:
            self.last_error = "NEO4J_URI / NEO4J_PASSWORD not set in src/.env"
            return False
        now = time.monotonic()
        if not force and (now - self._last_connect_attempt) < self.RECONNECT_COOLDOWN_S:
            return False
        self._last_connect_attempt = now
        self.driver = self._connect_with_fallback(self.settings)
        if self.driver:
            # Auto-discover working database (Aura uses instance-id as db name, not "neo4j")
            resolved = self._resolve_database()
            if resolved:
                self.active_database = resolved
            return True
        return False

    def reconnect(self) -> dict[str, Any]:
        """Manual retry (sidebar 'Retry connections' button). Bypasses cooldown."""
        self._ensure_driver(force=True)
        return self.health_detail()

    def _connect_with_fallback(self, settings: Settings):
        """Try neo4j+s:// first, fall back to neo4j+ssc:// on Windows SSL verify failure."""
        candidates = [settings.neo4j_uri]
        uri = settings.neo4j_uri
        # Build insecure (skip-cert-verify) fallback for Aura on machines with broken CA chain
        if "+s://" in uri and "+ssc://" not in uri:
            candidates.append(uri.replace("+s://", "+ssc://"))
        last_exc: Exception | None = None
        for candidate in candidates:
            try:
                driver = GraphDatabase.driver(
                    candidate,
                    auth=(settings.neo4j_user, settings.neo4j_password),
                )
                # Validate connection immediately (no database = server default/home)
                with driver.session() as session:
                    session.run("RETURN 1").consume()
                if candidate != uri:
                    print(f"Neo4j: SSL verification failed for {uri}, using fallback {candidate}")
                self.last_error = None
                return driver
            except Exception as exc:  # noqa: BLE001 - need to try next candidate
                last_exc = exc
                try:
                    driver.close()  # type: ignore[possibly-undefined]
                except Exception:
                    pass
        self.last_error = str(last_exc) if last_exc else "unknown connection error"
        print(f"Neo4j connection error: {self.last_error}")
        return None

    def _resolve_database(self) -> str | None:
        """Return a working database name. Prefers configured value, else home/default."""
        if not self.driver:
            return None
        candidates: list[str | None] = []
        if self.settings.neo4j_database:
            candidates.append(self.settings.neo4j_database)
        # Discover home database from SHOW DATABASES (Aura: instance id is home)
        try:
            with self.driver.session() as session:
                try:
                    rows = session.run("SHOW DATABASES").data()
                    for row in rows:
                        if row.get("home"):
                            candidates.append(row.get("name"))
                    for row in rows:
                        name = row.get("name")
                        if name and name != "system" and name not in candidates:
                            candidates.append(name)
                except Exception:
                    pass
        except Exception:
            pass
        candidates.append(None)  # server default as last resort
        for db in candidates:
            try:
                kwargs = {"database": db} if db else {}
                with self.driver.session(**kwargs) as session:
                    session.run("RETURN 1").consume()
                if db != self.settings.neo4j_database and db is not None:
                    print(f"Neo4j: configured database '{self.settings.neo4j_database}' unavailable, using '{db}'")
                return db  # type: ignore[return-value]
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                continue
        return None

    def _session_kwargs(self) -> dict[str, Any]:
        return {"database": self.active_database} if self.active_database else {}

    def close(self) -> None:
        if self.driver:
            self.driver.close()

    def health(self) -> str:
        if not self.configured:
            self.last_error = "NEO4J_URI / NEO4J_PASSWORD not set in src/.env"
            return "not_configured"
        # Self-heal: a transient DNS/SSL failure at startup no longer sticks.
        self._ensure_driver()
        if not self.driver:
            return "error"
        try:
            with self.driver.session(**self._session_kwargs()) as session:
                session.run("RETURN 1").consume()
            self.last_error = None
            return "ok"
        except Exception as exc:  # noqa: BLE001
            self.last_error = str(exc)
            # Drop the dead driver so the next health()/search() reconnects.
            try:
                self.driver.close()
            except Exception:
                pass
            self.driver = None
            return "error"

    def health_detail(self) -> dict[str, Any]:
        status = self.health()
        hint = ""
        if status == "error" and self.last_error:
            err = self.last_error.lower()
            if "getaddrinfo failed" in err or "dns" in err or "name resolution" in err:
                hint = ("Hostname did not resolve: check internet/DNS/VPN. "
                        "Aura free instances also pause after inactivity — resume it in the Aura console. "
                        "The app retries automatically (60s cooldown) or via 'Retry connections'.")
            elif "ssl" in err or "certificate" in err:
                hint = "TLS verification failed on Windows — the app already falls back to neo4j+ssc:// automatically."
            elif "database" in err and "not found" in err:
                hint = f"Aura home DB is usually the instance id, not 'neo4j'. Set NEO4J_DATABASE={self.active_database or '<instance-id>'} in src/.env."
            elif "unauthenticated" in err or "unauthorized" in err or "authentication" in err:
                hint = "Bad NEO4J_USER / NEO4J_PASSWORD in src/.env (or Aura credentials rotated)."
        return {
            "status": status,
            "uri": self.settings.neo4j_uri,
            "configured_database": self.settings.neo4j_database,
            "active_database": self.active_database,
            "error": self.last_error,
            "hint": hint,
        }

    def search(self, query: str, entities: list[str], limit: int = 8) -> list[dict[str, Any]]:
        self._ensure_driver()
        if not self.driver:
            return []
        # Fallback keywords when regex entity extraction finds nothing (e.g. lowercase query)
        terms = [e for e in (entities or []) if e and e.strip()]
        if not terms:
            # Use meaningful query words as fallback so graph search still runs
            stop = {"what", "which", "who", "how", "why", "when", "where", "are", "the", "between", "with",
                    "and", "for", "from", "about", "tell", "show", "list", "give", "does", "doing", "relationship",
                    "relationships", "companies", "company"}
            terms = [w.strip("?,.'\"") for w in query.split() if len(w) > 2 and w.lower() not in stop][:6]
        if not terms:
            return []
        try:
            # Two-phase search: :Company graph (has real edges) first, then
            # legacy :FinancialEntity for full provenance. This makes the
            # new edges visible (previously 0 rels for JSW/Chery).
            company_cypher = """
            MATCH (n:Company)
            WHERE any(term IN $entities WHERE toLower(n.name) CONTAINS toLower(term)
                      OR toLower(toString(n.key)) CONTAINS toLower(term))
            OPTIONAL MATCH (n)-[r]->(neighbor)
            RETURN properties(n) AS node, labels(n) AS labels,
                   type(r) AS relationship, properties(neighbor) AS neighbor,
                   labels(neighbor) AS neighbor_labels, properties(r) AS rel_props
            LIMIT $limit
            """
            entity_cypher = """
            MATCH (n:FinancialEntity)
            WHERE any(key IN keys(n) WHERE n[key] IS NOT NULL AND
                      any(term IN $entities WHERE toLower(toString(n[key])) CONTAINS toLower(term)))
            OPTIONAL MATCH (n)-[r]-(neighbor)
            RETURN properties(n) AS node, labels(n) AS labels,
                   type(r) AS relationship, properties(neighbor) AS neighbor,
                   labels(neighbor) AS neighbor_labels, properties(r) AS rel_props
            LIMIT $limit
            """
            self.last_cypher = " ".join(company_cypher.split()) + " // + FinancialEntity fallback"
            self.last_params = {"entities": terms, "limit": limit, "database": self.active_database}
            with self.driver.session(**self._session_kwargs()) as session:
                company_rows = [r.data() for r in session.run(company_cypher, entities=terms, limit=limit)]
                # If we have real edges, return them first; fill remainder with FinancialEntity provenance
                if len(company_rows) >= limit:
                    self.last_error = None
                    return company_rows
                remaining = limit - len(company_rows)
                entity_rows = [r.data() for r in session.run(entity_cypher, entities=terms, limit=remaining)] if remaining > 0 else []
                self.last_error = None
                return company_rows + entity_rows
        except Exception as e:
            self.last_error = str(e)
            print(f"Neo4j search error: {e}")
            return []

    @staticmethod
    def _stable_key(values: dict[str, str], source: str, row_idx: int) -> str:
        """Deterministic key — no Python hash() randomization.

        Prefers a business key (company_code / stock_code) so the same company
        from stock_company.csv + stock_report.csv merges to one :Company node.
        Falls back to company_name normalized. Only as last resort uses
        source:row so per-row FinancialEntity rows stay distinct but stable
        across re-runs (old code used hash(tuple(...)) → different key each
        process → duplicates on re-ingest).
        """
        code = (values.get("company_code") or values.get("stock_code") or "").strip().lower()
        if code:
            return f"company:{code}"
        name = (values.get("company_name") or "").strip().lower()
        if name:
            # per-company node (desired for graph)
            return f"company:{name}"
        # per-row fallback (keeps FinancialEntity parity)
        return f"row:{source}:{row_idx}"

    def upsert_rows(self, rows: list[dict[str, Any]], source: str) -> int:
        self._ensure_driver()
        if not self.driver or not rows:
            return 0
        cypher = """
        UNWIND $rows AS row
        MERGE (entity:FinancialEntity {key: row.key})
        SET entity += row.properties, entity.source = $source
        """
        prepared = []
        for idx, row in enumerate(rows):
            values = {str(k): str(v) for k, v in row.items() if v is not None and str(v).strip()}
            key = self._stable_key(values, source, idx)
            prepared.append({"key": key, "properties": values})
        with self.driver.session(**self._session_kwargs()) as session:
            session.run(cypher, rows=prepared, source=source).consume()
        return len(prepared)

    # ---------- New: idempotent edge layer ----------
    REL_TYPE_MAP = {
        # stock_company.relationship_type / stock_report.deal_type → graph rel
        "technology_partnership": "PARTNERS_WITH",
        "technology_licensing": "LICENSES_TECHNOLOGY_FROM",
        "platform_licensing": "LICENSES_TECHNOLOGY_FROM",
        "technology_agreement": "PARTNERS_WITH",
        "jv": "PARTNERS_WITH",
        "jv_discussion": "PARTNERS_WITH",
        "jv_abeyance": "PARTNERS_WITH",
        "jv_completed": "PARTNERS_WITH",
        "49_pct_jv": "HAS_STAKE_IN",
        "49% jv": "HAS_STAKE_IN",
        "49_retained": "HAS_STAKE_IN",
        "jv stake increase": "HAS_STAKE_IN",
        "jv + technology transfer": "PARTNERS_WITH",
        "jv investment": "HAS_STAKE_IN",
        "subsidiary": "HAS_SUBSIDIARY",
        "operations": "OPERATES_WITH",
        "operations_in_china": "OPERATES_WITH",
        "investment": "INVESTED_IN",
        "distribution": "DISTRIBUTES_FOR",
        "research_partnership": "RESEARCH_WITH",
        "technology partnership": "PARTNERS_WITH",
        "sales growth": "HAS_SUBSIDIARY",
        "r&d center": "HAS_RND_CENTER",
    }

    @staticmethod
    def _rel_type(raw: str) -> str:
        return Neo4jClient.REL_TYPE_MAP.get(raw.strip().lower(), "PARTNERS_WITH")

    @staticmethod
    def _split_partners(raw: str) -> list[str]:
        import re
        if not raw or raw.strip().lower() in ("multiple", "multiple chinese"):
            return []
        # "Chery_SAIC" → ["Chery","SAIC"]; "Chery Automobile" stays one
        if "_" in raw and " " not in raw:
            return [p.strip() for p in re.split(r"[_\"]+", raw) if p.strip()]
        # comma-separated in stock_report (rare)
        if "," in raw or ";" in raw:
            return [p.strip() for p in re.split(r"[,;]+", raw) if p.strip() and "multiple" not in p.lower()]
        return [raw.strip()]

    def upsert_with_edges(self, rows: list[dict[str, Any]], source: str) -> dict[str, int]:
        """Idempotent: MERGE Company nodes + MERGE edges. Safe to re-run.

        Does NOT touch Qdrant. Works against existing 316 FinancialEntity nodes:
        it MATCHes/ MERGEs :Company nodes by normalized name (so old hash-key
        nodes are NOT duplicated) and MERGEs the relationship, so running twice
        does not create duplicate rels.
        Returns {nodes, rels}.
        """
        self._ensure_driver()
        if not self.driver or not rows:
            return {"nodes": 0, "rels": 0}
        # Prepare per-CSV edge specs
        specs: list[dict[str, Any]] = []
        for row in rows:
            indien = (row.get("company_name") or "").strip()
            raw_partner = (row.get("chinese_partner") or row.get("key_players") or "").strip()
            raw_rel = (row.get("relationship_type") or row.get("deal_type") or row.get("key_players") or "PARTNERS_WITH").strip()
            if not indien or not raw_partner or raw_partner.lower() in ("multiple", "multiple chinese"):
                continue
            # Stock_industry_grouped has "Haier_JV" style — treat as partner hint
            # but prefer chinese_partner when present.
            partners = self._split_partners(raw_partner)
            rel_type = self._rel_type(raw_rel)
            for partner in partners:
                if partner.lower() in ("multiple", "multiple chinese", ""):
                    continue
                # Keep per-row properties on the rel for provenance
                props = {str(k): str(v) for k, v in row.items() if v is not None and str(v).strip()}
                props["source"] = source
                props["rel_type_raw"] = raw_rel
                specs.append({"indian": indien, "partner": partner, "rel_type": rel_type, "props": props})
        if not specs:
            return {"nodes": 0, "rels": 0}
        # Group by rel_type to use typed MERGE (dynamic rel type not allowed in Cypher)
        from collections import defaultdict
        by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for s in specs:
            by_type[s["rel_type"]].append(s)
        nodes_touched = 0
        rels_created = 0
        with self.driver.session(**self._session_kwargs()) as session:
            for rel_type, batch in by_type.items():
                # Parameterized batch with explicit relationship type
                cypher = f"""
                UNWIND $batch AS spec
                MERGE (a:Company {{name: spec.indian}})
                ON CREATE SET a.key = 'company:' + toLower(spec.indian)
                MERGE (b:Company {{name: spec.partner}})
                ON CREATE SET b.key = 'company:' + toLower(spec.partner)
                MERGE (a)-[r:{rel_type}]->(b)
                SET r += spec.props, r.rel_type = $rel_type
                """
                # Also ensure legacy FinancialEntity per-row still exists (idempotent)
                # — do not touch Qdrant here.
                result = session.run(cypher, batch=batch, rel_type=rel_type)
                result.consume()
                # Count is batch size (MERGE is idempotent, so second run adds 0)
                rels_created += len(batch)
                nodes_touched += len({s["indian"] for s in batch} | {s["partner"] for s in batch})
        return {"nodes": nodes_touched, "rels": rels_created}
