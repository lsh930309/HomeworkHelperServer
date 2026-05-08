import datetime as dt
import os
from pathlib import Path

os.environ["HOME"] = "/tmp/homeworkhelper-tests"
Path(os.environ["HOME"]).mkdir(parents=True, exist_ok=True)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.data import models
from src.data.session_repair import repair_preview_session_pollution


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    models.Base.metadata.create_all(bind=engine)
    return TestingSession()


def _ts(value: str) -> float:
    return dt.datetime.strptime(value, "%Y-%m-%d %H:%M").timestamp()


def test_repair_reopens_bug_closed_long_session_and_restores_last_played():
    db = _session()
    try:
        db.add(models.Process(id="game-a", name="Game A", last_played_timestamp=_ts("2026-05-08 12:10")))
        db.add(
            models.ProcessSession(
                process_id="game-a",
                process_name="Game A",
                start_timestamp=_ts("2026-04-01 10:00"),
                end_timestamp=_ts("2026-04-01 11:00"),
                session_duration=3600,
            )
        )
        db.add(
            models.ProcessSession(
                process_id="game-a",
                process_name="Game A",
                start_timestamp=_ts("2026-04-10 10:00"),
                end_timestamp=_ts("2026-05-08 12:10"),
                session_duration=_ts("2026-05-08 12:10") - _ts("2026-04-10 10:00"),
            )
        )
        db.commit()

        report = repair_preview_session_pollution(db)

        assert report.repaired_sessions == 1
        process = db.query(models.Process).filter_by(id="game-a").one()
        assert process.last_played_timestamp == _ts("2026-04-01 11:00")
        repaired = db.query(models.ProcessSession).filter_by(id=2).one()
        assert repaired.end_timestamp is None
        assert repaired.session_duration is None
    finally:
        db.close()


def test_repair_clears_last_played_when_no_valid_completed_session_remains():
    db = _session()
    try:
        db.add(models.Process(id="game-a", name="Game A", last_played_timestamp=_ts("2026-05-08 12:10")))
        db.add(
            models.ProcessSession(
                process_id="game-a",
                process_name="Game A",
                start_timestamp=_ts("2026-01-01 10:00"),
                end_timestamp=_ts("2026-05-08 12:10"),
                session_duration=_ts("2026-05-08 12:10") - _ts("2026-01-01 10:00"),
            )
        )
        db.commit()

        report = repair_preview_session_pollution(db)

        assert report.repaired_sessions == 1
        process = db.query(models.Process).filter_by(id="game-a").one()
        assert process.last_played_timestamp is None
    finally:
        db.close()


def test_repair_is_idempotent():
    db = _session()
    try:
        db.add(models.Process(id="game-a", name="Game A", last_played_timestamp=_ts("2026-05-08 12:10")))
        db.add(
            models.ProcessSession(
                process_id="game-a",
                process_name="Game A",
                start_timestamp=_ts("2026-04-01 10:00"),
                end_timestamp=_ts("2026-05-08 12:10"),
                session_duration=_ts("2026-05-08 12:10") - _ts("2026-04-01 10:00"),
            )
        )
        db.commit()

        first = repair_preview_session_pollution(db)
        second = repair_preview_session_pollution(db)

        assert first.repaired_sessions == 1
        assert second.repaired_sessions == 0
    finally:
        db.close()


def test_repair_ignores_old_long_sessions_before_incident_cutoff():
    db = _session()
    try:
        db.add(models.Process(id="game-a", name="Game A", last_played_timestamp=_ts("2026-04-01 12:00")))
        db.add(
            models.ProcessSession(
                process_id="game-a",
                process_name="Game A",
                start_timestamp=_ts("2026-03-01 10:00"),
                end_timestamp=_ts("2026-04-01 12:00"),
                session_duration=_ts("2026-04-01 12:00") - _ts("2026-03-01 10:00"),
            )
        )
        db.commit()

        report = repair_preview_session_pollution(db)

        assert report.repaired_sessions == 0
        session = db.query(models.ProcessSession).one()
        assert session.end_timestamp == _ts("2026-04-01 12:00")
    finally:
        db.close()
