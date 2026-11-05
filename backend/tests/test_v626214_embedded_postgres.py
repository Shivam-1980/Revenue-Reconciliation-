"""Built-in PostgreSQL: password-only access, persistence, and one-time SQLite -> PostgreSQL migration."""
import socket
import sqlite3

import pytest

pgserver = pytest.importorskip("pgserver")
import psycopg  # noqa: E402
from sqlalchemy import create_engine, func, insert, select, text  # noqa: E402

from app import database, db_compat, embedded_pg, secret_store  # noqa: E402
from app.db_schema import audit_events, metadata, period_workspaces, recon_runs, src_uploads, users  # noqa: E402
from app.services import sqlite_migration  # noqa: E402


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def pg(tmp_path_factory):
    base = tmp_path_factory.mktemp("embedded_pg")
    mp = pytest.MonkeyPatch()
    mp.setattr(embedded_pg, "PGDATA", base / "pgdata")
    mp.setattr(embedded_pg, "PORT", _free_port())
    mp.setattr(secret_store, "SECRETS_PATH", base / "secrets.json")
    url = embedded_pg.ensure_running()
    yield url
    embedded_pg.stop()
    mp.undo()


def test_login_needs_the_generated_password_and_listens_on_localhost_only(pg):
    with psycopg.connect(pg) as conn:
        assert conn.execute("select current_user").fetchone()[0] == "eko_app"
        assert conn.execute("show listen_addresses").fetchone()[0] == "127.0.0.1"
        assert conn.execute("show password_encryption").fetchone()[0] == "scram-sha-256"
    nopass = pg.replace(pg.split("//")[1].split("@")[0], "eko_app")
    wrong = pg.replace(pg.split("//")[1].split("@")[0], "eko_app:not-the-password")
    for bad in (nopass, wrong):
        with pytest.raises(psycopg.OperationalError):
            psycopg.connect(bad, connect_timeout=5)


def test_another_folders_leftover_database_on_the_port_is_stopped_cleanly(tmp_path, monkeypatch):
    # V62.6.215: a second copy of the app found the fixed port held by the first copy's database (backend already
    # closed) and failed with "could not create any TCP/IP sockets". It now shuts that database down and starts its own.
    monkeypatch.setattr(secret_store, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(embedded_pg, "PORT", _free_port())
    first, second = tmp_path / "first" / "pgdata", tmp_path / "second" / "pgdata"
    monkeypatch.setattr(embedded_pg, "PGDATA", first)
    with psycopg.connect(embedded_pg.ensure_running(), autocommit=True) as conn:
        conn.execute("create table kept(v text); insert into kept values ('first')")
    monkeypatch.setattr(embedded_pg, "PGDATA", second)
    try:
        assert embedded_pg.ensure_running()
        assert embedded_pg._port_owner()[1] and embedded_pg.Path(embedded_pg._port_owner()[1]).resolve() == second.resolve()
    finally:
        embedded_pg.stop()
    monkeypatch.setattr(embedded_pg, "PGDATA", first)                       # the first folder's data is intact
    with psycopg.connect(embedded_pg.ensure_running()) as conn:
        assert conn.execute("select v from kept").fetchone()[0] == "first"
    embedded_pg.stop()


def test_a_port_held_by_another_program_gives_a_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(secret_store, "SECRETS_PATH", tmp_path / "secrets.json")
    monkeypatch.setattr(embedded_pg, "PGDATA", tmp_path / "pgdata")
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0)); blocker.listen()
        monkeypatch.setattr(embedded_pg, "PORT", blocker.getsockname()[1])
        with pytest.raises(embedded_pg.EmbeddedPostgresError, match="used by another program"):
            embedded_pg.ensure_running()


def test_data_survives_a_stop_and_start_and_the_url_is_stable(pg):
    with psycopg.connect(pg, autocommit=True) as conn:
        conn.execute("create table if not exists persist_check(v text)")
        conn.execute("insert into persist_check values ('kept')")
    embedded_pg.stop()
    assert not embedded_pg.is_running()
    assert embedded_pg.ensure_running() == pg
    with psycopg.connect(pg) as conn:
        assert conn.execute("select v from persist_check").fetchone()[0] == "kept"


@pytest.fixture
def engines(pg, tmp_path, monkeypatch):
    for engine in list(database._engines.values()):
        engine.dispose()
    database._engines.clear()
    sqlite_file = tmp_path / "platform.sqlite3"
    monkeypatch.setattr(db_compat, "DB_PATH", sqlite_file)
    monkeypatch.setattr(db_compat, "DATABASE_URL", pg)
    monkeypatch.setattr(db_compat, "USE_POSTGRES", True)
    with psycopg.connect(pg, autocommit=True) as conn:                 # empty target before each test
        conn.execute("drop schema public cascade; create schema public")
    database.init_schema()                                              # no sqlite file yet: nothing to migrate
    src = create_engine(f"sqlite:///{sqlite_file.as_posix()}")
    metadata.create_all(src)
    yield src, database.get_engine()
    database._engines.clear()


def _seed_sqlite(src):
    with src.begin() as c:
        c.execute(insert(users), [{"id": "u1", "email": "admin@eko.test", "password_hash": "x", "role": "super_admin", "organization_id": None, "active": 1, "created_at": 1}])
        c.execute(insert(audit_events), [{"id": i, "actor_user_id": "u1", "organization_id": None, "event_type": "e", "detail_json": "{}", "created_at": i} for i in (1, 2, 40)])
        c.execute(insert(src_uploads), [{"id": "up1", "kind": "transactions", "filename": "Success Aug.xlsx", "sha256": "a" * 64, "row_count": 3, "source_file": "t.csv",
                                         "synced_at": 5, "is_current": True, "meta": {"columns": ["a", "b"]}}])
        c.execute(insert(recon_runs), [{"run_id": "REC-1", "synced_at": 6, "is_current": True, "settlement_ready": False, "summary": {"k": [1, 2.5, None]}}])
        c.execute(insert(period_workspaces), [{"period_key": "2026-08", "period_label": "August 2026", "saved_at": 7, "archive": b"\x00\x01PK\xff" * 1000,
                                               "archive_sha256": "b" * 64, "size_bytes": 5000, "manifest": {"files": []}}])


def test_sqlite_data_is_copied_with_types_sequences_and_a_marker(engines):
    src, target = engines
    _seed_sqlite(src)
    copied = sqlite_migration.migrate_if_needed()
    assert copied["users"] == 1 and copied["audit_events"] == 3 and copied["period_workspaces"] == 1
    with target.begin() as c:
        assert c.execute(select(users.c.email)).scalar() == "admin@eko.test"
        up = c.execute(select(src_uploads)).mappings().one()
        assert up["meta"] == {"columns": ["a", "b"]} and up["is_current"] is True
        assert c.execute(select(recon_runs.c.summary)).scalar() == {"k": [1, 2.5, None]}
        assert bytes(c.execute(select(period_workspaces.c.archive)).scalar()) == b"\x00\x01PK\xff" * 1000
        new_id = c.execute(insert(audit_events).values(event_type="after", detail_json="{}", created_at=99).returning(audit_events.c.id)).scalar()
        assert new_id > 40                                              # serial continues after the copied ids
    assert sqlite_migration.marker_path().exists()
    assert sqlite_migration.migrate_if_needed() is None                 # runs once
    sqlite3.connect(db_compat.DB_PATH).execute("select 1 from users").fetchone()   # source file untouched


def test_existing_postgres_accounts_are_never_overwritten(engines):
    src, target = engines
    _seed_sqlite(src)
    with target.begin() as c:
        c.execute(insert(users).values(id="pg-user", email="already@here.test", password_hash="y", role="viewer", active=1, created_at=2))
    assert sqlite_migration.migrate_if_needed() is None
    with target.begin() as c:
        assert [r[0] for r in c.execute(select(users.c.email))] == ["already@here.test"]
        assert c.execute(select(func.count()).select_from(src_uploads)).scalar() == 0


def test_saved_month_is_stored_encrypted_and_old_plain_months_are_converted(engines, tmp_path, monkeypatch):
    import json
    from app import crypto_store
    from app.services import period_store
    src, target = engines
    data = tmp_path / "data"
    for rel, text_ in {"transactions/latest_transactions.csv": "transaction_id,csp_id\nT1,1A850001\n", "commissions/latest_commission.csv": "csp_id\n1A850001\n"}.items():
        (data / rel).parent.mkdir(parents=True, exist_ok=True); (data / rel).write_text(text_, encoding="utf-8")
    (data / "upload_metadata.json").write_text(json.dumps({"transactions": {"filename": "a.xlsx"}}), encoding="utf-8")
    monkeypatch.setattr(period_store, "DATA", data)
    period_store.save_period("2026-08", "August 2026", "tester")
    with target.begin() as c:
        stored = bytes(c.execute(select(period_workspaces.c.archive)).scalar())
    assert stored.startswith(b"EKOENC1") and b"1A850001" not in stored and b"PK\x03\x04" not in stored[:20]
    for f in list((data / "transactions").glob("*")) + list((data / "commissions").glob("*")): f.unlink()
    period_store.restore_period("2026-08")
    assert "T1,1A850001" in (data / "transactions/latest_transactions.csv").read_text(encoding="utf-8")
    # a month saved by an older version (plain zip) is encrypted in place and still restores
    plain_zip = crypto_store.decrypt_bytes(stored)
    import hashlib
    with target.begin() as c:
        c.execute(period_workspaces.update().values(archive=plain_zip, archive_sha256=hashlib.sha256(plain_zip).hexdigest()))
    assert period_store.encrypt_legacy_archives() == 1 and period_store.encrypt_legacy_archives() == 0
    period_store.restore_period("2026-08")


def test_existing_rows_get_personal_identifiers_masked_once(engines):
    from app.db_schema import src_transaction_rows
    from app.services import privacy
    src, target = engines
    with target.begin() as c:
        c.execute(insert(src_uploads).values(id="u", kind="transactions", sha256="c" * 64, row_count=2, source_file="t", synced_at=1, is_current=True))
        c.execute(insert(src_transaction_rows), [
            {"upload_id": "u", "row_no": 1, "csp_id": "1A850001", "extra": {"from_account": "123456789012", "to_account": "", "status": "SUCCESS"}},
            {"upload_id": "u", "row_no": 2, "csp_id": "1A850002", "extra": {"from_account": "****9012", "customer_mobile": "9876543210"}}])
    privacy.marker_path().unlink(missing_ok=True)
    changed = privacy.mask_existing_rows()
    assert changed["src_transaction_rows"] == 2
    with target.begin() as c:
        rows = {r.row_no: r.extra for r in c.execute(select(src_transaction_rows))}
    assert rows[1] == {"from_account": "****9012", "to_account": None, "status": "SUCCESS"}
    assert rows[2]["customer_mobile"] == "****3210" and rows[2]["from_account"] == "****9012"
    assert privacy.mask_existing_rows() == {}                        # marker: not repeated


# ---------------------------------------------------------------- backup / restore
def _fill_everything(target):
    from decimal import Decimal
    from app.db_schema import recon_result_rows
    with target.begin() as c:
        c.execute(insert(users), [{"id": "u1", "email": "admin@eko.test", "password_hash": "h", "role": "super_admin", "active": 1, "created_at": 1}])
        c.execute(insert(audit_events), [{"id": i, "event_type": "e", "detail_json": "{}", "created_at": i} for i in (1, 2, 30)])
        c.execute(insert(src_uploads).values(id="up", kind="commission", sha256="d" * 64, row_count=1, source_file="c", synced_at=1, is_current=True, meta={"a": [1, {"b": None}]}))
        c.execute(insert(recon_runs).values(run_id="R1", synced_at=2, is_current=True, expected_commission=Decimal("1140884.6900"), summary={"x": 1}))
        c.execute(insert(period_workspaces).values(period_key="2026-09", saved_at=3, archive=bytes(range(256)) * 50, archive_sha256="e" * 64, size_bytes=12800, manifest={"files": ["a"]}))
        c.execute(insert(recon_result_rows).values(run_id="R1", row_no=1, csp_id="1A850001", expected_commission=Decimal("10.5"), exception_flag=True, data={"k": "v"}))


def test_backup_is_encrypted_verifiable_and_restores_everything(engines, tmp_path, monkeypatch):
    from decimal import Decimal
    from app.services import backup
    src, target = engines
    monkeypatch.setenv("EKO_BACKUP_DIR", str(tmp_path / "bk"))
    _fill_everything(target)
    info = backup.create_backup("test")
    f = tmp_path / "bk" / info["file"]
    raw = f.read_bytes()
    assert raw.startswith(b"EKOENC1") and b"admin@eko.test" not in raw and b"1140884" not in raw
    check = backup.verify_backup(info["file"])
    assert check["ok"] and check["rows"] == info["rows"] == 8
    with pytest.raises(ValueError):                                       # a database with accounts is never overwritten silently
        backup.restore_backup(info["file"])
    result = backup.restore_backup(info["file"], force=True)
    assert result["rows"] == 8
    with target.begin() as c:
        assert c.execute(select(recon_runs.c.expected_commission)).scalar() == Decimal("1140884.6900")
        assert bytes(c.execute(select(period_workspaces.c.archive)).scalar()) == bytes(range(256)) * 50
        assert c.execute(select(src_uploads.c.meta)).scalar() == {"a": [1, {"b": None}]}
        assert c.execute(insert(audit_events).values(event_type="n", detail_json="{}", created_at=9).returning(audit_events.c.id)).scalar() > 30


def test_restore_into_an_empty_database_needs_no_force(engines, tmp_path, monkeypatch):
    from app.services import backup
    src, target = engines
    monkeypatch.setenv("EKO_BACKUP_DIR", str(tmp_path / "bk"))
    _fill_everything(target)
    name = backup.create_backup("test")["file"]
    with target.begin() as c:
        for t in reversed(metadata.sorted_tables):
            c.execute(t.delete())
    assert backup.restore_backup(name)["rows"] == 8


def test_tampered_or_wrong_key_backups_are_rejected_and_old_ones_pruned(engines, tmp_path, monkeypatch):
    import time
    from app import crypto_store
    from app.services import backup
    src, target = engines
    monkeypatch.setenv("EKO_BACKUP_DIR", str(tmp_path / "bk")); monkeypatch.setenv("EKO_BACKUP_KEEP", "2")
    _fill_everything(target)
    name = backup.create_backup("one")["file"]
    path = tmp_path / "bk" / name
    blob = bytearray(path.read_bytes()); blob[200] ^= 0xFF
    path.write_bytes(bytes(blob))
    with pytest.raises(crypto_store.DecryptionError):
        backup.verify_backup(name)
    for i in range(3):
        time.sleep(1.1); backup.create_backup(f"n{i}")
    assert len(backup.list_backups()) == 2                                  # only the newest EKO_BACKUP_KEEP remain
    assert backup.auto_backup_if_due(24) is None                            # a recent backup exists: nothing to do
