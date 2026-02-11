# dashboard/routes.py
"""대시보드 API 라우터"""

import datetime
import os
from pathlib import Path
from fastapi import APIRouter, Query, Body
from fastapi.responses import HTMLResponse, JSONResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func

from src.data import models
from .settings import load_settings, save_settings, DEFAULT_SETTINGS
from .icons import extract_icon_from_exe, generate_fallback_svg, get_color_for_game, get_cached_icon_path, get_icon_for_size

router = APIRouter()

# 정적 파일 및 템플릿 경로
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATE_DIR = BASE_DIR / "templates"


@router.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard():
    """대시보드 HTML 페이지"""
    template_path = TEMPLATE_DIR / "dashboard.html"
    with open(template_path, 'r', encoding='utf-8') as f:
        return f.read()


@router.get("/api/dashboard/settings")
async def get_settings():
    """대시보드 설정 조회"""
    return JSONResponse(load_settings())


@router.post("/api/dashboard/settings")
async def update_settings(settings: dict = Body(...)):
    """대시보드 설정 저장"""
    current = load_settings()
    current.update(settings)
    save_settings(current)
    return {"status": "ok"}


@router.get("/api/dashboard/playtime")
async def get_playtime_stats(
    period: str = Query("week"),
    offset: int = Query(0, description="기간 오프셋 (-1: 이전, 1: 다음)"),
    game_id: str = Query("all"),
    merge_names: bool = Query(True),
    show_unregistered: bool = Query(False)
):
    """기간별 플레이 시간 통계 API"""
    from src.data.database import SessionLocal
    db = SessionLocal()
    
    try:
        now = datetime.datetime.now()
        days = 7 if period == "week" else 30
        
        # 오프셋 적용
        if period == "week":
            start_date = now - datetime.timedelta(days=days + (-offset * 7))
        else:
            # 월간: 해당 월의 1일부터
            target_month = now.month + offset
            target_year = now.year
            while target_month < 1:
                target_month += 12
                target_year -= 1
            while target_month > 12:
                target_month -= 12
                target_year += 1
            start_date = datetime.datetime(target_year, target_month, 1)
            # 해당 월의 마지막 날 계산
            if target_month == 12:
                end_date = datetime.datetime(target_year + 1, 1, 1)
            else:
                end_date = datetime.datetime(target_year, target_month + 1, 1)
            days = (end_date - start_date).days
        
        start_timestamp = start_date.timestamp()
        dates = [(start_date + datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
        
        query = db.query(
            func.date(models.ProcessSession.start_timestamp, 'unixepoch', 'localtime').label('play_date'),
            models.ProcessSession.process_id,
            models.ProcessSession.process_name,
            func.sum(models.ProcessSession.session_duration).label('total_seconds')
        ).filter(
            models.ProcessSession.start_timestamp >= start_timestamp,
            models.ProcessSession.start_timestamp < start_timestamp + (days * 86400),
            models.ProcessSession.session_duration.isnot(None)
        )
        
        if game_id != "all":
            query = query.filter(models.ProcessSession.process_id == game_id)
        
        query = query.group_by('play_date', models.ProcessSession.process_id)
        results = query.all()
        
        # 등록된 게임 목록
        registered_names = set()
        process_ids = {}
        if not show_unregistered:
            processes = db.query(models.Process).all()
            registered_names = {p.name.lower() for p in processes}
            process_ids = {p.name.lower(): p.id for p in processes}
        
        games_data = {}
        for row in results:
            if not show_unregistered and row.process_name.lower() not in registered_names:
                continue
            
            key = row.process_name if merge_names else row.process_id
            
            if key not in games_data:
                games_data[key] = {
                    "name": row.process_name, 
                    "minutes": [0] * days,
                    "process_id": process_ids.get(row.process_name.lower(), row.process_id)
                }
            
            if row.play_date in dates:
                idx = dates.index(row.play_date)
                games_data[key]["minutes"][idx] += (row.total_seconds or 0) / 60
        
        # 통계 계산
        today_str = now.strftime("%Y-%m-%d")
        week_start = (now - datetime.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0)
        
        today_minutes = week_minutes = month_minutes = 0
        for i, ds in enumerate(dates):
            dt = datetime.datetime.strptime(ds, "%Y-%m-%d")
            day_total = sum(g["minutes"][i] for g in games_data.values())
            if ds == today_str: 
                today_minutes = day_total
            if dt >= week_start: 
                week_minutes += day_total
            if dt >= month_start: 
                month_minutes += day_total
        
        return {
            "dates": dates,
            "games": games_data,
            "stats": {
                "today_minutes": today_minutes, 
                "week_minutes": week_minutes, 
                "month_minutes": month_minutes
            }
        }
    finally:
        db.close()


@router.get("/api/dashboard/calendar")
async def get_calendar_data(
    year: int = Query(...),
    month: int = Query(...),
    threshold: int = Query(10),
    show_unregistered: bool = Query(False)
):
    """달력 데이터 API"""
    from src.data.database import SessionLocal
    db = SessionLocal()
    
    try:
        start_date = datetime.datetime(year, month + 1, 1)
        end_date = datetime.datetime(year + 1, 1, 1) if month == 11 else datetime.datetime(year, month + 2, 1)
        
        # 등록된 게임 목록
        registered_names = set()
        if not show_unregistered:
            processes = db.query(models.Process).all()
            registered_names = {p.name.lower() for p in processes}
        
        results = db.query(
            func.date(models.ProcessSession.start_timestamp, 'unixepoch', 'localtime').label('play_date'),
            models.ProcessSession.process_id,
            models.ProcessSession.process_name,
            func.sum(models.ProcessSession.session_duration).label('total_seconds')
        ).filter(
            models.ProcessSession.start_timestamp >= start_date.timestamp(),
            models.ProcessSession.start_timestamp < end_date.timestamp(),
            models.ProcessSession.session_duration.isnot(None)
        ).group_by('play_date', models.ProcessSession.process_name).all()
        
        days_data = {}
        for row in results:
            if not show_unregistered and row.process_name.lower() not in registered_names:
                continue
            
            total_min = (row.total_seconds or 0) / 60
            if total_min < threshold:
                continue
            
            if row.play_date not in days_data:
                days_data[row.play_date] = {"games": []}
            
            days_data[row.play_date]["games"].append({
                "id": row.process_id,
                "name": row.process_name,
                "minutes": total_min
            })
        
        return {"days": days_data}
    finally:
        db.close()


@router.get("/api/dashboard/icons/{process_id}")
async def get_game_icon(
    process_id: str,
    size: int = Query(default=64, ge=1, le=256, description="Icon size in pixels")
):
    """게임 아이콘 API - 동적 크기 지원"""
    from src.data.database import SessionLocal
    db = SessionLocal()

    try:
        process = db.query(models.Process).filter(models.Process.id == process_id).first()
        if not process:
            return Response(
                content=generate_fallback_svg("?", "#6366f1"),
                media_type="image/svg+xml"
            )

        name = process.name
        # monitoring_path 우선, launch_path 폴백
        exe_path = process.monitoring_path or process.launch_path

        # 요청된 크기에 맞는 캐시된 아이콘 확인
        icon_path = get_icon_for_size(process_id, size)
        if icon_path:
            return FileResponse(str(icon_path), media_type="image/png")

        # exe에서 아이콘 추출 시도
        if exe_path and os.path.exists(exe_path):
            extract_icon_from_exe(exe_path, process_id)
            icon_path = get_icon_for_size(process_id, size)
            if icon_path:
                return FileResponse(str(icon_path), media_type="image/png")

        # 폴백 SVG
        color = get_color_for_game(name)
        return Response(
            content=generate_fallback_svg(name, color),
            media_type="image/svg+xml"
        )
    finally:
        db.close()

