import hashlib
from typing import Any
from uuid import uuid4, uuid5, NAMESPACE_URL
import time

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.http import models

from src.config.settings import Settings


class QdrantStore:
    def __init__(self, settings: Settings):
        self.settings = settings

        self.client = (
            QdrantClient(
                url=settings.qdrant_url,
                api_key=settings.qdrant_api_key or None,
                timeout=120,
            )
            if settings.qdrant_url
            else None
        )

        self.embeddings = (
            GoogleGenerativeAIEmbeddings(
                model=settings.embedding_model,
                google_api_key=settings.google_api_key,
            )
            if settings.google_api_key
            else None
        )
        self.last_error: str | None = None

    def health(self) -> str:
        if not self.client:
            self.last_error = "QDRANT_URL not set in src/.env"
            return "not_configured"

        try:
            self.client.get_collections()
            self.last_error = None
            return "ok"
        except Exception as exc:
            self.last_error = str(exc)
            return "error"

    def health_detail(self) -> dict[str, Any]:
        status = self.health()
        hint = ""
        if status == "error" and self.last_error:
            err = self.last_error.lower()
            if "getaddrinfo failed" in err or "name or service not known" in err or "nodename nor servname" in err:
                hint = "Qdrant Cloud hostname did not resolve: check internet/DNS/VPN, then use 'Retry connections'."
            elif "unauthorized" in err or "401" in err or "forbidden" in err or "403" in err:
                hint = "Bad QDRANT_API_KEY in src/.env (or key rotated/deleted in Qdrant Cloud console)."
            elif "not found" in err or "404" in err:
                hint = "Cluster URL wrong or cluster deleted — verify QDRANT_URL in Qdrant Cloud dashboard."
            elif "timeout" in err or "timed out" in err:
                hint = "Transient network timeout — use 'Retry connections'."
        try:
            collections = [c.name for c in self.client.get_collections().collections] if status == "ok" and self.client else []
        except Exception:
            collections = []
        return {
            "status": status,
            "url": self.settings.qdrant_url,
            "collection": self.settings.qdrant_collection,
            "collections": collections,
            "error": self.last_error,
            "hint": hint,
        }

    def ensure_collection(self) -> None:
        if not self.client:
            raise RuntimeError("QDRANT_URL is not configured")

        names = {
            item.name
            for item in self.client.get_collections().collections
        }

        if self.settings.qdrant_collection not in names:
            self.client.create_collection(
                collection_name=self.settings.qdrant_collection,
                vectors_config=models.VectorParams(
                    size=self.settings.embedding_dimensions,
                    distance=models.Distance.COSINE,
                ),
            )

    def _embed_batch(
        self,
        texts: list[str],
        max_retries: int = 5,
    ) -> list[list[float]]:

        for attempt in range(max_retries):
            try:
                return self.embeddings.embed_documents(texts)

            except Exception as e:
                error_text = str(e)

                if (
                    "429" not in error_text
                    and "RESOURCE_EXHAUSTED" not in error_text
                ):
                    raise

                wait_time = 35 * (attempt + 1)

                print(
                    f"Gemini embedding quota reached. "
                    f"Waiting {wait_time}s before retry "
                    f"({attempt + 1}/{max_retries})..."
                )

                time.sleep(wait_time)

        raise RuntimeError(
            "Gemini embedding quota is still exhausted after retries."
        )

    def upsert(
        self,
        documents: list[dict[str, Any]],
        batch_size: int = 5,
    ) -> int:

        if not self.client or not self.embeddings:
            raise RuntimeError(
                "QDRANT_URL and GOOGLE_API_KEY are required for ingestion"
            )

        self.ensure_collection()

        total = len(documents)

        if total == 0:
            return 0

        total_inserted = 0

        for start in range(0, total, batch_size):
            batch = documents[start:start + batch_size]

            print(
                f"Embedding documents "
                f"{start + 1}-{min(start + batch_size, total)} "
                f"of {total}..."
            )

            texts = [item["text"] for item in batch]

            vectors = self._embed_batch(texts)

            points = [
                models.PointStruct(
                    # Deterministic ID so re-ingesting the same CSV row does NOT
                    # create a duplicate point (old code used uuid4 → 532 points
                    # for 320 rows). uuid5 is stable per text+source+row.
                    id=str(uuid5(
                        NAMESPACE_URL,
                        hashlib.sha256(
                            f"{item['text']}|{item.get('metadata',{}).get('source','')}|{item.get('metadata',{}).get('row','')}".encode()
                        ).hexdigest()
                    )),
                    vector=vector,
                    payload={
                        "text": item["text"],
                        "metadata": item.get("metadata", {}),
                    },
                )
                for item, vector in zip(batch, vectors)
            ]

            self.client.upsert(
                collection_name=self.settings.qdrant_collection,
                points=points,
            )

            total_inserted += len(points)

            print(
                f"Inserted {total_inserted}/{total} documents into Qdrant."
            )

            # Small pause between batches to avoid hammering the API.
            if start + batch_size < total:
                time.sleep(2)

        return total_inserted

    def search(
        self,
        query: str,
        limit: int = 8,
    ) -> list[dict[str, Any]]:

        if not self.client or not self.embeddings:
            return []

        self.ensure_collection()

        vector = self.embeddings.embed_query(query)

        result = self.client.query_points(
            collection_name=self.settings.qdrant_collection,
            query=vector,
            limit=limit,
            with_payload=True,
        )

        return [
            {
                "text": point.payload.get("text", ""),
                "score": point.score,
                "metadata": point.payload.get("metadata", {}),
            }
            for point in result.points
        ]