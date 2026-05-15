# dashboard/routes.py
"""Dashboard routes and analytics APIs."""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import unicodedata
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from sqlalchemy import func
from contextlib import contextmanager

from src.data import models
from src.utils.game_preset_manager import GamePresetManager
from src.utils.icon_helper import resolve_preset_icon_path
from .icons import extract_icon_from_exe, fallback_png_bytes, generate_fallback_svg, get_color_for_game, get_icon_for_size, safe_icon_cache_key
from .settings import load_settings, save_settings

router = APIRouter()

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATE_DIR = BASE_DIR / "templates"

SECONDS_PER_DAY = 86_400
DATE_FORMAT = "%Y-%m-%d"
EPOCH_DATE = dt.date(1970, 1, 1)
MAX_OPEN_SESSION_SECONDS = 24 * 60 * 60
MIN_SMART_SESSION_SECONDS = 60
MIN_LONG_SESSION_SECONDS = 3 * 60 * 60


@contextmanager
def _dashboard_db_session():
    """Serialize dashboard DB reads with Beholder backup restore swaps."""
    from src.api.beholder_routes import database_access_gate
    from src.data.database import SessionLocal

    with database_access_gate():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()


def _game_key(name: str | None) -> str:
    """Normalize game display names into a stable analytics grouping key."""
    normalized = unicodedata.normalize("NFKC", name or "")
    folded = normalized.casefold()
    key = re.sub(r"[\W_]+", "", folded, flags=re.UNICODE)
    return key or "unknown"


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * percentile
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return ordered[int(pos)]
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def _build_game_groups(db: Any, sessions: list[models.ProcessSession] | None = None, show_unregistered: bool = False) -> dict[str, dict[str, Any]]:
    """Build normalized game groups from registered processes plus optional sessions."""
    groups: dict[str, dict[str, Any]] = {}

    def add(process_id: str | None, display_name: str | None) -> None:
        if not display_name:
            display_name = process_id or "알 수 없는 게임"
        key = _game_key(display_name)
        group = groups.setdefault(
            key,
            {
                "game_key": key,
                "display_name": display_name,
                "process_ids": [],
                "icon_process_id": None,
                "total_seconds": 0.0,
            },
        )
        if process_id and process_id not in group["process_ids"]:
            group["process_ids"].append(process_id)

    for process in db.query(models.Process).all():
        add(process.id, process.name)
    if show_unregistered:
        for session in sessions or []:
            add(session.process_id, session.process_name)

    ordered_keys = sorted(groups, key=lambda key: groups[key]["display_name"].casefold())
    total = max(1, len(ordered_keys))
    for index, key in enumerate(ordered_keys):
        group = groups[key]
        group["color"] = get_color_for_game(key, index, total)
        group["icon_process_id"] = _choose_icon_process_id(group["process_ids"])
    return groups


def _choose_icon_process_id(process_ids: list[str]) -> str | None:
    for process_id in process_ids:
        if get_icon_for_size(process_id, 128):
            return process_id
    return process_ids[0] if process_ids else None


def _session_game_key(session: models.ProcessSession) -> str:
    return _game_key(session.process_name or session.process_id)


def _game_meta(session: models.ProcessSession, groups: dict[str, dict[str, Any]]) -> dict[str, Any]:
    key = _session_game_key(session)
    group = groups.get(key) or {
        "game_key": key,
        "display_name": session.process_name or session.process_id or "알 수 없는 게임",
        "icon_process_id": session.process_id,
        "color": get_color_for_game(key),
    }
    return {
        "game_key": key,
        "display_name": group["display_name"],
        "icon_process_id": group.get("icon_process_id"),
        "color": group.get("color"),
    }


def _filter_sessions_by_game_key(sessions: list[models.ProcessSession], game_id: str | None) -> list[models.ProcessSession]:
    if not game_id or game_id == "all":
        return sessions
    return [session for session in sessions if _session_game_key(session) == game_id or session.process_id == game_id]


def _insights_for_sessions(
    sessions: list[models.ProcessSession],
    start_dt: dt.datetime,
    end_dt: dt.datetime,
) -> dict[str, Any]:
    durations = [_effective_duration(session) for session in sessions if _effective_duration(session) > 0]
    non_short = [duration for duration in durations if duration >= MIN_SMART_SESSION_SECONDS]
    q1 = _percentile(non_short, 0.25)
    q3 = _percentile(non_short, 0.75)
    iqr_threshold = q3 + (1.5 * (q3 - q1)) if non_short else MIN_LONG_SESSION_SECONDS
    p90 = _percentile(non_short, 0.9)
    distribution_thresholds = [value for value in (iqr_threshold, p90) if value > 0]
    long_threshold = max(float(MIN_LONG_SESSION_SECONDS), min(distribution_thresholds) if distribution_thresholds else 0.0)
    long_sessions = [session for session in sessions if _effective_duration(session) >= long_threshold]
    very_short_count = sum(1 for duration in durations if duration < MIN_SMART_SESSION_SECONDS)
    normal_durations = [duration for duration in non_short if duration < long_threshold]
    smart_sample = normal_durations if len(normal_durations) >= 3 else non_short
    smart_average = sum(smart_sample) / len(smart_sample) if smart_sample else 0.0
    longest_normal = max(normal_durations, default=(max(non_short, default=0.0)))

    long_dates = sorted(dt.datetime.fromtimestamp(float(session.start_timestamp)).date() for session in long_sessions)
    intervals = [(b - a).days for a, b in zip(long_dates, long_dates[1:])]

    weekday_totals = defaultdict(float)
    hour_totals = defaultdict(float)
    for _, overlap_start, overlap_end, _ in _iter_overlaps(sessions, start_dt, end_dt):
        for weekday, hour, seconds in _split_by_hour(overlap_start, overlap_end):
            weekday_totals[weekday] += seconds
            hour_totals[hour] += seconds
    favorite_weekday = max(weekday_totals, key=weekday_totals.get) if weekday_totals else None
    favorite_hour = max(hour_totals, key=hour_totals.get) if hour_totals else None
    weekday_seconds = sum(v for k, v in weekday_totals.items() if k < 5)
    weekend_seconds = sum(v for k, v in weekday_totals.items() if k >= 5)
    if weekday_seconds == weekend_seconds == 0:
        preference = "none"
    elif weekend_seconds > weekday_seconds:
        preference = "weekend"
    elif weekday_seconds > weekend_seconds:
        preference = "weekday"
    else:
        preference = "balanced"

    range_days = max(1.0, (end_dt - start_dt).total_seconds() / SECONDS_PER_DAY)
    range_total = sum(overlap for _, _, _, overlap in _iter_overlaps(sessions, start_dt, end_dt))
    return {
        "smart_average_session_seconds": round(smart_average, 3),
        "longest_normal_session_seconds": round(longest_normal, 3),
        "very_short_session_count": very_short_count,
        "long_session_count": len(long_sessions),
        "long_session_threshold_seconds": round(long_threshold, 3),
        "long_session_recent_date": long_dates[-1].isoformat() if long_dates else None,
        "long_session_average_interval_days": round(sum(intervals) / len(intervals), 2) if intervals else None,
        "weekly_average_seconds": round(range_total / range_days * 7, 3),
        "favorite_weekday": favorite_weekday,
        "favorite_hour": favorite_hour,
        "weekday_weekend_preference": preference,
    }


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
    now_ts = now_ts if now_ts is not None else dt.datetime.now().timestamp()
    if now_ts - float(session.start_timestamp) > MAX_OPEN_SESSION_SECONDS:
        return float(session.start_timestamp)
    return now_ts


def _session_duration(session: models.ProcessSession, now_ts: float | None = None) -> float:
    return max(0.0, _session_end(session, now_ts) - float(session.start_timestamp))


def _effective_duration(session: models.ProcessSession, now_ts: float | None = None) -> float:
    return _session_duration(session, now_ts)


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


def _completed_session_filter(start_ts: float | None = None, end_ts: float | None = None):
    clauses = [
        models.ProcessSession.end_timestamp.isnot(None),
        models.ProcessSession.end_timestamp > models.ProcessSession.start_timestamp,
    ]
    if end_ts is not None:
        clauses.append(models.ProcessSession.start_timestamp < end_ts)
    if start_ts is not None:
        clauses.append(models.ProcessSession.end_timestamp >= start_ts)
    return clauses


def _query_sessions(db: Any, start_dt: dt.datetime, end_dt: dt.datetime) -> list[models.ProcessSession]:
    start_ts = start_dt.timestamp()
    end_ts = end_dt.timestamp()
    query = db.query(models.ProcessSession).filter(*_completed_session_filter(start_ts, end_ts))
    return query.order_by(models.ProcessSession.start_timestamp.asc()).all()


def _query_all_completed_sessions(db: Any) -> list[models.ProcessSession]:
    query = db.query(models.ProcessSession).filter(*_completed_session_filter())
    return query.order_by(models.ProcessSession.start_timestamp.asc()).all()


def _analytics_span_dates(sessions: list[models.ProcessSession]) -> list[tuple[dt.date, dt.date]]:
    spans = []
    for session in sessions:
        start_ts = float(session.start_timestamp)
        end_ts = _session_end(session)
        if end_ts <= start_ts:
            continue
        spans.append((dt.datetime.fromtimestamp(start_ts).date(), (dt.datetime.fromtimestamp(end_ts) - dt.timedelta(microseconds=1)).date()))
    return spans


def _normalize_all_time_range(
    start_date: dt.date,
    end_date: dt.date,
    start_dt: dt.datetime,
    end_dt: dt.datetime,
    sessions: list[models.ProcessSession],
) -> tuple[dt.date, dt.date, dt.datetime, dt.datetime]:
    """Clamp open-ended "all time" requests to the actual playable data span.

    The frontend historically used 1970-01-01 as the "all" lower bound. Keeping
    that range literally makes averages/no-play days meaningless and can push
    previous-period math before the Unix epoch on Windows. For all-time requests,
    derive the visible span from valid session overlaps instead.
    """
    if start_date > EPOCH_DATE:
        return start_date, end_date, start_dt, end_dt

    spans = _analytics_span_dates(sessions)
    if not spans:
        return end_date, end_date, dt.datetime.combine(end_date, dt.time.min), dt.datetime.combine(end_date + dt.timedelta(days=1), dt.time.min)

    actual_start = min(start for start, _ in spans)
    actual_end = min(end_date, max(end for _, end in spans))
    if actual_end < actual_start:
        actual_end = actual_start
    return (
        actual_start,
        actual_end,
        dt.datetime.combine(actual_start, dt.time.min),
        dt.datetime.combine(actual_end + dt.timedelta(days=1), dt.time.min),
    )


def _sessions_for_range(
    db: Any,
    start_date: dt.date,
    end_date: dt.date,
    start_dt: dt.datetime,
    end_dt: dt.datetime,
    game_id: str | None,
    show_unregistered: bool,
) -> tuple[dt.date, dt.date, dt.datetime, dt.datetime, list[models.ProcessSession]]:
    sessions = _filter_registered(db, _query_sessions(db, start_dt, end_dt), show_unregistered)
    sessions = _filter_sessions_by_game_key(sessions, game_id)
    start_date, end_date, start_dt, end_dt = _normalize_all_time_range(start_date, end_date, start_dt, end_dt, sessions)
    return start_date, end_date, start_dt, end_dt, sessions


def _data_bounds(db: Any, game_id: str | None = None, show_unregistered: bool = False) -> tuple[dt.date, dt.date]:
    sessions = _filter_registered(db, _query_all_completed_sessions(db), show_unregistered)
    sessions = _filter_sessions_by_game_key(sessions, game_id)
    spans = _analytics_span_dates(sessions)
    today = _today()
    if not spans:
        return today, today
    return min(start for start, _ in spans), max(end for _, end in spans)


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


def _serialize_session(session: models.ProcessSession, duration_seconds: float | None = None, groups: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    raw_end = _session_end(session)
    duration = _effective_duration(session) if duration_seconds is None else duration_seconds
    meta = _game_meta(session, groups or {})
    return {
        "id": session.id,
        "process_id": session.process_id,
        "process_name": session.process_name,
        **meta,
        "start_timestamp": session.start_timestamp,
        "end_timestamp": session.end_timestamp,
        "effective_end_timestamp": raw_end,
        "duration_seconds": round(duration, 3),
        "is_active": session.end_timestamp is None,
        "stamina_at_end": getattr(session, "stamina_at_end", None),
    }


def _aggregate_summary(
    sessions: list[models.ProcessSession],
    start_dt: dt.datetime,
    end_dt: dt.datetime,
    groups: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    groups = groups or {}
    days = max(1, math.ceil((end_dt - start_dt).total_seconds() / SECONDS_PER_DAY))
    total_seconds = 0.0
    played_dates: set[str] = set()
    games: dict[str, dict[str, Any]] = {}
    grouped_sessions: dict[str, list[models.ProcessSession]] = defaultdict(list)
    longest: dict[str, Any] | None = None
    session_count = 0

    for session, overlap_start, overlap_end, overlap_seconds in _iter_overlaps(sessions, start_dt, end_dt):
        total_seconds += overlap_seconds
        session_count += 1
        meta = _game_meta(session, groups)
        game = games.setdefault(
            meta["game_key"],
            {
                **meta,
                "process_ids": list(groups.get(meta["game_key"], {}).get("process_ids", [session.process_id])),
                "total_seconds": 0.0,
                "session_count": 0,
            },
        )
        game["total_seconds"] += overlap_seconds
        game["session_count"] += 1
        grouped_sessions[meta["game_key"]].append(session)
        for date_key, seconds in _split_by_day(overlap_start, overlap_end):
            if seconds > 0:
                played_dates.add(date_key)
        full_duration = _effective_duration(session)
        if longest is None or full_duration > longest["duration_seconds"]:
            longest = _serialize_session(session, full_duration, groups)

    game_rows = sorted(games.values(), key=lambda row: row["total_seconds"], reverse=True)
    for row in game_rows:
        row["total_seconds"] = round(row["total_seconds"], 3)
        row["share"] = round(row["total_seconds"] / total_seconds, 6) if total_seconds else 0
        row["insights"] = _insights_for_sessions(grouped_sessions[row["game_key"]], start_dt, end_dt)

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


@router.get("/api/analytics/games")
def get_analytics_games(show_unregistered: bool = Query(False)):
    """Return normalized game choices independent of the active dashboard filters."""
    with _dashboard_db_session() as db:
        sessions = _filter_registered(db, _query_all_completed_sessions(db), show_unregistered)
        groups = _build_game_groups(db, sessions, show_unregistered)
        totals = defaultdict(float)
        for session in sessions:
            totals[_session_game_key(session)] += _effective_duration(session)
        rows = []
        for key, group in groups.items():
            rows.append({
                "game_key": key,
                "display_name": group["display_name"],
                "process_ids": group["process_ids"],
                "icon_process_id": group.get("icon_process_id"),
                "color": group.get("color"),
                "total_seconds": round(totals[key], 3),
            })
        rows.sort(key=lambda row: row["total_seconds"], reverse=True)
        return {"games": rows}


@router.get("/api/analytics/range")
def get_analytics_range(
    game_id: str = Query("all"),
    show_unregistered: bool = Query(False),
):
    """Return the actual session date bounds for all-time range selection."""
    with _dashboard_db_session() as db:
        start_date, end_date = _data_bounds(db, game_id, show_unregistered)
        return {"start": start_date.isoformat(), "end": end_date.isoformat()}


@router.get("/api/analytics/timeline")
def get_analytics_timeline(
    start: str | None = Query(None),
    end: str | None = Query(None),
    bucket: str = Query("day", pattern="^day$"),
    game_id: str = Query("all"),
    show_unregistered: bool = Query(False),
):
    """Daily timeline based on each session's start date and duration."""
    try:
        start_date, end_date, start_dt, end_dt = _resolve_range(start, end)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    with _dashboard_db_session() as db:
        start_date, end_date, start_dt, end_dt, sessions = _sessions_for_range(
            db, start_date, end_date, start_dt, end_dt, game_id, show_unregistered
        )
        groups = _build_game_groups(db, sessions, show_unregistered)
        days = {date_key: {"date": date_key, "total_seconds": 0.0, "games": {}} for date_key in _date_list(start_date, end_date)}
        games: dict[str, dict[str, Any]] = {}

        for session, overlap_start, overlap_end, _ in _iter_overlaps(sessions, start_dt, end_dt):
            meta = _game_meta(session, groups)
            group = groups.get(meta["game_key"], {})
            game_total = games.setdefault(
                meta["game_key"],
                {**meta, "process_ids": list(group.get("process_ids", [session.process_id])), "total_seconds": 0.0},
            )
            for date_key, seconds in _split_by_day(overlap_start, overlap_end):
                if date_key not in days:
                    continue
                day = days[date_key]
                day["total_seconds"] += seconds
                game_total["total_seconds"] += seconds
                game_day = day["games"].setdefault(
                    meta["game_key"],
                    {**meta, "process_ids": list(group.get("process_ids", [session.process_id])), "total_seconds": 0.0, "sessions": 0},
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


@router.get("/api/analytics/summary")
def get_analytics_summary(
    start: str | None = Query(None),
    end: str | None = Query(None),
    game_id: str = Query("all"),
    show_unregistered: bool = Query(False),
):
    """Range summary plus previous-period deltas."""
    try:
        start_date, end_date, start_dt, end_dt = _resolve_range(start, end)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    with _dashboard_db_session() as db:
        start_date, end_date, start_dt, end_dt, current_sessions = _sessions_for_range(
            db, start_date, end_date, start_dt, end_dt, game_id, show_unregistered
        )
        period = end_dt - start_dt
        prev_start_dt = start_dt - period
        prev_end_dt = start_dt
        if prev_start_dt.date() < EPOCH_DATE:
            previous_sessions = []
            previous_range = None
        else:
            previous_sessions = _filter_registered(db, _query_sessions(db, prev_start_dt, prev_end_dt), show_unregistered)
            previous_sessions = _filter_sessions_by_game_key(previous_sessions, game_id)
            previous_range = {
                "start": prev_start_dt.date().isoformat(),
                "end": (prev_end_dt - dt.timedelta(days=1)).date().isoformat(),
            }
        groups = _build_game_groups(db, current_sessions + previous_sessions, show_unregistered)
        current = _aggregate_summary(current_sessions, start_dt, end_dt, groups)
        previous = _aggregate_summary(previous_sessions, prev_start_dt, prev_end_dt, groups)
        return {
            "range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
            "previous_range": previous_range,
            "metrics": current,
            "previous_metrics": previous,
            "deltas": {
                "total_seconds": _delta(current["total_seconds"], previous["total_seconds"]),
                "daily_average_seconds": _delta(current["daily_average_seconds"], previous["daily_average_seconds"]),
                "played_days": _delta(current["played_days"], previous["played_days"]),
                "session_count": _delta(current["session_count"], previous["session_count"]),
            },
        }


@router.get("/api/analytics/patterns")
def get_analytics_patterns(
    start: str | None = Query(None),
    end: str | None = Query(None),
    game_id: str = Query("all"),
    show_unregistered: bool = Query(False),
):
    """Weekday/hour heatmap data for play-pattern analysis."""
    try:
        start_date, end_date, start_dt, end_dt = _resolve_range(start, end)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    with _dashboard_db_session() as db:
        start_date, end_date, start_dt, end_dt, sessions = _sessions_for_range(
            db, start_date, end_date, start_dt, end_dt, game_id, show_unregistered
        )
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


@router.get("/api/analytics/sessions")
def get_analytics_sessions(
    start: str | None = Query(None),
    end: str | None = Query(None),
    game_id: str = Query("all"),
    show_unregistered: bool = Query(False),
    limit: int = Query(500, ge=1, le=2000),
):
    """Session detail rows for the selected date/game drawer."""
    try:
        start_date, end_date, start_dt, end_dt = _resolve_range(start, end)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    with _dashboard_db_session() as db:
        start_date, end_date, start_dt, end_dt, sessions = _sessions_for_range(
            db, start_date, end_date, start_dt, end_dt, game_id, show_unregistered
        )
        groups = _build_game_groups(db, sessions, show_unregistered)
        rows = []
        for session, _, _, overlap_seconds in _iter_overlaps(sessions, start_dt, end_dt):
            rows.append(_serialize_session(session, overlap_seconds, groups))
        rows.sort(key=lambda row: row["start_timestamp"], reverse=True)
        return {"range": {"start": start_date.isoformat(), "end": end_date.isoformat()}, "sessions": rows[:limit]}


@router.get("/api/dashboard/playtime")
def get_playtime_stats(
    period: str = Query("week"),
    offset: int = Query(0, description="기간 오프셋 (-1: 이전, 1: 다음)"),
    game_id: str = Query("all"),
    merge_names: bool = Query(True),
    show_unregistered: bool = Query(False),
):
    """Legacy period playtime stats kept for compatibility."""
    with _dashboard_db_session() as db:
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


@router.get("/api/dashboard/calendar")
def get_calendar_data(year: int = Query(...), month: int = Query(..., ge=0, le=11), threshold: int = Query(10), show_unregistered: bool = Query(False)):
    """Calendar data API kept for compatibility."""
    with _dashboard_db_session() as db:
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


@router.get("/api/dashboard/icons/{process_id}")
def get_game_icon(process_id: str, size: int = Query(default=64, ge=1, le=256), format: str = Query(default="svg")):
    """Game icon API: PNG cache with SVG fallback."""
    with _dashboard_db_session() as db:
        process = db.query(models.Process).filter(models.Process.id == process_id).first()
        if not process:
            if format == "png":
                fallback = fallback_png_bytes("?", size)
                if fallback is not None:
                    return Response(content=fallback, media_type="image/png")
            return Response(content=generate_fallback_svg("?", "#6366f1"), media_type="image/svg+xml")
        name = process.name
        exe_path = process.monitoring_path or process.launch_path
        cache_key = safe_icon_cache_key(process_id)
        icon_path = get_icon_for_size(cache_key, size)
        if icon_path:
            return FileResponse(str(icon_path), media_type="image/png")
        if exe_path and os.path.exists(exe_path):
            extract_icon_from_exe(exe_path, cache_key)
            icon_path = get_icon_for_size(cache_key, size)
            if icon_path:
                return FileResponse(str(icon_path), media_type="image/png")
        if format == "png":
            fallback = fallback_png_bytes(name, size)
            if fallback is not None:
                return Response(content=fallback, media_type="image/png")
        return Response(content=generate_fallback_svg(name, get_color_for_game(name)), media_type="image/svg+xml")


def _read_preset_by_id(preset_id: str | None) -> dict[str, Any] | None:
    if not preset_id:
        return None
    for path in (GamePresetManager.SYSTEM_PRESET_FILE, GamePresetManager.USER_PRESET_FILE):
        try:
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for preset in payload.get("presets", []):
            if preset.get("id") == preset_id:
                return preset
    return None


def _preset_icon_response(icon_path: str, requested_size: int) -> Response | FileResponse:
    """Return a native-client PNG resource icon at the requested pixel size."""
    requested_size = max(1, min(256, int(requested_size or 32)))
    try:
        from PIL import Image

        with Image.open(icon_path) as image:
            image.load()
            if image.mode != "RGBA":
                image = image.convert("RGBA")
            current_size = max(image.size)
            if current_size != requested_size:
                resampling_filter = getattr(Image, "Resampling", Image)
                resampling = resampling_filter.LANCZOS if current_size > requested_size else resampling_filter.BICUBIC
                image = image.resize((requested_size, requested_size), resampling)
            output = BytesIO()
            image.save(output, format="PNG", optimize=True)
            return Response(content=output.getvalue(), media_type="image/png")
    except Exception:
        return FileResponse(icon_path, media_type="image/png")


@router.get("/api/dashboard/resource-icons/{process_id}")
def get_resource_icon(process_id: str, size: int = Query(default=32, ge=1, le=256)):
    """Resource/stamina icon API for native clients."""
    with _dashboard_db_session() as db:
        process = db.query(models.Process).filter(models.Process.id == process_id).first()
        if not process:
            raise HTTPException(status_code=404, detail="process not found")
        preset = _read_preset_by_id(getattr(process, "user_preset_id", None))
        if not preset:
            raise HTTPException(status_code=404, detail="preset not found")
        icon_path = resolve_preset_icon_path(str(preset.get("icon_path") or ""), str(preset.get("icon_type") or "system"))
        if not icon_path:
            raise HTTPException(status_code=404, detail="resource icon not found")
        return _preset_icon_response(icon_path, size)
