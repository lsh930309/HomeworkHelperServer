# dashboard.py
"""대시보드 API 및 HTML 렌더링 모듈 v2"""

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
    
    <style>
        /* === 테마 변수 === */
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
        
        [data-theme="dark"] {
            --bg-primary: #0f0f23;
            --bg-secondary: #1a1a2e;
            --bg-card: #16213e;
            --text-primary: #e9ecef;
            --text-secondary: #adb5bd;
            --border-color: #2d3748;
            --accent: #818cf8;
            --accent-light: #a5b4fc;
        }
        
        @media (prefers-color-scheme: dark) {
            :root:not([data-theme="light"]) {
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
        
        * { margin: 0; padding: 0; box-sizing: border-box; }
        
        html, body {
            height: 100%;
            overflow: hidden;
        }
        
        body {
            font-family: 'Satoshi', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            display: flex;
            flex-direction: column;
        }
        
        /* === Toolbar 스타일 (위치 설정 가능) === */
        .toolbar {
            height: 56px;
            background: var(--bg-card);
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 20px;
            z-index: 100;
            flex-shrink: 0;
            transition: all 0.3s ease;
        }
        
        /* 플로팅 스타일 */
        body[data-toolbar="floating-top"] .toolbar,
        body[data-toolbar="floating-bottom"] .toolbar {
            position: fixed;
            left: 20px;
            right: 20px;
            border-radius: 16px;
            border: 1px solid var(--border-color);
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
        }
        body[data-toolbar="floating-top"] .toolbar { top: 16px; }
        body[data-toolbar="floating-bottom"] .toolbar { bottom: 16px; top: auto; }
        body[data-toolbar="floating-top"] .main-content { padding-top: 88px; }
        body[data-toolbar="floating-bottom"] .main-content { padding-bottom: 88px; }
        body[data-toolbar="bottom"] { flex-direction: column-reverse; }
        body[data-toolbar="bottom"] .toolbar { border-bottom: none; border-top: 1px solid var(--border-color); }
        
        .toolbar-brand {
            font-weight: 700;
            font-size: 1.1rem;
            color: var(--accent);
            display: flex;
            align-items: center;
            gap: 8px;
        }
        
        /* === 탭 버튼 (슬라이딩 indicator) === */
        .toolbar-tabs {
            display: flex;
            gap: 4px;
            background: var(--bg-secondary);
            padding: 4px;
            border-radius: 12px;
            position: relative;
        }
        
        .tab-indicator {
            position: absolute;
            height: calc(100% - 8px);
            background: var(--accent);
            border-radius: 8px;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            z-index: 0;
        }
        
        .tab-btn {
            padding: 8px 20px;
            border: none;
            background: transparent;
            color: var(--text-secondary);
            font-family: inherit;
            font-size: 0.9rem;
            font-weight: 500;
            cursor: pointer;
            border-radius: 8px;
            transition: color 0.2s;
            position: relative;
            z-index: 1;
        }
        
        .tab-btn.active { color: white; }
        .tab-btn:not(.active):hover { color: var(--text-primary); }
        
        /* === 설정 버튼 === */
        .toolbar-actions {
            display: flex;
            gap: 8px;
            align-items: center;
        }
        
        .icon-btn {
            width: 36px;
            height: 36px;
            border: 1px solid var(--border-color);
            background: var(--bg-secondary);
            border-radius: 8px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.1rem;
            transition: all 0.2s;
        }
        
        .icon-btn:hover {
            background: var(--accent);
            color: white;
            border-color: var(--accent);
        }
        
        /* === 메인 컨텐츠 === */
        .main-content {
            flex: 1;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 16px;
            overflow: auto;
        }
        
        /* === 탭 패널 === */
        .tab-panel {
            display: none;
            flex: 1;
            min-height: 0;
        }
        
        .tab-panel.active {
            display: flex;
            flex-direction: column;
            gap: 16px;
            animation: fadeIn 0.3s ease;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        /* === 카드 === */
        .card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 16px;
        }
        
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
            flex-wrap: wrap;
            gap: 12px;
        }
        
        .card-title { font-size: 1rem; font-weight: 600; }
        
        /* === 필터 컨트롤 === */
        .filter-controls {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            align-items: center;
        }
        
        .filter-select, .filter-input {
            padding: 6px 10px;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            background: var(--bg-secondary);
            color: var(--text-primary);
            font-family: inherit;
            font-size: 0.8rem;
        }
        
        .filter-input { width: 60px; }
        
        .filter-label {
            font-size: 0.8rem;
            color: var(--text-secondary);
        }
        
        /* === 통계 카드 그리드 === */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
        }
        
        @media (max-width: 900px) { .stats-grid { grid-template-columns: repeat(2, 1fr); } }
        @media (max-width: 500px) { .stats-grid { grid-template-columns: 1fr; } }
        
        .stat-card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 12px 16px;
        }
        
        .stat-label { font-size: 0.75rem; color: var(--text-secondary); margin-bottom: 2px; }
        .stat-value { font-size: 1.5rem; font-weight: 700; color: var(--accent); }
        .stat-unit { font-size: 0.75rem; color: var(--text-secondary); font-weight: 400; }
        
        /* === 차트 컨테이너 === */
        .chart-container {
            position: relative;
            flex: 1;
            min-height: 250px;
        }
        
        /* === 달력 === */
        .calendar-wrapper {
            flex: 1;
            display: flex;
            flex-direction: column;
            min-height: 0;
        }
        
        .calendar-grid {
            display: grid;
            grid-template-columns: repeat(7, 1fr);
            gap: 3px;
            flex: 1;
        }
        
        .calendar-header {
            text-align: center;
            font-size: 0.7rem;
            font-weight: 600;
            color: var(--text-secondary);
            padding: 4px 0;
        }
        
        .calendar-day {
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 4px 2px;
            border-radius: 6px;
            background: var(--bg-secondary);
            font-size: 0.7rem;
            cursor: pointer;
            transition: all 0.2s;
            min-height: 50px;
        }
        
        .calendar-day:hover { border: 1px solid var(--accent); }
        .calendar-day.empty { background: transparent; pointer-events: none; }
        .calendar-day .date { font-weight: 600; margin-bottom: 2px; font-size: 0.75rem; }
        
        .calendar-day .icons {
            display: flex;
            flex-wrap: wrap;
            gap: 2px;
            justify-content: center;
            flex: 1;
            align-items: flex-start;
        }
        
        .calendar-day .icon {
            width: 22px;
            height: 22px;
            border-radius: 4px;
            object-fit: cover;
            background: var(--bg-card);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.65rem;
            font-weight: 600;
        }
        
        /* === 월 네비게이션 === */
        .month-nav {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 12px;
        }
        
        .month-nav button {
            padding: 6px 12px;
            border: 1px solid var(--border-color);
            background: var(--bg-secondary);
            color: var(--text-primary);
            border-radius: 6px;
            cursor: pointer;
            font-family: inherit;
            font-size: 0.85rem;
        }
        
        .month-nav button:hover { background: var(--accent); color: white; border-color: var(--accent); }
        .month-title { font-size: 1rem; font-weight: 600; }
        
        /* === 설정 모달 === */
        .modal-overlay {
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.5);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 200;
            opacity: 0;
            visibility: hidden;
            transition: all 0.2s;
        }
        
        .modal-overlay.active { opacity: 1; visibility: visible; }
        
        .modal {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 24px;
            min-width: 320px;
            max-width: 90%;
            transform: scale(0.9);
            transition: transform 0.2s;
        }
        
        .modal-overlay.active .modal { transform: scale(1); }
        
        .modal-title { font-size: 1.1rem; font-weight: 600; margin-bottom: 16px; }
        
        .setting-group {
            margin-bottom: 16px;
        }
        
        .setting-label {
            font-size: 0.85rem;
            color: var(--text-secondary);
            margin-bottom: 6px;
            display: block;
        }
        
        .setting-options {
            display: flex;
            gap: 6px;
            flex-wrap: wrap;
        }
        
        .setting-btn {
            padding: 8px 14px;
            border: 1px solid var(--border-color);
            background: var(--bg-secondary);
            color: var(--text-primary);
            border-radius: 8px;
            cursor: pointer;
            font-family: inherit;
            font-size: 0.85rem;
            transition: all 0.2s;
        }
        
        .setting-btn:hover { border-color: var(--accent); }
        .setting-btn.active { background: var(--accent); color: white; border-color: var(--accent); }
        
        .modal-close {
            margin-top: 16px;
            width: 100%;
            padding: 10px;
            border: none;
            background: var(--accent);
            color: white;
            border-radius: 8px;
            cursor: pointer;
            font-family: inherit;
            font-size: 0.9rem;
            font-weight: 500;
        }
        
        .modal-close:hover { background: var(--accent-light); }
    </style>
</head>
<body data-toolbar="top">
    <!-- Toolbar -->
    <header class="toolbar">
        <div class="toolbar-brand">📊 대시보드</div>
        <nav class="toolbar-tabs">
            <div class="tab-indicator" id="tabIndicator"></div>
            <button class="tab-btn active" data-tab="playtime">📈 플레이 시간</button>
            <button class="tab-btn" data-tab="calendar">📅 달력</button>
        </nav>
        <div class="toolbar-actions">
            <button class="icon-btn" id="settingsBtn" title="설정">⚙️</button>
        </div>
    </header>
    
    <!-- Main Content -->
    <main class="main-content">
        <!-- 플레이 시간 탭 -->
        <section id="playtime" class="tab-panel active">
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-label">오늘</div>
                    <div class="stat-value" id="statToday">-<span class="stat-unit">분</span></div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">이번 주</div>
                    <div class="stat-value" id="statWeek">-<span class="stat-unit">시간</span></div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">이번 달</div>
                    <div class="stat-value" id="statMonth">-<span class="stat-unit">시간</span></div>
                </div>
                <div class="stat-card">
                    <div class="stat-label">등록 게임</div>
                    <div class="stat-value" id="statGames">-<span class="stat-unit">개</span></div>
                </div>
            </div>
            
            <div class="card" style="flex:1; display:flex; flex-direction:column;">
                <div class="card-header">
                    <h2 class="card-title">기간별 플레이 시간</h2>
                    <div class="filter-controls">
                        <select class="filter-select" id="periodSelect">
                            <option value="week">주간</option>
                            <option value="month">월간</option>
                        </select>
                        <select class="filter-select" id="gameFilter">
                            <option value="all">전체 게임</option>
                        </select>
                        <select class="filter-select" id="chartTypeSelect">
                            <option value="bar">막대</option>
                            <option value="line">선형</option>
                        </select>
                        <select class="filter-select" id="stackModeSelect">
                            <option value="stacked">누적</option>
                            <option value="grouped">개별</option>
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
            <div class="card calendar-wrapper">
                <div class="card-header">
                    <div class="month-nav">
                        <button id="prevMonth">◀</button>
                        <span class="month-title" id="monthTitle">2026년 2월</span>
                        <button id="nextMonth">▶</button>
                    </div>
                    <div class="filter-controls">
                        <span class="filter-label">최소</span>
                        <input type="number" class="filter-input" id="thresholdInput" value="10" min="0">
                        <span class="filter-label">분</span>
                    </div>
                </div>
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
        </section>
    </main>
    
    <!-- 설정 모달 -->
    <div class="modal-overlay" id="settingsModal">
        <div class="modal">
            <h3 class="modal-title">⚙️ 설정</h3>
            
            <div class="setting-group">
                <label class="setting-label">테마</label>
                <div class="setting-options" id="themeOptions">
                    <button class="setting-btn active" data-value="auto">자동</button>
                    <button class="setting-btn" data-value="light">라이트</button>
                    <button class="setting-btn" data-value="dark">다크</button>
                </div>
            </div>
            
            <div class="setting-group">
                <label class="setting-label">툴바 위치</label>
                <div class="setting-options" id="toolbarOptions">
                    <button class="setting-btn active" data-value="top">상단</button>
                    <button class="setting-btn" data-value="bottom">하단</button>
                    <button class="setting-btn" data-value="floating-top">플로팅(상단)</button>
                    <button class="setting-btn" data-value="floating-bottom">플로팅(하단)</button>
                </div>
            </div>
            
            <button class="modal-close" id="closeSettings">닫기</button>
        </div>
    </div>
    
    <script>
        // === 상태 ===
        const state = {
            currentMonth: new Date().getMonth(),
            currentYear: new Date().getFullYear(),
            games: [],
            registeredGameNames: new Set(),
            playtimeData: null,
            calendarData: null,
            settings: {
                theme: localStorage.getItem('dashboard_theme') || 'auto',
                toolbar: localStorage.getItem('dashboard_toolbar') || 'top',
                chartType: localStorage.getItem('dashboard_chartType') || 'bar',
                stackMode: localStorage.getItem('dashboard_stackMode') || 'stacked'
            }
        };
        
        // === 테마 적용 ===
        function applyTheme(theme) {
            if (theme === 'auto') {
                document.documentElement.removeAttribute('data-theme');
            } else {
                document.documentElement.setAttribute('data-theme', theme);
            }
            localStorage.setItem('dashboard_theme', theme);
            state.settings.theme = theme;
            if (state.playtimeData) updatePlaytimeChart(state.playtimeData);
        }
        
        function applyToolbar(position) {
            document.body.setAttribute('data-toolbar', position);
            localStorage.setItem('dashboard_toolbar', position);
            state.settings.toolbar = position;
        }
        
        // === 탭 indicator 업데이트 ===
        function updateTabIndicator() {
            const activeTab = document.querySelector('.tab-btn.active');
            const indicator = document.getElementById('tabIndicator');
            if (activeTab && indicator) {
                indicator.style.width = activeTab.offsetWidth + 'px';
                indicator.style.left = activeTab.offsetLeft + 'px';
            }
        }
        
        // === API ===
        async function fetchAPI(endpoint) {
            try {
                const res = await fetch(endpoint);
                if (!res.ok) throw new Error('API 오류');
                return await res.json();
            } catch (e) {
                console.error('API 실패:', e);
                return null;
            }
        }
        
        async function loadGames() {
            const games = await fetchAPI('/processes');
            if (games) {
                state.games = games;
                state.registeredGameNames = new Set(games.map(g => g.name.toLowerCase()));
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
        
        // === UI ===
        function populateGameFilter() {
            const select = document.getElementById('gameFilter');
            select.innerHTML = '<option value="all">전체 게임</option>';
            state.games.forEach(g => {
                const opt = document.createElement('option');
                opt.value = g.id;
                opt.textContent = g.name;
                select.appendChild(opt);
            });
        }
        
        function updateStats(data) {
            if (data.stats) {
                const today = Math.round(data.stats.today_minutes || 0);
                const week = (data.stats.week_minutes || 0) / 60;
                const month = (data.stats.month_minutes || 0) / 60;
                document.getElementById('statToday').innerHTML = `${today}<span class="stat-unit">분</span>`;
                document.getElementById('statWeek').innerHTML = `${week.toFixed(1)}<span class="stat-unit">시간</span>`;
                document.getElementById('statMonth').innerHTML = `${month.toFixed(1)}<span class="stat-unit">시간</span>`;
            }
        }
        
        // === 차트 ===
        let playtimeChart = null;
        
        function updatePlaytimeChart(data) {
            const ctx = document.getElementById('playtimeChart').getContext('2d');
            if (playtimeChart) playtimeChart.destroy();
            
            const chartType = document.getElementById('chartTypeSelect').value;
            const stackMode = document.getElementById('stackModeSelect').value;
            const period = document.getElementById('periodSelect').value;
            
            const colors = ['#6366f1','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#06b6d4','#84cc16','#f97316','#14b8a6'];
            const datasets = [];
            let colorIdx = 0;
            
            for (const [gid, gdata] of Object.entries(data.games || {})) {
                const color = colors[colorIdx++ % colors.length];
                datasets.push({
                    label: gdata.name,
                    data: gdata.minutes.map(m => m / 60),
                    backgroundColor: chartType === 'bar' ? color + '99' : color + '33',
                    borderColor: color,
                    borderWidth: 2,
                    fill: chartType === 'line' && stackMode === 'stacked',
                    tension: 0.4,
                    pointRadius: chartType === 'line' ? 3 : 0
                });
            }
            
            const isDark = getComputedStyle(document.documentElement).getPropertyValue('--bg-primary').trim() === '#0f0f23';
            const gridColor = isDark ? '#2d3748' : '#e9ecef';
            const textColor = isDark ? '#adb5bd' : '#6c757d';
            
            // 날짜 레이블 포맷 (월간: M-D, 주간: M-D)
            const labels = data.dates.map(d => {
                const parts = d.split('-');
                return `${parseInt(parts[1])}/${parseInt(parts[2])}`;
            });
            
            playtimeChart = new Chart(ctx, {
                type: chartType,
                data: { labels, datasets },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { intersect: false, mode: 'index' },
                    plugins: {
                        legend: { position: 'top', labels: { color: textColor, boxWidth: 12, padding: 8 } },
                        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(1)}시간` } }
                    },
                    scales: {
                        x: {
                            stacked: stackMode === 'stacked',
                            grid: { color: gridColor },
                            ticks: { color: textColor, font: { size: 10 } }
                        },
                        y: {
                            stacked: stackMode === 'stacked',
                            beginAtZero: true,
                            grid: { color: gridColor },
                            ticks: { color: textColor, callback: v => v + 'h' }
                        }
                    }
                }
            });
        }
        
        // === 달력 ===
        function renderCalendar(data, year, month) {
            document.getElementById('monthTitle').textContent = `${year}년 ${month + 1}월`;
            
            const grid = document.getElementById('calendarGrid');
            const headers = grid.querySelectorAll('.calendar-header');
            grid.innerHTML = '';
            headers.forEach(h => grid.appendChild(h));
            
            const firstDay = new Date(year, month, 1).getDay();
            const daysInMonth = new Date(year, month + 1, 0).getDate();
            
            // 빈 셀
            for (let i = 0; i < firstDay; i++) {
                const empty = document.createElement('div');
                empty.className = 'calendar-day empty';
                grid.appendChild(empty);
            }
            
            // 날짜 셀
            for (let day = 1; day <= daysInMonth; day++) {
                const dateStr = `${year}-${String(month+1).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
                const dayData = data.days?.[dateStr];
                
                const cell = document.createElement('div');
                cell.className = 'calendar-day';
                
                let iconsHtml = '';
                if (dayData?.games) {
                    // 등록된 게임만 표시 (이름 매칭)
                    const validGames = dayData.games.filter(g => {
                        // ID로 등록된 게임 찾기 또는 이름 매칭
                        const registered = state.games.find(rg => rg.id === g.id);
                        if (registered) return true;
                        // 이름 매칭 (대소문자 무시)
                        return state.registeredGameNames.has(g.name.toLowerCase());
                    });
                    
                    iconsHtml = validGames.slice(0, 4).map(g => {
                        const initial = g.name.charAt(0).toUpperCase();
                        return `<div class="icon" title="${g.name}: ${Math.round(g.minutes)}분" style="background:${getColorForName(g.name)};color:white;">${initial}</div>`;
                    }).join('');
                    
                    if (validGames.length > 4) {
                        iconsHtml += `<div class="icon" style="background:var(--text-secondary);color:white;">+${validGames.length-4}</div>`;
                    }
                }
                
                cell.innerHTML = `<span class="date">${day}</span><div class="icons">${iconsHtml}</div>`;
                grid.appendChild(cell);
            }
        }
        
        function getColorForName(name) {
            const colors = ['#6366f1','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899'];
            let hash = 0;
            for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
            return colors[Math.abs(hash) % colors.length];
        }
        
        // === 이벤트 ===
        function initEvents() {
            // 탭 전환
            document.querySelectorAll('.tab-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
                    btn.classList.add('active');
                    document.getElementById(btn.dataset.tab).classList.add('active');
                    updateTabIndicator();
                    if (btn.dataset.tab === 'calendar' && !state.calendarData) {
                        loadCalendarData(state.currentYear, state.currentMonth);
                    }
                });
            });
            
            // 차트 필터
            ['periodSelect','gameFilter','chartTypeSelect','stackModeSelect'].forEach(id => {
                document.getElementById(id).addEventListener('change', () => {
                    const period = document.getElementById('periodSelect').value;
                    const gameId = document.getElementById('gameFilter').value;
                    loadPlaytimeData(period, gameId);
                });
            });
            
            // 월 이동
            document.getElementById('prevMonth').addEventListener('click', () => {
                state.currentMonth--;
                if (state.currentMonth < 0) { state.currentMonth = 11; state.currentYear--; }
                loadCalendarData(state.currentYear, state.currentMonth, document.getElementById('thresholdInput').value);
            });
            document.getElementById('nextMonth').addEventListener('click', () => {
                state.currentMonth++;
                if (state.currentMonth > 11) { state.currentMonth = 0; state.currentYear++; }
                loadCalendarData(state.currentYear, state.currentMonth, document.getElementById('thresholdInput').value);
            });
            document.getElementById('thresholdInput').addEventListener('change', e => {
                loadCalendarData(state.currentYear, state.currentMonth, e.target.value);
            });
            
            // 설정 모달
            document.getElementById('settingsBtn').addEventListener('click', () => {
                document.getElementById('settingsModal').classList.add('active');
            });
            document.getElementById('closeSettings').addEventListener('click', () => {
                document.getElementById('settingsModal').classList.remove('active');
            });
            document.getElementById('settingsModal').addEventListener('click', e => {
                if (e.target.id === 'settingsModal') e.target.classList.remove('active');
            });
            
            // 테마 옵션
            document.querySelectorAll('#themeOptions .setting-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    document.querySelectorAll('#themeOptions .setting-btn').forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    applyTheme(btn.dataset.value);
                });
            });
            
            // 툴바 옵션
            document.querySelectorAll('#toolbarOptions .setting-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    document.querySelectorAll('#toolbarOptions .setting-btn').forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    applyToolbar(btn.dataset.value);
                });
            });
            
            // 창 리사이즈 시 indicator 업데이트
            window.addEventListener('resize', updateTabIndicator);
        }
        
        // === 초기화 ===
        async function init() {
            // 저장된 설정 적용
            applyTheme(state.settings.theme);
            applyToolbar(state.settings.toolbar);
            document.getElementById('chartTypeSelect').value = state.settings.chartType;
            document.getElementById('stackModeSelect').value = state.settings.stackMode;
            
            // 설정 UI 활성화
            document.querySelector(`#themeOptions [data-value="${state.settings.theme}"]`)?.classList.add('active');
            document.querySelector(`#toolbarOptions [data-value="${state.settings.toolbar}"]`)?.classList.add('active');
            
            initEvents();
            await loadGames();
            await loadPlaytimeData();
            
            // 탭 indicator 초기화
            requestAnimationFrame(updateTabIndicator);
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
    db: Session = Depends(lambda: None)
):
    """기간별 플레이 시간 통계 API"""
    from src.data.database import SessionLocal
    db = SessionLocal()
    
    try:
        now = datetime.datetime.now()
        days = 7 if period == "week" else 30
        
        start_date = now - datetime.timedelta(days=days)
        start_timestamp = start_date.timestamp()
        
        dates = [(start_date + datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(days)]
        
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
        
        games_data = {}
        for row in results:
            gid = row.process_id
            if gid not in games_data:
                games_data[gid] = {"name": row.process_name, "minutes": [0] * days}
            if row.play_date in dates:
                idx = dates.index(row.play_date)
                games_data[gid]["minutes"][idx] = (row.total_seconds or 0) / 60
        
        today_str = now.strftime("%Y-%m-%d")
        week_start = (now - datetime.timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0)
        
        today_minutes = week_minutes = month_minutes = 0
        for i, ds in enumerate(dates):
            dt = datetime.datetime.strptime(ds, "%Y-%m-%d")
            day_total = sum(g["minutes"][i] for g in games_data.values())
            if ds == today_str: today_minutes = day_total
            if dt >= week_start: week_minutes += day_total
            if dt >= month_start: month_minutes += day_total
        
        return {
            "dates": dates,
            "games": games_data,
            "stats": {"today_minutes": today_minutes, "week_minutes": week_minutes, "month_minutes": month_minutes}
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
        start_date = datetime.datetime(year, month + 1, 1)
        end_date = datetime.datetime(year + 1, 1, 1) if month == 11 else datetime.datetime(year, month + 2, 1)
        
        start_ts = start_date.timestamp()
        end_ts = end_date.timestamp()
        threshold_seconds = threshold * 60
        
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
        
        days_data = {}
        for row in results:
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
async def get_game_icon(process_id: str):
    """게임 아이콘 이미지 반환"""
    from fastapi.responses import Response
    from src.data.database import SessionLocal
    
    db = SessionLocal()
    try:
        process = db.query(models.Process).filter(models.Process.id == process_id).first()
        name = process.name if process else "?"
        initial = name[0].upper() if name else "?"
        
        # 색상 해시
        colors = ['#6366f1','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899']
        h = sum(ord(c) for c in name)
        color = colors[h % len(colors)]
        
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">
            <rect width="32" height="32" rx="6" fill="{color}"/>
            <text x="16" y="21" text-anchor="middle" fill="white" font-size="16" font-family="Arial" font-weight="bold">{initial}</text>
        </svg>'''
        return Response(content=svg, media_type="image/svg+xml")
    finally:
        db.close()
