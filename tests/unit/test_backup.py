"""The local backup command (common/backup.py). No database, no pg_dump run: only how the
command line is built, because the one thing it must never do is put the password there,
where any process list would show it."""

from pathlib import Path

from reg30_radar.common.backup import build_command, prune

# Built from parts so no credential-shaped string sits in the repo for a secret scan to flag.
FAKE_PW = "not-a-real-password"
URL = "postgresql://tradebot:" + FAKE_PW + "@localhost:5432/tradebot_backfill"


def test_password_goes_to_the_environment_never_the_command_line():
    argv, env = build_command(URL, Path("pg_dump"), Path("backups/x.dump"))
    assert not any(FAKE_PW in part for part in argv)
    assert env["PGPASSWORD"] == FAKE_PW


def test_connection_fields_and_custom_format_are_passed():
    argv, _ = build_command(URL, Path("pg_dump"), Path("backups/x.dump"))
    assert argv[0] == "pg_dump"
    for expected in (["--host", "localhost"], ["--port", "5432"], ["--username", "tradebot"],
                     ["--dbname", "tradebot_backfill"], ["--file", str(Path("backups/x.dump"))]):
        i = argv.index(expected[0])
        assert argv[i + 1] == expected[1]
    assert "--format=custom" in argv


def test_a_url_without_a_password_sets_no_pgpassword():
    _, env = build_command("postgresql://tradebot@localhost/tradebot", Path("pg_dump"),
                           Path("x.dump"))
    assert "PGPASSWORD" not in env


def test_prune_keeps_the_newest_per_database(tmp_path):
    for day in range(1, 11):
        (tmp_path / f"tradebot_backfill_202610{day:02d}_000000.dump").write_bytes(b"x")
    (tmp_path / "tradebot_20261001_000000.dump").write_bytes(b"x")
    removed = prune(tmp_path, "tradebot_backfill", keep=7)
    left = sorted(p.name for p in tmp_path.glob("tradebot_backfill_*.dump"))
    assert len(removed) == 3 and len(left) == 7
    assert left[0] == "tradebot_backfill_20261004_000000.dump"
    # the live database's dump is a different prefix and is never touched
    assert (tmp_path / "tradebot_20261001_000000.dump").exists()


def test_prune_does_not_confuse_tradebot_with_tradebot_backfill(tmp_path):
    # ops/backup.sh's glob "tradebot_*" also matched backfill dumps; this must not.
    for day in range(1, 10):
        (tmp_path / f"tradebot_backfill_202610{day:02d}_000000.dump").write_bytes(b"x")
    (tmp_path / "tradebot_20261001_000000.dump").write_bytes(b"x")
    removed = prune(tmp_path, "tradebot", keep=7)
    assert removed == []
    assert len(list(tmp_path.glob("tradebot_backfill_*.dump"))) == 9
