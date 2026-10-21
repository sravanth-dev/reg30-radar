"""The migration runner (common/migrate.py) applies each file in its own committed
transaction. Real SQL, in a scratch schema of the backfill database (conftest.py).

The bug this pins (audit, 20 Oct 2026): pending()'s reads opened an implicit transaction,
so each `conn.transaction()` was only a savepoint inside one outer transaction, and a
failing file undid every migration the run had already printed as applied."""

import pytest

from reg30_radar.common import migrate


def test_a_failing_migration_leaves_the_earlier_ones_applied(scratch_conn, tmp_path):
    (tmp_path / "9001_ok.sql").write_text("create table m_ok (x int);", encoding="utf-8")
    (tmp_path / "9002_bad.sql").write_text("create table m_bad (x no_such_type);",
                                           encoding="utf-8")
    with pytest.raises(Exception, match="no_such_type"):
        migrate.apply_all(conn=scratch_conn, migrations_dir=tmp_path)
    scratch_conn.rollback()
    versions = {r[0] for r in scratch_conn.execute("select version from schema_migrations")}
    assert "9001_ok" in versions
    assert "9002_bad" not in versions
    assert scratch_conn.execute("select to_regclass('m_ok') is not null").fetchone()[0]


def test_an_applied_migration_is_not_run_again(scratch_conn, tmp_path):
    (tmp_path / "9001_ok.sql").write_text("create table m_once (x int);", encoding="utf-8")
    assert migrate.apply_all(conn=scratch_conn, migrations_dir=tmp_path) == ["9001_ok"]
    assert migrate.apply_all(conn=scratch_conn, migrations_dir=tmp_path) == []
