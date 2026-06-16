"""Optional Postgres + pgvector source provider.

Grounds the pipeline in your own knowledge base instead of public feeds. Point
the ``WARDROBE_DB_*`` / ``WARDROBE_EMBED_*`` settings (see .env.example) at any
table that has a text payload and a pgvector embedding column, and this provider
retrieves the rows most similar to your query.

Heavy dependencies (the Cloud SQL connector, a Postgres driver, and an embedding
client) are imported lazily so the base install stays light. Install them only
if you use this provider:

    pip install "cloud-sql-python-connector[pg8000]" pgvector openai

The query embedding MUST use the same model the stored vectors were built with,
or similarity scores are meaningless.
"""

from __future__ import annotations

import logging

from .. import config
from .base import SourceItem

log = logging.getLogger("sources.vectordb")


class VectorDBSourceProvider:
    def fetch(self, limit: int = 40, brief: str | None = None) -> list[SourceItem]:
        if not config.WARDROBE_DB_CONNECTION_NAME or not config.WARDROBE_DB_NAME:
            log.warning("vectordb provider not configured (missing connection/name)")
            return []

        top_k = min(limit, config.WARDROBE_TOP_K)
        query_text = brief or f"{config.BRAND_DOMAIN}. Audience: {config.BRAND_AUDIENCE}."

        try:
            embedding = self._embed(query_text)
            rows = self._query_similar(embedding, top_k)
        except Exception:
            log.exception("vectordb retrieval failed")
            return []

        return [self._to_item(row) for row in rows]

    # -- embeddings -----------------------------------------------------
    def _embed(self, text: str) -> list[float]:
        provider = config.WARDROBE_EMBED_PROVIDER.lower()
        if provider == "openai":
            from openai import OpenAI

            client = OpenAI(api_key=config.OPENAI_API_KEY or None)
            resp = client.embeddings.create(
                model=config.WARDROBE_EMBED_MODEL, input=text
            )
            return resp.data[0].embedding
        raise ValueError(
            f"Unsupported WARDROBE_EMBED_PROVIDER: {config.WARDROBE_EMBED_PROVIDER!r}"
        )

    # -- database -------------------------------------------------------
    def _connect(self):
        from google.cloud.sql.connector import Connector, IPTypes

        ip_type = IPTypes.PRIVATE if config.WARDROBE_DB_PRIVATE_IP else IPTypes.PUBLIC
        connector = Connector()
        return connector.connect(
            config.WARDROBE_DB_CONNECTION_NAME,
            "pg8000",
            user=config.WARDROBE_DB_USER,
            password=config.WARDROBE_DB_PASSWORD or None,
            db=config.WARDROBE_DB_NAME,
            ip_type=ip_type,
            enable_iam_auth=config.WARDROBE_DB_USE_IAM,
        )

    def _query_similar(self, embedding: list[float], top_k: int) -> list[dict]:
        text_cols = config.WARDROBE_DB_TEXT_COLUMNS
        # Identifiers come from trusted config, not user input.
        select_cols = ", ".join(f'"{c}"' for c in text_cols)
        table = f'"{config.WARDROBE_DB_TABLE}"'
        embed_col = f'"{config.WARDROBE_DB_EMBED_COLUMN}"'
        vector_literal = "[" + ",".join(str(x) for x in embedding) + "]"

        sql = (
            f"SELECT {select_cols} FROM {table} "
            f"ORDER BY {embed_col} <=> %s LIMIT %s"
        )

        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(sql, (vector_literal, top_k))
            fetched = cursor.fetchall()
            cursor.close()
        finally:
            conn.close()

        return [dict(zip(text_cols, row)) for row in fetched]

    # -- mapping --------------------------------------------------------
    def _to_item(self, row: dict) -> SourceItem:
        cols = config.WARDROBE_DB_TEXT_COLUMNS
        title = str(row.get(cols[0], "")).strip() if cols else ""
        rest = [f"{k}: {row[k]}" for k in cols[1:] if row.get(k)]
        context = " | ".join(rest)[:300]
        return {
            "title": title or context[:80],
            "url": "",
            "context": context,
            "source": "vectordb",
        }
