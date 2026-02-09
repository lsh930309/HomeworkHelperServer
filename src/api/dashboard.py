# dashboard.py
"""대시보드 API 및 HTML 렌더링 모듈 v3"""

import datetime
import json
import os
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Body
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import func, text

from src.data import models

router = APIRouter()

# 설정 파일 경로
SETTINGS_DIR = os.path.join(os.getenv('APPDATA', os.path.expanduser('~')), 'HomeworkHelper')
SETTINGS_FILE = os.path.join(SETTINGS_DIR, 'dashboard_settings.json')

DEFAULT_SETTINGS = {
    "theme": "auto",
    "toolbar": "top",
    "chartType": "bar",
    "stackMode": "stacked",
    "calendarThreshold": 10
}


def load_settings():
    """AppData에서 설정 로드"""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return {**DEFAULT_SETTINGS, **json.load(f)}
    except:
        pass
    return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict):
    """AppData에 설정 저장"""
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


def get_dashboard_html() -> str:
    """대시보드 HTML 페이지를 반환합니다."""
    return '''<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>숙제 관리자 - 대시보드</title>
    
    <link href="https://api.fontshare.com/v2/css?f[]=satoshi@400,500,700&display=swap" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1"></script>
    
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
        html, body { height: 100%; overflow: hidden; }
        
        body {
            font-family: 'Satoshi', -apple-system, BlinkMacSystemFont, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            display: flex;
            flex-direction: column;
        }
        
        /* === Toolbar === */
        .toolbar {
            height: 52px;
            background: var(--bg-card);
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0 16px;
            z-index: 100;
            flex-shrink: 0;
            transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
        }
        
        /* 플로팅 스타일 - 더 플로팅 느낌 */
        body[data-toolbar="floating-top"] .toolbar,
        body[data-toolbar="floating-bottom"] .toolbar {
            position: fixed;
            left: 24px;
            right: 24px;
            border-radius: 20px;
            border: 1px solid var(--border-color);
            box-shadow: 0 8px 32px rgba(0,0,0,0.15), 0 2px 8px rgba(0,0,0,0.1);
            backdrop-filter: blur(16px);
            background: color-mix(in srgb, var(--bg-card) 85%, transparent);
        }
        body[data-toolbar="floating-top"] .toolbar { top: 20px; }
        body[data-toolbar="floating-bottom"] .toolbar { bottom: 20px; top: auto; }
        body[data-toolbar="floating-top"] .main-content { padding-top: 92px; }
        body[data-toolbar="floating-bottom"] .main-content { padding-bottom: 92px; }
        body[data-toolbar="bottom"] { flex-direction: column-reverse; }
        body[data-toolbar="bottom"] .toolbar { border-bottom: none; border-top: 1px solid var(--border-color); }
        
        .toolbar-brand {
            font-weight: 700;
            font-size: 1rem;
            color: var(--accent);
        }
        
        /* === 탭 버튼 === */
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
            padding: 7px 18px;
            border: none;
            background: transparent;
            color: var(--text-secondary);
            font-family: inherit;
            font-size: 0.85rem;
            font-weight: 500;
            cursor: pointer;
            border-radius: 8px;
            transition: color 0.2s;
            position: relative;
            z-index: 1;
        }
        
        .tab-btn.active { color: white; }
        .tab-btn:not(.active):hover { color: var(--text-primary); }
        
        .toolbar-actions { display: flex; gap: 6px; align-items: center; }
        
        .icon-btn {
            width: 34px;
            height: 34px;
            border: 1px solid var(--border-color);
            background: var(--bg-secondary);
            border-radius: 8px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1rem;
            transition: all 0.2s;
        }
        
        .icon-btn:hover { background: var(--accent); color: white; border-color: var(--accent); }
        
        /* === 메인 컨텐츠 === */
        .main-content {
            flex: 1;
            padding: 16px;
            display: flex;
            flex-direction: column;
            gap: 12px;
            overflow: auto;
        }
        
        .tab-panel { display: none; flex: 1; min-height: 0; }
        .tab-panel.active {
            display: flex;
            flex-direction: column;
            gap: 12px;
            animation: fadeIn 0.3s ease;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(6px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        /* === 카드 === */
        .card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 12px;
            padding: 14px;
        }
        
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
            flex-wrap: wrap;
            gap: 10px;
        }
        
        .card-title { font-size: 0.95rem; font-weight: 600; }
        
        /* === 통계 그리드 === */
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 10px;
        }
        @media (max-width: 800px) { .stats-grid { grid-template-columns: repeat(2, 1fr); } }
        
        .stat-card {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 10px 14px;
        }
        
        .stat-label { font-size: 0.7rem; color: var(--text-secondary); margin-bottom: 2px; }
        .stat-value { font-size: 1.4rem; font-weight: 700; color: var(--accent); }
        .stat-unit { font-size: 0.7rem; color: var(--text-secondary); font-weight: 400; }
        
        /* === 차트 === */
        .chart-container { position: relative; flex: 1; min-height: 220px; }
        
        /* 게임 아이콘 범례 */
        .chart-legend {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            margin-bottom: 8px;
        }
        
        .legend-item {
            display: flex;
            align-items: center;
            gap: 4px;
            padding: 4px 8px;
            background: var(--bg-secondary);
            border-radius: 6px;
            font-size: 0.75rem;
        }
        
        .legend-icon {
            width: 20px;
            height: 20px;
            border-radius: 4px;
            display: flex;
            align-items: center;
            justify-content: center;
            color: white;
            font-weight: 600;
            font-size: 0.65rem;
        }
        
        /* === 달력 === */
        .calendar-wrapper { flex: 1; display: flex; flex-direction: column; min-height: 0; }
        
        .calendar-grid {
            display: grid;
            grid-template-columns: repeat(7, 1fr);
            gap: 3px;
            flex: 1;
        }
        
        .calendar-header {
            text-align: center;
            font-size: 0.65rem;
            font-weight: 600;
            color: var(--text-secondary);
            padding: 3px 0;
        }
        
        .calendar-day {
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 3px 2px;
            border-radius: 5px;
            background: var(--bg-secondary);
            font-size: 0.65rem;
            cursor: pointer;
            transition: all 0.2s;
            min-height: 44px;
        }
        
        .calendar-day:hover { border: 1px solid var(--accent); }
        .calendar-day.empty { background: transparent; pointer-events: none; }
        .calendar-day .date { font-weight: 600; margin-bottom: 1px; font-size: 0.7rem; }
        
        .calendar-day .icons {
            display: flex;
            flex-wrap: wrap;
            gap: 2px;
            justify-content: center;
            flex: 1;
            align-items: flex-start;
        }
        
        .calendar-day .icon {
            width: 20px;
            height: 20px;
            border-radius: 4px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.6rem;
            font-weight: 600;
            color: white;
        }
        
        .month-nav { display: flex; align-items: center; gap: 10px; }
        .month-nav button {
            padding: 5px 10px;
            border: 1px solid var(--border-color);
            background: var(--bg-secondary);
            color: var(--text-primary);
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.8rem;
        }
        .month-nav button:hover { background: var(--accent); color: white; }
        .month-title { font-size: 0.95rem; font-weight: 600; }
        
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
            padding: 20px;
            width: 360px;
            max-width: 90%;
            max-height: 80vh;
            overflow-y: auto;
            transform: scale(0.9);
            transition: transform 0.2s;
        }
        
        .modal-overlay.active .modal { transform: scale(1); }
        .modal-title { font-size: 1rem; font-weight: 600; margin-bottom: 14px; }
        
        .setting-group { margin-bottom: 14px; }
        .setting-label { font-size: 0.8rem; color: var(--text-secondary); margin-bottom: 5px; display: block; }
        .setting-options { display: flex; gap: 5px; flex-wrap: wrap; }
        
        .setting-btn {
            padding: 6px 12px;
            border: 1px solid var(--border-color);
            background: var(--bg-secondary);
            color: var(--text-primary);
            border-radius: 6px;
            cursor: pointer;
            font-family: inherit;
            font-size: 0.8rem;
            transition: all 0.2s;
        }
        
        .setting-btn:hover { border-color: var(--accent); }
        .setting-btn.active { background: var(--accent); color: white; border-color: var(--accent); }
        
        .modal-close {
            margin-top: 14px;
            width: 100%;
            padding: 9px;
            border: none;
            background: var(--accent);
            color: white;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.85rem;
            font-weight: 500;
        }
    </style>
</head>
<body data-toolbar="top">
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
    
    <main class="main-content">
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
                </div>
                <div class="chart-legend" id="chartLegend"></div>
                <div class="chart-container">
                    <canvas id="playtimeChart"></canvas>
                </div>
            </div>
        </section>
        
        <section id="calendar" class="tab-panel">
            <div class="card calendar-wrapper">
                <div class="card-header">
                    <div class="month-nav">
                        <button id="prevMonth">◀</button>
                        <span class="month-title" id="monthTitle">2026년 2월</span>
                        <button id="nextMonth">▶</button>
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
    
    <div class="modal-overlay" id="settingsModal">
        <div class="modal">
            <h3 class="modal-title">⚙️ 설정</h3>
            
            <div class="setting-group">
                <label class="setting-label">테마</label>
                <div class="setting-options" id="themeOptions">
                    <button class="setting-btn" data-value="auto">자동</button>
                    <button class="setting-btn" data-value="light">라이트</button>
                    <button class="setting-btn" data-value="dark">다크</button>
                </div>
            </div>
            
            <div class="setting-group">
                <label class="setting-label">툴바 위치</label>
                <div class="setting-options" id="toolbarOptions">
                    <button class="setting-btn" data-value="top">상단</button>
                    <button class="setting-btn" data-value="bottom">하단</button>
                    <button class="setting-btn" data-value="floating-top">플로팅↑</button>
                    <button class="setting-btn" data-value="floating-bottom">플로팅↓</button>
                </div>
            </div>
            
            <div class="setting-group">
                <label class="setting-label">차트 유형</label>
                <div class="setting-options" id="chartTypeOptions">
                    <button class="setting-btn" data-value="bar">막대</button>
                    <button class="setting-btn" data-value="line">선형</button>
                </div>
            </div>
            
            <div class="setting-group">
                <label class="setting-label">데이터 표시</label>
                <div class="setting-options" id="stackModeOptions">
                    <button class="setting-btn" data-value="stacked">누적</button>
                    <button class="setting-btn" data-value="grouped">개별</button>
                </div>
            </div>
            
            <div class="setting-group">
                <label class="setting-label">기간</label>
                <div class="setting-options" id="periodOptions">
                    <button class="setting-btn" data-value="week">주간</button>
                    <button class="setting-btn" data-value="month">월간</button>
                </div>
            </div>
            
            <div class="setting-group">
                <label class="setting-label">달력 최소 플레이 시간 (분)</label>
                <div class="setting-options">
                    <input type="number" id="thresholdInput" value="10" min="0" style="width:60px;padding:6px 10px;border:1px solid var(--border-color);border-radius:6px;background:var(--bg-secondary);color:var(--text-primary);font-size:0.8rem;">
                </div>
            </div>
            
            <button class="modal-close" id="closeSettings">닫기</button>
        </div>
    </div>
    
    <script>
        const state = {
            currentMonth: new Date().getMonth(),
            currentYear: new Date().getFullYear(),
            games: [],
            gameNameMap: {},
            playtimeData: null,
            calendarData: null,
            settings: null
        };
        
        const COLORS = ['#6366f1','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#06b6d4','#84cc16','#f97316','#14b8a6'];
        
        function getColorForName(name) {
            let hash = 0;
            for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
            return COLORS[Math.abs(hash) % COLORS.length];
        }
        
        // === 설정 ===
        async function loadSettings() {
            try {
                const res = await fetch('/api/dashboard/settings');
                state.settings = await res.json();
            } catch {
                state.settings = { theme: 'auto', toolbar: 'top', chartType: 'bar', stackMode: 'stacked', period: 'week', calendarThreshold: 10 };
            }
            applySettings();
        }
        
        async function saveSettings() {
            try {
                await fetch('/api/dashboard/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(state.settings)
                });
            } catch (e) { console.error('설정 저장 실패:', e); }
            localStorage.setItem('dashboard_settings', JSON.stringify(state.settings));
        }
        
        function applySettings() {
            const s = state.settings;
            
            // 테마
            if (s.theme === 'auto') document.documentElement.removeAttribute('data-theme');
            else document.documentElement.setAttribute('data-theme', s.theme);
            
            // 툴바
            document.body.setAttribute('data-toolbar', s.toolbar);
            
            // UI 업데이트
            document.querySelectorAll('#themeOptions .setting-btn').forEach(b => b.classList.toggle('active', b.dataset.value === s.theme));
            document.querySelectorAll('#toolbarOptions .setting-btn').forEach(b => b.classList.toggle('active', b.dataset.value === s.toolbar));
            document.querySelectorAll('#chartTypeOptions .setting-btn').forEach(b => b.classList.toggle('active', b.dataset.value === s.chartType));
            document.querySelectorAll('#stackModeOptions .setting-btn').forEach(b => b.classList.toggle('active', b.dataset.value === s.stackMode));
            document.querySelectorAll('#periodOptions .setting-btn').forEach(b => b.classList.toggle('active', b.dataset.value === s.period));
            document.getElementById('thresholdInput').value = s.calendarThreshold || 10;
        }
        
        function updateTabIndicator() {
            const tab = document.querySelector('.tab-btn.active');
            const ind = document.getElementById('tabIndicator');
            if (tab && ind) {
                ind.style.width = tab.offsetWidth + 'px';
                ind.style.left = tab.offsetLeft + 'px';
            }
        }
        
        // === API ===
        async function fetchAPI(url) {
            try {
                const res = await fetch(url);
                return res.ok ? await res.json() : null;
            } catch { return null; }
        }
        
        async function loadGames() {
            const games = await fetchAPI('/processes');
            if (games) {
                state.games = games;
                state.gameNameMap = {};
                games.forEach(g => { state.gameNameMap[g.name.toLowerCase()] = g; });
                document.getElementById('statGames').innerHTML = `${games.length}<span class="stat-unit">개</span>`;
            }
        }
        
        async function loadPlaytimeData() {
            const period = state.settings?.period || 'week';
            const data = await fetchAPI(`/api/dashboard/playtime?period=${period}&merge_names=true`);
            if (data) {
                state.playtimeData = data;
                updatePlaytimeChart(data);
                updateStats(data);
            }
        }
        
        async function loadCalendarData() {
            const threshold = state.settings?.calendarThreshold || 10;
            const data = await fetchAPI(`/api/dashboard/calendar?year=${state.currentYear}&month=${state.currentMonth}&threshold=${threshold}`);
            if (data) {
                state.calendarData = data;
                renderCalendar(data, state.currentYear, state.currentMonth);
            }
        }
        
        function updateStats(data) {
            if (data.stats) {
                document.getElementById('statToday').innerHTML = `${Math.round(data.stats.today_minutes || 0)}<span class="stat-unit">분</span>`;
                document.getElementById('statWeek').innerHTML = `${((data.stats.week_minutes || 0) / 60).toFixed(1)}<span class="stat-unit">시간</span>`;
                document.getElementById('statMonth').innerHTML = `${((data.stats.month_minutes || 0) / 60).toFixed(1)}<span class="stat-unit">시간</span>`;
            }
        }
        
        // === 차트 ===
        let playtimeChart = null;
        
        function updatePlaytimeChart(data) {
            const ctx = document.getElementById('playtimeChart').getContext('2d');
            if (playtimeChart) playtimeChart.destroy();
            
            const chartType = state.settings?.chartType || 'bar';
            const stackMode = state.settings?.stackMode || 'stacked';
            
            // 아이콘 범례 생성
            const legendEl = document.getElementById('chartLegend');
            legendEl.innerHTML = '';
            
            const datasets = [];
            const gameNames = Object.keys(data.games || {});
            
            gameNames.forEach((name, idx) => {
                const gdata = data.games[name];
                const color = getColorForName(name);
                
                // 범례 아이템 추가
                const item = document.createElement('div');
                item.className = 'legend-item';
                item.innerHTML = `<div class="legend-icon" style="background:${color}">${name.charAt(0).toUpperCase()}</div><span>${name}</span>`;
                legendEl.appendChild(item);
                
                datasets.push({
                    label: name,
                    data: gdata.minutes.map(m => m / 60),
                    backgroundColor: chartType === 'bar' ? color + 'cc' : color + '33',
                    borderColor: color,
                    borderWidth: 2,
                    fill: chartType === 'line' && stackMode === 'stacked',
                    tension: 0.4,
                    pointRadius: chartType === 'line' ? 4 : 0,
                    pointBackgroundColor: color
                });
            });
            
            const isDark = getComputedStyle(document.documentElement).getPropertyValue('--bg-primary').includes('0f0f23');
            const gridColor = isDark ? '#2d3748' : '#e9ecef';
            const textColor = isDark ? '#adb5bd' : '#6c757d';
            
            const labels = data.dates.map(d => {
                const p = d.split('-');
                return `${parseInt(p[1])}/${parseInt(p[2])}`;
            });
            
            playtimeChart = new Chart(ctx, {
                type: chartType,
                data: { labels, datasets },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { intersect: false, mode: 'index' },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: c => `${c.dataset.label}: ${c.parsed.y.toFixed(1)}시간`
                            }
                        }
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
            const headers = [...grid.querySelectorAll('.calendar-header')];
            grid.innerHTML = '';
            headers.forEach(h => grid.appendChild(h));
            
            const firstDay = new Date(year, month, 1).getDay();
            const daysInMonth = new Date(year, month + 1, 0).getDate();
            
            for (let i = 0; i < firstDay; i++) {
                const e = document.createElement('div');
                e.className = 'calendar-day empty';
                grid.appendChild(e);
            }
            
            for (let day = 1; day <= daysInMonth; day++) {
                const dateStr = `${year}-${String(month+1).padStart(2,'0')}-${String(day).padStart(2,'0')}`;
                const dayData = data.days?.[dateStr];
                
                const cell = document.createElement('div');
                cell.className = 'calendar-day';
                
                let iconsHtml = '';
                if (dayData?.games) {
                    const validGames = dayData.games.filter(g => state.gameNameMap[g.name.toLowerCase()]);
                    iconsHtml = validGames.slice(0, 4).map(g => {
                        const color = getColorForName(g.name);
                        return `<div class="icon" title="${g.name}: ${Math.round(g.minutes)}분" style="background:${color}">${g.name.charAt(0).toUpperCase()}</div>`;
                    }).join('');
                    if (validGames.length > 4) iconsHtml += `<div class="icon" style="background:var(--text-secondary)">+${validGames.length-4}</div>`;
                }
                
                cell.innerHTML = `<span class="date">${day}</span><div class="icons">${iconsHtml}</div>`;
                grid.appendChild(cell);
            }
        }
        
        // === 이벤트 ===
        function initEvents() {
            // 탭
            document.querySelectorAll('.tab-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
                    btn.classList.add('active');
                    document.getElementById(btn.dataset.tab).classList.add('active');
                    updateTabIndicator();
                    if (btn.dataset.tab === 'calendar') loadCalendarData();
                });
            });
            
            // 월 이동
            document.getElementById('prevMonth').addEventListener('click', () => {
                state.currentMonth--;
                if (state.currentMonth < 0) { state.currentMonth = 11; state.currentYear--; }
                loadCalendarData();
            });
            document.getElementById('nextMonth').addEventListener('click', () => {
                state.currentMonth++;
                if (state.currentMonth > 11) { state.currentMonth = 0; state.currentYear++; }
                loadCalendarData();
            });
            
            // 설정 모달
            document.getElementById('settingsBtn').addEventListener('click', () => document.getElementById('settingsModal').classList.add('active'));
            document.getElementById('closeSettings').addEventListener('click', () => document.getElementById('settingsModal').classList.remove('active'));
            document.getElementById('settingsModal').addEventListener('click', e => { if (e.target.id === 'settingsModal') e.target.classList.remove('active'); });
            
            // 설정 옵션들
            const settingHandlers = [
                { id: 'themeOptions', key: 'theme', reload: false },
                { id: 'toolbarOptions', key: 'toolbar', reload: false },
                { id: 'chartTypeOptions', key: 'chartType', reload: true },
                { id: 'stackModeOptions', key: 'stackMode', reload: true },
                { id: 'periodOptions', key: 'period', reload: true }
            ];
            
            settingHandlers.forEach(({ id, key, reload }) => {
                document.querySelectorAll(`#${id} .setting-btn`).forEach(btn => {
                    btn.addEventListener('click', () => {
                        state.settings[key] = btn.dataset.value;
                        applySettings();
                        saveSettings();
                        if (reload) loadPlaytimeData();
                    });
                });
            });
            
            document.getElementById('thresholdInput').addEventListener('change', e => {
                state.settings.calendarThreshold = parseInt(e.target.value) || 10;
                saveSettings();
                loadCalendarData();
            });
            
            window.addEventListener('resize', updateTabIndicator);
        }
        
        async function init() {
            await loadSettings();
            initEvents();
            await loadGames();
            await loadPlaytimeData();
            requestAnimationFrame(updateTabIndicator);
        }
        
        init();
    </script>
</body>
</html>'''


@router.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard():
    return get_dashboard_html()


@router.get("/api/dashboard/settings")
async def get_settings():
    """대시보드 설정 조회"""
    return JSONResponse(load_settings())


@router.post("/api/dashboard/settings")
async def save_settings_api(settings: dict = Body(...)):
    """대시보드 설정 저장"""
    current = load_settings()
    current.update(settings)
    save_settings(current)
    return {"status": "ok"}


@router.get("/api/dashboard/playtime")
async def get_playtime_stats(
    period: str = Query("week"),
    game_id: str = Query("all"),
    merge_names: bool = Query(False, description="동일 이름 게임 병합")
):
    """기간별 플레이 시간 통계 API (이름 기준 병합 지원)"""
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
        
        # 이름 기준 병합
        games_data = {}
        for row in results:
            # 이름 기준으로 그룹핑 (merge_names=True일 때)
            key = row.process_name if merge_names else row.process_id
            
            if key not in games_data:
                games_data[key] = {"name": row.process_name, "minutes": [0] * days}
            
            if row.play_date in dates:
                idx = dates.index(row.play_date)
                games_data[key]["minutes"][idx] += (row.total_seconds or 0) / 60
        
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
    year: int = Query(...),
    month: int = Query(...),
    threshold: int = Query(10)
):
    """달력 데이터 API (이름 기준 병합)"""
    from src.data.database import SessionLocal
    db = SessionLocal()
    
    try:
        start_date = datetime.datetime(year, month + 1, 1)
        end_date = datetime.datetime(year + 1, 1, 1) if month == 11 else datetime.datetime(year, month + 2, 1)
        
        results = db.query(
            func.date(models.ProcessSession.start_timestamp, 'unixepoch', 'localtime').label('play_date'),
            models.ProcessSession.process_id,
            models.ProcessSession.process_name,
            func.sum(models.ProcessSession.session_duration).label('total_seconds')
        ).filter(
            models.ProcessSession.start_timestamp >= start_date.timestamp(),
            models.ProcessSession.start_timestamp < end_date.timestamp(),
            models.ProcessSession.session_duration.isnot(None)
        ).group_by('play_date', models.ProcessSession.process_name).all()  # process_name으로 그룹핑
        
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
    from fastapi.responses import Response
    from src.data.database import SessionLocal
    
    db = SessionLocal()
    try:
        process = db.query(models.Process).filter(models.Process.id == process_id).first()
        name = process.name if process else "?"
        initial = name[0].upper() if name else "?"
        
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
