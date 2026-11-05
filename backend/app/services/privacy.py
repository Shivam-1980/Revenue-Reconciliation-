"""Mask personal identifiers already stored in database rows (V62.6.214); idempotent, runs once per database."""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import and_, bindparam, select, tuple_, update

from app import crypto_store, database, db_compat
from app.db_schema import recon_result_rows, src_commission_rows, src_generic_rows, src_transaction_rows

log = logging.getLogger("eko.privacy")
TARGETS = ((src_transaction_rows, "extra"), (src_commission_rows, "extra"), (src_generic_rows, "data"), (recon_result_rows, "data"))
CHUNK = 5000


def marker_path() -> Path:
    return Path(db_compat.DB_PATH).with_name("pii_masked_v1.txt")


def mask_existing_rows(force: bool = False) -> dict:
    if marker_path().exists() and not force:
        return {}
    engine = database.get_engine()
    changed = {}
    for table, column in TARGETS:
        pk = list(table.primary_key.columns)
        done, last = 0, None
        while True:
            q = select(*pk, table.c[column]).order_by(*pk).limit(CHUNK)
            if last is not None:
                q = q.where(tuple_(*pk) > tuple_(*last))
            with engine.connect() as conn:
                rows = conn.execute(q).all()
                if not rows:
                    break
                updates = []
                for row in rows:
                    data = row[-1]
                    if isinstance(data, dict):
                        masked = crypto_store.mask_record(data)
                        if masked != data:
                            updates.append({**{f"p_{c.name}": row[i] for i, c in enumerate(pk)}, "v": masked})
                if updates:
                    conn.execute(update(table).where(and_(*[c == bindparam(f"p_{c.name}") for c in pk])).values({column: bindparam("v")}), updates)
                    conn.commit()
                    done += len(updates)
            last = tuple(rows[-1][: len(pk)])
        changed[table.name] = done
    marker_path().write_text(f"Personal identifiers masked in existing rows: {changed}\n", encoding="utf-8")
    log.warning("Masked personal identifiers in existing rows: %s", changed)
    return changed
