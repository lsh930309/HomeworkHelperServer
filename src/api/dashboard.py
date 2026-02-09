# dashboard.py
"""대시보드 API 및 HTML 렌더링 모듈"""

import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from src.data import models

router = APIRouter()


def get_dashboard_html() -> str:
    """대시보드 HTML 페이지를 반환합니다."""
    return '''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>숙제 관리자 - 대시보드</title>
    
    <!-- Satoshi 폰트 -->
    <link href="https://api.fontshare.com/v2/css?f[]=satoshi@400,500,700&display=swap" rel="stylesheet">
    
    <!-- Chart.js -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-adapter-date-fns@3.0.0"></script>
    
    <style>
        :root {
            --bg-primary: #ffffff;
            --bg-secondary: #f8f9fa;
            --bg-card: #ffffff;
            --text-primary: #1a1a2e;
            --text-secondary: #6c757d;
            --border-color: #e9ecef;
            --accent: #6366f1;
            --accent-light: #818cf8;
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
        }
        
        @media (prefers-color-scheme: dark) {
            :root {
                --bg-primary: #0f0f23;
                --bg-secondary: #1a1a2e;
                --bg-card: #16213e;
                --text-primary: #e9ecef;
                --text-secondary: #adb5bd;
                --border-color: #2d3748;
                --accent: #818cf8;
                --accent-light: #a5b4fc;
            }
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Satoshi', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }
        
        /* 고정 Toolbar */
        .toolbar {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            height: 60px;
            background: var(--bg-card);
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 24px;
            z-index: 100;
            backdrop-filter: blur(10px);
        }
        
        .toolbar-brand {
            font-weight: 700;
            font-size: 1.25rem;
            color: var(--accent);
        }
        
        .toolbar-tabs {
            display: flex;
            gap: 8px;
        }
        
        .tab-btn {
            padding: 8px 16px;
            border: none;
            background: transparent;
            color: var(--text-secondary);
            font-family: inherit;
            font-size: 0.9rem;
            font-weight: 500;
            cursor: pointer;
            border-radius: 8px;
            transition: all 0.2s;
        }
        
        .tab-btn:hover {
            background: var(--bg-secondary);
            color: var(--text-primary);
        }
        
        .tab-btn.active {
            background: var(--accent);
            color: white;
        }
        
        /* 메인 컨텐츠 */
        .main-content {
            flex: 1;
            margin-top: 60px;
            padding: 24px;
            display: flex;
            flex-direction: column;
            gap: 24px;
        }
        
        /* 탭 패널 */
        .tab-panel {
            display: none;
            flex: 1;
        }
        
        .tab-panel.active {
            display: flex;
            flex-direction: column;
            gap: 24px;
        }
        
        /* 카드 컴포넌트 */
        .card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 20px;
        }
        
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }
        
        .card-title {
            font-size: 1rem;
            font-weight: 600;
        }
        
        /* 필터 컨트롤 */
        .filter-controls {
            display: flex;
            gap: 12px;
            flex-wrap: wrap;
        }
        
        .filter-select {
            padding: 8px 12px;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            background: var(--bg-secondary);
            color: var(--text-primary);
            font-family: inherit;
            font-size: 0.85rem;
            cursor: pointer;
        }
        
        .filter-input {
            padding: 8px 12px;
            border: 1px solid var(--border-color);
            border-radius: 8px;
            background: var(--bg-secondary);
            color: var(--text-primary);
            font-family: inherit;
            font-size: 0.85rem;
            width: 100px;
        }
        
        /* 차트 컨테이너 */
        .chart-container {
            position: relative;
            height: 400px;
            width: 100%;
        }
        
        /* 달력 그리드 */
        .calendar-grid {
            display: grid;
            grid-template-columns: repeat(7, 1fr);
            gap: 4px;
        }
        
        .calendar-header {
            text-align: center;
            font-size: 0.8rem;
            font-weight: 600;
            color: var(--text-secondary);
            padding: 8px 0;
        }
        
        .calendar-day {
            aspect-ratio: 1;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: flex-start;
            padding: 4px;
            border-radius: 8px;
            background: var(--bg-secondary);
            font-size: 0.75rem;
            cursor: pointer;
            transition: all 0.2s;
            overflow: hidden;
        }
        
        .calendar-day:hover {
            border: 1px solid var(--accent);
        }
        
        .calendar-day.empty {
            background: transparent;
        }
        
        .calendar-day .date {
            font-weight: 500;
            margin-bottom: 2px;
        }
        
        .calendar-day .icons {
            display: flex;
            flex-wrap: wrap;
            gap: 2px;
            justify-content: center;
        }
        
        .calendar-day .icon {
            width: 16px;
            height: 16px;
            border-radius: 4px;
            object-fit: cover;
        }
        
        /* 월 네비게이션 */
        .month-nav {
            display: flex;
            align-items: center;
            gap: 16px;
        }
        
        .month-nav button {
            padding: 8px 12px;
            border: 1px solid var(--border-color);
            background: var(--bg-secondary);
            color: var(--text-primary);
            border-radius: 8px;
            cursor: pointer;
            font-family: inherit;
        }
        
        .month-nav button:hover {
            background: var(--accent);
            color: white;
            border-color: var(--accent);
        }
        
        .month-title {
            font-size: 1.1rem;
            font-weight: 600;
            min-width: 120px;
            text-align: center;
        }
        
        /* 통계 카드 그리드 */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
        }
        
        .stat-card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 16px;
        }
        
        .stat-label {
            font-size: 0.85rem;
            color: var(--text-secondary);
            margin-bottom: 4px;
        }
        
        .stat-value {
            font-size: 1.75rem;
            font-weight: 700;
            color: var(--accent);
        }
        
        .stat-unit {
            font-size: 0.85rem;
            color: var(--text-secondary);
            font-weight: 400;
        }
        
        /* 로딩 상태 */
        .loading {
            display: flex;
            align-items: center;
            justify-content: center;
            height: 200px;
            color: var(--text-secondary);
        }
        
        /* 반응형 */
        @media (max-width: 768px) {
            .toolbar {
                padding: 0 16px;
            }
            
            .toolbar-brand {
                font-size: 1rem;
            }
            
            .tab-btn {
                padding: 6px 12px;
                font-size: 0.8rem;
            }
            
            .main-content {
                padding: 16px;
            }
            
            .chart-container {
                height: 300px;
            }
        }
    </style>
</head>
<body>
    <!-- Toolbar -->
    <header class="toolbar">
        <div class="toolbar-brand">📊 숙제 관리자</div>
        <nav class="toolbar-tabs">
            <button class="tab-btn active" data-tab="playtime">플레이 시간</button>
            <button class="tab-btn" data-tab="calendar">달력</button>
        </nav>
    </header>
    
    <!-- Main Content -->
    <main class="main-content">
        <!-- 플레이 시간 탭 -->
        <section id="playtime" class="tab-panel active">
            <!-- 통계 요약 -->
            <div class="stats-grid" id="statsGrid">
                <div class="stat-card">
                    <div class="stat-label">오늘 플레이</div>
                    <div class="stat-value" id="statToday">-<span class="stat-unit">분</span></div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">이번 주 플레이</div>
                    <div class="stat-value" id="statWeek">-<span class="stat-unit">시간</span></div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">이번 달 플레이</div>
                    <div class="stat-value" id="statMonth">-<span class="stat-unit">시간</span></div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">등록된 게임</div>
                    <div class="stat-value" id="statGames">-<span class="stat-unit">개</span></div>
                </div>
            </div>
            
            <!-- 플레이 시간 차트 -->
            <div class="card">
                <div class="card-header">
                    <h2 class="card-title">기간별 플레이 시간</h2>
                    <div class="filter-controls">
                        <select class="filter-select" id="periodSelect">
                            <option value="week" selected>주간</option>
                            <option value="month">월간</option>
                        </select>
                        <select class="filter-select" id="gameFilter">
                            <option value="all">전체 게임</option>
                        </select>
                    </div>
                </div>
                <div class="chart-container">
                    <canvas id="playtimeChart"></canvas>
                </div>
            </div>
        </section>
        
        <!-- 달력 탭 -->
        <section id="calendar" class="tab-panel">
            <div class="card">
                <div class="card-header">
                    <h2 class="card-title">플레이 기록</h2>
                    <div class="filter-controls">
                        <label style="display: flex; align-items: center; gap: 8px;">
                            <span style="font-size: 0.85rem;">최소 플레이 시간:</span>
                            <input type="number" class="filter-input" id="thresholdInput" value="10" min="0">
                            <span style="font-size: 0.85rem;">분</span>
                        </label>
                    </div>
                </div>
                <div class="month-nav">
                    <button id="prevMonth">◀</button>
                    <span class="month-title" id="monthTitle">2026년 2월</span>
                    <button id="nextMonth">▶</button>
                </div>
                <div style="margin-top: 16px;">
                    <div class="calendar-grid" id="calendarGrid">
                        <div class="calendar-header">일</div>
                        <div class="calendar-header">월</div>
                        <div class="calendar-header">화</div>
                        <div class="calendar-header">수</div>
                        <div class="calendar-header">목</div>
                        <div class="calendar-header">금</div>
                        <div class="calendar-header">토</div>
                    </div>
                </div>
            </div>
        </section>
    </main>
    
    <script>
        // === 상태 관리 ===
        const state = {
            currentMonth: new Date().getMonth(),
            currentYear: new Date().getFullYear(),
            games: [],
            playtimeData: null,
            calendarData: null
        };
        
        // === API 호출 ===
        async function fetchAPI(endpoint) {
            try {
                const response = await fetch(endpoint);
                if (!response.ok) throw new Error('API 오류');
                return await response.json();
            } catch (error) {
                console.error('API 호출 실패:', error);
                return null;
            }
        }
        
        async function loadGames() {
            const games = await fetchAPI('/processes');
            if (games) {
                state.games = games;
                populateGameFilter();
                document.getElementById('statGames').innerHTML = `${games.length}<span class="stat-unit">개</span>`;
            }
        }
        
        async function loadPlaytimeData(period = 'week', gameId = 'all') {
            const data = await fetchAPI(`/api/dashboard/playtime?period=${period}&game_id=${gameId}`);
            if (data) {
                state.playtimeData = data;
                updatePlaytimeChart(data);
                updateStats(data);
            }
        }
        
        async function loadCalendarData(year, month, threshold = 10) {
            const data = await fetchAPI(`/api/dashboard/calendar?year=${year}&month=${month}&threshold=${threshold}`);
            if (data) {
                state.calendarData = data;
                renderCalendar(data, year, month);
            }
        }
        
        // === UI 업데이트 ===
        function populateGameFilter() {
            const select = document.getElementById('gameFilter');
            select.innerHTML = '<option value="all">전체 게임</option>';
            state.games.forEach(game => {
                const option = document.createElement('option');
                option.value = game.id;
                option.textContent = game.name;
                select.appendChild(option);
            });
        }
        
        function updateStats(data) {
            if (data.stats) {
                const todayMinutes = Math.round(data.stats.today_minutes || 0);
                const weekHours = (data.stats.week_minutes || 0) / 60;
                const monthHours = (data.stats.month_minutes || 0) / 60;
                
                document.getElementById('statToday').innerHTML = 
                    `${todayMinutes}<span class="stat-unit">분</span>`;
                document.getElementById('statWeek').innerHTML = 
                    `${weekHours.toFixed(1)}<span class="stat-unit">시간</span>`;
                document.getElementById('statMonth').innerHTML = 
                    `${monthHours.toFixed(1)}<span class="stat-unit">시간</span>`;
            }
        }
        
        // === 차트 ===
        let playtimeChart = null;
        
        function updatePlaytimeChart(data) {
            const ctx = document.getElementById('playtimeChart').getContext('2d');
            
            if (playtimeChart) {
                playtimeChart.destroy();
            }
            
            const datasets = [];
            const colors = [
                '#6366f1', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6',
                '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#14b8a6'
            ];
            
            let colorIndex = 0;
            for (const [gameId, gameData] of Object.entries(data.games || {})) {
                const color = colors[colorIndex % colors.length];
                datasets.push({
                    label: gameData.name,
                    data: data.dates.map((date, i) => ({
                        x: date,
                        y: (gameData.minutes[i] || 0) / 60
                    })),
                    backgroundColor: color + '80',
                    borderColor: color,
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3
                });
                colorIndex++;
            }
            
            const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            const gridColor = isDark ? '#2d3748' : '#e9ecef';
            const textColor = isDark ? '#adb5bd' : '#6c757d';
            
            playtimeChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: data.dates,
                    datasets: datasets
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: {
                        intersect: false,
                        mode: 'index'
                    },
                    plugins: {
                        legend: {
                            position: 'top',
                            labels: { color: textColor }
                        },
                        tooltip: {
                            callbacks: {
                                label: (ctx) => `${ctx.dataset.label}: ${ctx.parsed.y.toFixed(1)}시간`
                            }
                        }
                    },
                    scales: {
                        x: {
                            stacked: true,
                            grid: { color: gridColor },
                            ticks: { color: textColor }
                        },
                        y: {
                            stacked: true,
                            beginAtZero: true,
                            grid: { color: gridColor },
                            ticks: { 
                                color: textColor,
                                callback: (value) => value + '시간'
                            }
                        }
                    }
                }
            });
        }
        
        // === 달력 ===
        function renderCalendar(data, year, month) {
            document.getElementById('monthTitle').textContent = `${year}년 ${month + 1}월`;
            
            const grid = document.getElementById('calendarGrid');
            // 헤더 유지하고 날짜 셀만 제거
            const headers = grid.querySelectorAll('.calendar-header');
            grid.innerHTML = '';
            headers.forEach(h => grid.appendChild(h));
            
            const firstDay = new Date(year, month, 1).getDay();
            const daysInMonth = new Date(year, month + 1, 0).getDate();
            
            // 빈 셀 추가
            for (let i = 0; i < firstDay; i++) {
                const emptyCell = document.createElement('div');
                emptyCell.className = 'calendar-day empty';
                grid.appendChild(emptyCell);
            }
            
            // 날짜 셀 추가
            for (let day = 1; day <= daysInMonth; day++) {
                const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
                const dayData = data.days ? data.days[dateStr] : null;
                
                const cell = document.createElement('div');
                cell.className = 'calendar-day';
                
                let iconsHtml = '';
                if (dayData && dayData.games) {
                    iconsHtml = dayData.games.map(g => 
                        `<img class="icon" src="/api/dashboard/icons/${g.id}" alt="${g.name}" title="${g.name}: ${Math.round(g.minutes)}분">`
                    ).join('');
                }
                
                cell.innerHTML = `
                    <span class="date">${day}</span>
                    <div class="icons">${iconsHtml}</div>
                `;
                grid.appendChild(cell);
            }
        }
        
        // === 이벤트 핸들러 ===
        function initEventHandlers() {
            // 탭 전환
            document.querySelectorAll('.tab-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
                    
                    btn.classList.add('active');
                    document.getElementById(btn.dataset.tab).classList.add('active');
                    
                    if (btn.dataset.tab === 'calendar' && !state.calendarData) {
                        loadCalendarData(state.currentYear, state.currentMonth);
                    }
                });
            });
            
            // 기간 선택
            document.getElementById('periodSelect').addEventListener('change', (e) => {
                const gameId = document.getElementById('gameFilter').value;
                loadPlaytimeData(e.target.value, gameId);
            });
            
            // 게임 필터
            document.getElementById('gameFilter').addEventListener('change', (e) => {
                const period = document.getElementById('periodSelect').value;
                loadPlaytimeData(period, e.target.value);
            });
            
            // 월 이동
            document.getElementById('prevMonth').addEventListener('click', () => {
                state.currentMonth--;
                if (state.currentMonth < 0) {
                    state.currentMonth = 11;
                    state.currentYear--;
                }
                const threshold = document.getElementById('thresholdInput').value;
                loadCalendarData(state.currentYear, state.currentMonth, threshold);
            });
            
            document.getElementById('nextMonth').addEventListener('click', () => {
                state.currentMonth++;
                if (state.currentMonth > 11) {
                    state.currentMonth = 0;
                    state.currentYear++;
                }
                const threshold = document.getElementById('thresholdInput').value;
                loadCalendarData(state.currentYear, state.currentMonth, threshold);
            });
            
            // Threshold 변경
            document.getElementById('thresholdInput').addEventListener('change', (e) => {
                loadCalendarData(state.currentYear, state.currentMonth, e.target.value);
            });
        }
        
        // === 초기화 ===
        async function init() {
            initEventHandlers();
            await loadGames();
            await loadPlaytimeData();
        }
        
        init();
    </script>
</body>
</html>'''


@router.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard():
    """대시보드 HTML 페이지 반환"""
    return get_dashboard_html()


@router.get("/api/dashboard/playtime")
async def get_playtime_stats(
    period: str = Query("week", description="기간: week, month"),
    game_id: str = Query("all", description="게임 ID 또는 'all'"),
    db: Session = Depends(lambda: None)  # 실제 사용 시 get_db로 교체
):
    """기간별 플레이 시간 통계 API"""
    from src.data.database import SessionLocal
    db = SessionLocal()
    
    try:
        now = datetime.datetime.now()
        
        # 기간 계산
        if period == "week":
            days = 7
        else:  # month
            days = 30
        
        start_date = now - datetime.timedelta(days=days)
        start_timestamp = start_date.timestamp()
        
        # 날짜 목록 생성
        dates = []
        for i in range(days):
            date = start_date + datetime.timedelta(days=i)
            dates.append(date.strftime("%Y-%m-%d"))
        
        # 게임별 플레이 시간 쿼리
        query = db.query(
            func.date(models.ProcessSession.start_timestamp, 'unixepoch', 'localtime').label('play_date'),
            models.ProcessSession.process_id,
            models.ProcessSession.process_name,
            func.sum(models.ProcessSession.session_duration).label('total_seconds')
        ).filter(
            models.ProcessSession.start_timestamp >= start_timestamp,
            models.ProcessSession.session_duration.isnot(None)
        )
        
        if game_id != "all":
            query = query.filter(models.ProcessSession.process_id == game_id)
        
        query = query.group_by('play_date', models.ProcessSession.process_id)
        results = query.all()
        
        # 결과 정리
        games_data = {}
        for row in results:
            game_id_key = row.process_id
            if game_id_key not in games_data:
                games_data[game_id_key] = {
                    "name": row.process_name,
                    "minutes": [0] * days
                }
            
            if row.play_date in dates:
                idx = dates.index(row.play_date)
                games_data[game_id_key]["minutes"][idx] = (row.total_seconds or 0) / 60
        
        # 통계 계산
        today_str = now.strftime("%Y-%m-%d")
        week_start = (now - datetime.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0)
        
        today_minutes = 0
        week_minutes = 0
        month_minutes = 0
        
        for i, date_str in enumerate(dates):
            date = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            day_total = sum(g["minutes"][i] for g in games_data.values())
            
            if date_str == today_str:
                today_minutes = day_total
            if date >= week_start:
                week_minutes += day_total
            if date >= month_start:
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
    year: int = Query(..., description="년도"),
    month: int = Query(..., description="월 (0-11)"),
    threshold: int = Query(10, description="최소 플레이 시간 (분)"),
    db: Session = Depends(lambda: None)
):
    """달력 데이터 API"""
    from src.data.database import SessionLocal
    db = SessionLocal()
    
    try:
        # 월의 시작과 끝 타임스탬프
        start_date = datetime.datetime(year, month + 1, 1)
        if month == 11:
            end_date = datetime.datetime(year + 1, 1, 1)
        else:
            end_date = datetime.datetime(year, month + 2, 1)
        
        start_ts = start_date.timestamp()
        end_ts = end_date.timestamp()
        threshold_seconds = threshold * 60
        
        # 일별 게임별 플레이 시간 쿼리
        results = db.query(
            func.date(models.ProcessSession.start_timestamp, 'unixepoch', 'localtime').label('play_date'),
            models.ProcessSession.process_id,
            models.ProcessSession.process_name,
            func.sum(models.ProcessSession.session_duration).label('total_seconds')
        ).filter(
            models.ProcessSession.start_timestamp >= start_ts,
            models.ProcessSession.start_timestamp < end_ts,
            models.ProcessSession.session_duration.isnot(None)
        ).group_by('play_date', models.ProcessSession.process_id).all()
        
        # 결과 정리
        days_data = {}
        for row in results:
            total_minutes = (row.total_seconds or 0) / 60
            if total_minutes < threshold:
                continue
            
            if row.play_date not in days_data:
                days_data[row.play_date] = {"games": []}
            
            days_data[row.play_date]["games"].append({
                "id": row.process_id,
                "name": row.process_name,
                "minutes": total_minutes
            })
        
        return {"days": days_data}
    finally:
        db.close()


@router.get("/api/dashboard/icons/{process_id}")
async def get_game_icon(process_id: str):
    """게임 아이콘 이미지 반환"""
    from fastapi.responses import FileResponse
    from src.data.database import SessionLocal
    import os
    
    db = SessionLocal()
    try:
        # 프로세스 정보에서 monitoring_path 가져오기
        process = db.query(models.Process).filter(models.Process.id == process_id).first()
        if not process or not process.monitoring_path:
            # 기본 아이콘 반환 또는 404
            return {"error": "프로세스를 찾을 수 없습니다."}
        
        # 파일 경로에서 아이콘 추출은 복잡하므로 간단한 placeholder 반환
        # 실제 구현 시 win32api를 사용하여 exe 아이콘 추출 필요
        
        # 아이콘 캐시 디렉토리
        app_data = os.getenv('APPDATA', os.path.expanduser('~'))
        icon_cache_dir = os.path.join(app_data, 'HomeworkHelper', 'icon_cache')
        os.makedirs(icon_cache_dir, exist_ok=True)
        
        icon_path = os.path.join(icon_cache_dir, f"{process_id}.png")
        
        if os.path.exists(icon_path):
            return FileResponse(icon_path, media_type="image/png")
        
        # 아이콘이 없으면 SVG placeholder 반환
        from fastapi.responses import Response
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">
            <rect width="32" height="32" rx="4" fill="#6366f1"/>
            <text x="16" y="20" text-anchor="middle" fill="white" font-size="14" font-family="Arial">{process.name[0].upper() if process.name else "?"}</text>
        </svg>'''
        return Response(content=svg, media_type="image/svg+xml")
    finally:
        db.close()
