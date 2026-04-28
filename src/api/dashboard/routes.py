# dashboard/routes.py
"""Dashboard routes and analytics APIs."""

from __future__ import annotations

import datetime as dt
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from fastapi import APIRouter, Body, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from sqlalchemy import func

from src.data import models
from .icons import extract_icon_from_exe, generate_fallback_svg, get_color_for_game, get_icon_for_size
from .settings import load_settings, save_settings

router = APIRouter()

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATE_DIR = BASE_DIR / "templates"

SECONDS_PER_DAY = 86_400
DATE_FORMAT = "%Y-%m-%d"


def _today() -> dt.date:
    return dt.datetime.now().date()


def _parse_date(value: str | None, fallback: dt.date) -> dt.date:
    if not value:
        return fallback
    try:
        return dt.datetime.strptime(value, DATE_FORMAT).date()
    except ValueError as exc:
        raise ValueError(f"날짜는 YYYY-MM-DD 형식이어야 합니다: {value}") from exc


def _resolve_range(start: str | None, end: str | None) -> tuple[dt.date, dt.date, dt.datetime, dt.datetime]:
    """Resolve dashboard date range.

    Public API accepts inclusive start/end dates for UX convenience. Internally we
    use an exclusive end datetime at the next local midnight.
    """
    today = _today()
    start_date = _parse_date(start, today - dt.timedelta(days=29))
    end_date = _parse_date(end, today)
    if end_date < start_date:
        raise ValueError("end는 start보다 빠를 수 없습니다.")
    start_dt = dt.datetime.combine(start_date, dt.time.min)
    end_exclusive = dt.datetime.combine(end_date + dt.timedelta(days=1), dt.time.min)
    return start_date, end_date, start_dt, end_exclusive


def _date_list(start_date: dt.date, end_date: dt.date) -> list[str]:
    days = (end_date - start_date).days + 1
    return [(start_date + dt.timedelta(days=i)).strftime(DATE_FORMAT) for i in range(days)]


def _session_end(session: models.ProcessSession, now_ts: float | None = None) -> float:
    if session.end_timestamp is not None:
        return float(session.end_timestamp)
    if session.session_duration is not None:
        return float(session.start_timestamp) + float(session.session_duration)
    return now_ts if now_ts is not None else dt.datetime.now().timestamp()


def _effective_duration(session: models.ProcessSession, now_ts: float | None = None) -> float:
    if session.session_duration is not None:
        return max(0.0, float(session.session_duration))
    return max(0.0, _session_end(session, now_ts) - float(session.start_timestamp))


def _iter_overlaps(
    sessions: Iterable[models.ProcessSession],
    start_dt: dt.datetime,
    end_dt: dt.datetime,
    now_ts: float | None = None,
) -> Iterable[tuple[models.ProcessSession, dt.datetime, dt.datetime, float]]:
    start_ts = start_dt.timestamp()
    end_ts = end_dt.timestamp()
    for session in sessions:
        raw_start = float(session.start_timestamp)
        raw_end = _session_end(session, now_ts)
        overlap_start_ts = max(raw_start, start_ts)
        overlap_end_ts = min(raw_end, end_ts)
        if overlap_end_ts <= overlap_start_ts:
            continue
        overlap_start = dt.datetime.fromtimestamp(overlap_start_ts)
        overlap_end = dt.datetime.fromtimestamp(overlap_end_ts)
        yield session, overlap_start, overlap_end, overlap_end_ts - overlap_start_ts


def _query_sessions(db: Any, start_dt: dt.datetime, end_dt: dt.datetime, game_id: str | None = None) -> list[models.ProcessSession]:
    start_ts = start_dt.timestamp()
    end_ts = end_dt.timestamp()
    query = db.query(models.ProcessSession).filter(
        models.ProcessSession.start_timestamp < end_ts,
        (
            (models.ProcessSession.end_timestamp.is_(None))
            | (models.ProcessSession.end_timestamp >= start_ts)
            | (
                models.ProcessSession.session_duration.isnot(None)
                & ((models.ProcessSession.start_timestamp + models.ProcessSession.session_duration) >= start_ts)
            )
        ),
    )
    if game_id and game_id != "all":
        query = query.filter(models.ProcessSession.process_id == game_id)
    return query.order_by(models.ProcessSession.start_timestamp.asc()).all()


def _registered_process_maps(db: Any) -> tuple[set[str], dict[str, str]]:
    processes = db.query(models.Process).all()
    return {p.name.lower() for p in processes}, {p.name.lower(): p.id for p in processes}


def _filter_registered(db: Any, sessions: list[models.ProcessSession], show_unregistered: bool) -> list[models.ProcessSession]:
    if show_unregistered:
        return sessions
    registered_names, _ = _registered_process_maps(db)
    return [s for s in sessions if (s.process_name or "").lower() in registered_names]


def _split_by_day(start: dt.datetime, end: dt.datetime) -> Iterable[tuple[str, float]]:
    cursor = start
    while cursor < end:
        next_midnight = dt.datetime.combine(cursor.date() + dt.timedelta(days=1), dt.time.min)
        chunk_end = min(end, next_midnight)
        yield cursor.strftime(DATE_FORMAT), (chunk_end - cursor).total_seconds()
        cursor = chunk_end


def _split_by_hour(start: dt.datetime, end: dt.datetime) -> Iterable[tuple[int, int, float]]:
    cursor = start
    while cursor < end:
        next_hour = (cursor.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1))
        chunk_end = min(end, next_hour)
        yield cursor.weekday(), cursor.hour, (chunk_end - cursor).total_seconds()
        cursor = chunk_end


def _serialize_session(session: models.ProcessSession, duration_seconds: float | None = None) -> dict[str, Any]:
    raw_end = _session_end(session)
    duration = _effective_duration(session) if duration_seconds is None else duration_seconds
    return {
        "id": session.id,
        "process_id": session.process_id,
        "process_name": session.process_name,
        "start_timestamp": session.start_timestamp,
        "end_timestamp": session.end_timestamp,
        "effective_end_timestamp": raw_end,
        "duration_seconds": round(duration, 3),
        "is_active": session.end_timestamp is None,
        "stamina_at_end": getattr(session, "stamina_at_end", None),
    }


def _aggregate_summary(sessions: list[models.ProcessSession], start_dt: dt.datetime, end_dt: dt.datetime) -> dict[str, Any]:
    days = max(1, math.ceil((end_dt - start_dt).total_seconds() / SECONDS_PER_DAY))
    total_seconds = 0.0
    played_dates: set[str] = set()
    games: dict[str, dict[str, Any]] = {}
    longest: dict[str, Any] | None = None
    session_count = 0

    for session, overlap_start, overlap_end, overlap_seconds in _iter_overlaps(sessions, start_dt, end_dt):
        total_seconds += overlap_seconds
        session_count += 1
        game = games.setdefault(
            session.process_id,
            {"process_id": session.process_id, "process_name": session.process_name, "total_seconds": 0.0, "session_count": 0},
        )
        game["total_seconds"] += overlap_seconds
        game["session_count"] += 1
        for date_key, seconds in _split_by_day(overlap_start, overlap_end):
            if seconds > 0:
                played_dates.add(date_key)
        full_duration = _effective_duration(session)
        if longest is None or full_duration > longest["duration_seconds"]:
            longest = _serialize_session(session, full_duration)

    game_rows = sorted(games.values(), key=lambda row: row["total_seconds"], reverse=True)
    for row in game_rows:
        row["total_seconds"] = round(row["total_seconds"], 3)
        row["share"] = round(row["total_seconds"] / total_seconds, 6) if total_seconds else 0

    return {
        "total_seconds": round(total_seconds, 3),
        "daily_average_seconds": round(total_seconds / days, 3),
        "played_days": len(played_dates),
        "no_play_days": max(0, days - len(played_dates)),
        "session_count": session_count,
        "average_session_seconds": round(total_seconds / session_count, 3) if session_count else 0,
        "top_game": game_rows[0] if game_rows else None,
        "longest_session": longest,
        "games": game_rows,
    }


def _delta(current: float, previous: float) -> dict[str, float | None]:
    change = current - previous
    percent = None if previous == 0 else round((change / previous) * 100, 2)
    return {"current": round(current, 3), "previous": round(previous, 3), "change": round(change, 3), "percent": percent}


@router.get("/dashboard", response_class=HTMLResponse)
def get_dashboard():
    """Dashboard HTML entry point using stable packaged asset URLs."""
    template_path = TEMPLATE_DIR / "dashboard.html"
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()


@router.get("/api/dashboard/settings")
def get_settings():
    return JSONResponse(load_settings())


@router.post("/api/dashboard/settings")
def update_settings(settings: dict = Body(...)):
    current = load_settings()
    current.update(settings)
    save_settings(current)
    return {"status": "ok"}


@router.get("/api/analytics/timeline")
def get_analytics_timeline(
    start: str | None = Query(None),
    end: str | None = Query(None),
    bucket: str = Query("day", pattern="^day$"),
    game_id: str = Query("all"),
    show_unregistered: bool = Query(False),
):
    """Continuous play timeline split by local day."""
    from src.data.database import SessionLocal

    try:
        start_date, end_date, start_dt, end_dt = _resolve_range(start, end)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    db = SessionLocal()
    try:
        sessions = _filter_registered(db, _query_sessions(db, start_dt, end_dt, game_id), show_unregistered)
        days = {date_key: {"date": date_key, "total_seconds": 0.0, "games": {}} for date_key in _date_list(start_date, end_date)}
        games: dict[str, dict[str, Any]] = {}

        for session, overlap_start, overlap_end, _ in _iter_overlaps(sessions, start_dt, end_dt):
            game_total = games.setdefault(
                session.process_id,
                {"process_id": session.process_id, "process_name": session.process_name, "total_seconds": 0.0},
            )
            for date_key, seconds in _split_by_day(overlap_start, overlap_end):
                if date_key not in days:
                    continue
                day = days[date_key]
                day["total_seconds"] += seconds
                game_total["total_seconds"] += seconds
                game_day = day["games"].setdefault(
                    session.process_id,
                    {"process_id": session.process_id, "process_name": session.process_name, "total_seconds": 0.0, "sessions": 0},
                )
                game_day["total_seconds"] += seconds
                game_day["sessions"] += 1

        day_rows = []
        for day in days.values():
            day_rows.append({
                "date": day["date"],
                "total_seconds": round(day["total_seconds"], 3),
                "games": sorted(
                    ({**g, "total_seconds": round(g["total_seconds"], 3)} for g in day["games"].values()),
                    key=lambda row: row["total_seconds"],
                    reverse=True,
                ),
            })
        game_rows = sorted(
            ({**g, "total_seconds": round(g["total_seconds"], 3)} for g in games.values()),
            key=lambda row: row["total_seconds"],
            reverse=True,
        )
        return {"range": {"start": start_date.isoformat(), "end": end_date.isoformat()}, "bucket": bucket, "days": day_rows, "games": game_rows}
    finally:
        db.close()


@router.get("/api/analytics/summary")
def get_analytics_summary(
    start: str | None = Query(None),
    end: str | None = Query(None),
    game_id: str = Query("all"),
    show_unregistered: bool = Query(False),
):
    """Range summary plus previous-period deltas."""
    from src.data.database import SessionLocal

    try:
        start_date, end_date, start_dt, end_dt = _resolve_range(start, end)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    period = end_dt - start_dt
    prev_start_dt = start_dt - period
    prev_end_dt = start_dt
    db = SessionLocal()
    try:
        current_sessions = _filter_registered(db, _query_sessions(db, start_dt, end_dt, game_id), show_unregistered)
        previous_sessions = _filter_registered(db, _query_sessions(db, prev_start_dt, prev_end_dt, game_id), show_unregistered)
        current = _aggregate_summary(current_sessions, start_dt, end_dt)
        previous = _aggregate_summary(previous_sessions, prev_start_dt, prev_end_dt)
        return {
            "range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
            "previous_range": {
                "start": prev_start_dt.date().isoformat(),
                "end": (prev_end_dt - dt.timedelta(days=1)).date().isoformat(),
            },
            "metrics": current,
            "previous_metrics": previous,
            "deltas": {
                "total_seconds": _delta(current["total_seconds"], previous["total_seconds"]),
                "daily_average_seconds": _delta(current["daily_average_seconds"], previous["daily_average_seconds"]),
                "played_days": _delta(current["played_days"], previous["played_days"]),
                "session_count": _delta(current["session_count"], previous["session_count"]),
            },
        }
    finally:
        db.close()


@router.get("/api/analytics/patterns")
def get_analytics_patterns(
    start: str | None = Query(None),
    end: str | None = Query(None),
    game_id: str = Query("all"),
    show_unregistered: bool = Query(False),
):
    """Weekday/hour heatmap data for play-pattern analysis."""
    from src.data.database import SessionLocal

    try:
        start_date, end_date, start_dt, end_dt = _resolve_range(start, end)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    db = SessionLocal()
    try:
        sessions = _filter_registered(db, _query_sessions(db, start_dt, end_dt, game_id), show_unregistered)
        matrix = defaultdict(float)
        for _, overlap_start, overlap_end, _ in _iter_overlaps(sessions, start_dt, end_dt):
            for weekday, hour, seconds in _split_by_hour(overlap_start, overlap_end):
                matrix[(weekday, hour)] += seconds
        heatmap = [
            {"weekday": weekday, "hour": hour, "total_seconds": round(matrix[(weekday, hour)], 3)}
            for weekday in range(7)
            for hour in range(24)
        ]
        return {
            "range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
            "weekdays": ["월", "화", "수", "목", "금", "토", "일"],
            "hours": list(range(24)),
            "heatmap": heatmap,
        }
    finally:
        db.close()


@router.get("/api/analytics/sessions")
def get_analytics_sessions(
    start: str | None = Query(None),
    end: str | None = Query(None),
    game_id: str = Query("all"),
    show_unregistered: bool = Query(False),
    limit: int = Query(500, ge=1, le=2000),
):
    """Session detail rows for the selected date/game drawer."""
    from src.data.database import SessionLocal

    try:
        start_date, end_date, start_dt, end_dt = _resolve_range(start, end)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    db = SessionLocal()
    try:
        sessions = _filter_registered(db, _query_sessions(db, start_dt, end_dt, game_id), show_unregistered)
        rows = []
        for session, _, _, overlap_seconds in _iter_overlaps(sessions, start_dt, end_dt):
            rows.append(_serialize_session(session, overlap_seconds))
        rows.sort(key=lambda row: row["start_timestamp"], reverse=True)
        return {"range": {"start": start_date.isoformat(), "end": end_date.isoformat()}, "sessions": rows[:limit]}
    finally:
        db.close()


@router.get("/api/dashboard/playtime")
def get_playtime_stats(
    period: str = Query("week"),
    offset: int = Query(0, description="기간 오프셋 (-1: 이전, 1: 다음)"),
    game_id: str = Query("all"),
    merge_names: bool = Query(True),
    show_unregistered: bool = Query(False),
):
    """Legacy period playtime stats kept for compatibility."""
    from src.data.database import SessionLocal

    db = SessionLocal()
    try:
        now = dt.datetime.now()
        days = 7 if period == "week" else 30
        if period == "week":
            days_since_sunday = (now.weekday() + 1) % 7
            current_week_sunday = (now - dt.timedelta(days=days_since_sunday)).replace(hour=0, minute=0, second=0, microsecond=0)
            start_date = current_week_sunday - dt.timedelta(weeks=-offset)
        else:
            target_month = now.month + offset
            target_year = now.year
            while target_month < 1:
                target_month += 12
                target_year -= 1
            while target_month > 12:
                target_month -= 12
                target_year += 1
            start_date = dt.datetime(target_year, target_month, 1)
            end_date = dt.datetime(target_year + 1, 1, 1) if target_month == 12 else dt.datetime(target_year, target_month + 1, 1)
            days = (end_date - start_date).days

        start_timestamp = start_date.timestamp()
        dates = [(start_date + dt.timedelta(days=i)).strftime(DATE_FORMAT) for i in range(days)]
        query = db.query(
            func.date(models.ProcessSession.start_timestamp, "unixepoch", "localtime").label("play_date"),
            models.ProcessSession.process_id,
            models.ProcessSession.process_name,
            func.sum(models.ProcessSession.session_duration).label("total_seconds"),
        ).filter(
            models.ProcessSession.start_timestamp >= start_timestamp,
            models.ProcessSession.start_timestamp < start_timestamp + (days * SECONDS_PER_DAY),
            models.ProcessSession.session_duration.isnot(None),
        )
        if game_id != "all":
            query = query.filter(models.ProcessSession.process_id == game_id)
        results = query.group_by("play_date", models.ProcessSession.process_id).all()

        registered_names = set()
        process_ids = {}
        if not show_unregistered:
            registered_names, process_ids = _registered_process_maps(db)

        games_data = {}
        for row in results:
            if not show_unregistered and row.process_name.lower() not in registered_names:
                continue
            key = row.process_name if merge_names else row.process_id
            games_data.setdefault(key, {"name": row.process_name, "minutes": [0] * days, "process_id": process_ids.get(row.process_name.lower(), row.process_id)})
            if row.play_date in dates:
                games_data[key]["minutes"][dates.index(row.play_date)] += (row.total_seconds or 0) / 60

        today_str = now.strftime(DATE_FORMAT)
        days_since_sunday = (now.weekday() + 1) % 7
        current_week_start = (now - dt.timedelta(days=days_since_sunday)).replace(hour=0, minute=0, second=0, microsecond=0)
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        today_minutes = week_minutes = month_minutes = 0
        for i, ds in enumerate(dates):
            day_dt = dt.datetime.strptime(ds, DATE_FORMAT)
            day_total = sum(g["minutes"][i] for g in games_data.values())
            if ds == today_str:
                today_minutes = day_total
            if current_week_start <= day_dt < current_week_start + dt.timedelta(days=7):
                week_minutes += day_total
            if day_dt >= current_month_start and day_dt.month == now.month:
                month_minutes += day_total
        return {"dates": dates, "games": games_data, "stats": {"today_minutes": today_minutes, "week_minutes": week_minutes, "month_minutes": month_minutes}}
    finally:
        db.close()


@router.get("/api/dashboard/calendar")
def get_calendar_data(year: int = Query(...), month: int = Query(..., ge=0, le=11), threshold: int = Query(10), show_unregistered: bool = Query(False)):
    """Calendar data API kept for compatibility."""
    from src.data.database import SessionLocal

    db = SessionLocal()
    try:
        start_date = dt.datetime(year, month + 1, 1)
        end_date = dt.datetime(year + 1, 1, 1) if month == 11 else dt.datetime(year, month + 2, 1)
        registered_names = set()
        if not show_unregistered:
            registered_names, _ = _registered_process_maps(db)
        results = db.query(
            func.date(models.ProcessSession.start_timestamp, "unixepoch", "localtime").label("play_date"),
            models.ProcessSession.process_id,
            models.ProcessSession.process_name,
            func.sum(models.ProcessSession.session_duration).label("total_seconds"),
        ).filter(
            models.ProcessSession.start_timestamp >= start_date.timestamp(),
            models.ProcessSession.start_timestamp < end_date.timestamp(),
            models.ProcessSession.session_duration.isnot(None),
        ).group_by("play_date", models.ProcessSession.process_name).all()
        days_data = {}
        for row in results:
            if not show_unregistered and row.process_name.lower() not in registered_names:
                continue
            total_min = (row.total_seconds or 0) / 60
            if total_min < threshold:
                continue
            days_data.setdefault(row.play_date, {"games": []})["games"].append({"id": row.process_id, "name": row.process_name, "minutes": total_min})
        return {"days": days_data}
    finally:
        db.close()


@router.get("/api/dashboard/icons/{process_id}")
def get_game_icon(process_id: str, size: int = Query(default=64, ge=1, le=256)):
    """Game icon API: PNG cache with SVG fallback."""
    from src.data.database import SessionLocal

    db = SessionLocal()
    try:
        process = db.query(models.Process).filter(models.Process.id == process_id).first()
        if not process:
            return Response(content=generate_fallback_svg("?", "#6366f1"), media_type="image/svg+xml")
        name = process.name
        exe_path = process.monitoring_path or process.launch_path
        icon_path = get_icon_for_size(process_id, size)
        if icon_path:
            return FileResponse(str(icon_path), media_type="image/png")
        if exe_path and os.path.exists(exe_path):
            extract_icon_from_exe(exe_path, process_id)
            icon_path = get_icon_for_size(process_id, size)
            if icon_path:
                return FileResponse(str(icon_path), media_type="image/png")
        return Response(content=generate_fallback_svg(name, get_color_for_game(name)), media_type="image/svg+xml")
    finally:
        db.close()
