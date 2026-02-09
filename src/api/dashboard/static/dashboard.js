// dashboard.js - 대시보드 JavaScript v5

const Dashboard = {
    // === 상태 ===
    state: {
        currentMonth: new Date().getMonth(),
        currentYear: new Date().getFullYear(),
        currentPeriodOffset: 0,  // 주간/월간 오프셋
        games: [],
        gameNameMap: {},
        gameColors: {},
        playtimeData: null,
        calendarData: null,
        settings: null,
        iconImages: {},
        iconCache: {}
    },

    // 확장된 색상 팔레트 (15색, 구분 용이)
    COLORS: [
        '#6366f1', '#22c55e', '#f59e0b', '#ef4444', '#8b5cf6',
        '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#14b8a6',
        '#a855f7', '#3b82f6', '#eab308', '#64748b', '#0ea5e9'
    ],

    DEFAULT_SETTINGS: {
        theme: 'auto',
        toolbar: 'top',
        chartType: 'bar',
        stackMode: 'stacked',
        period: 'week',
        calendarThreshold: 10,
        showUnregistered: false,
        showChartIcons: true
    },

    playtimeChart: null,

    // === 초기화 ===
    async init() {
        await this.loadSettings();
        this.initEvents();
        await this.loadGames();
        await this.loadPlaytimeData();
        requestAnimationFrame(() => this.updateTabIndicator());
    },

    // === 색상 ===
    getColorForGame(name, index) {
        if (this.state.gameColors[name]) return this.state.gameColors[name];
        const color = this.COLORS[index % this.COLORS.length];
        this.state.gameColors[name] = color;
        return color;
    },

    // === 아이콘 ===
    async preloadIcon(name, processId) {
        const cacheKey = processId || name;
        if (this.state.iconImages[cacheKey]) return this.state.iconImages[cacheKey];

        const img = new Image();

        // 실제 아이콘 시도
        if (processId) {
            const iconUrl = `/api/dashboard/icons/${processId}`;
            try {
                const res = await fetch(iconUrl, { method: 'HEAD' });
                if (res.ok) {
                    img.src = iconUrl;
                    this.state.iconImages[cacheKey] = img;
                    return img;
                }
            } catch (e) { }
        }

        // 폴백 SVG
        const color = this.state.gameColors[name] || this.COLORS[0];
        const initial = name.charAt(0).toUpperCase();
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
            <rect width="24" height="24" rx="4" fill="${color}"/>
            <text x="12" y="16" text-anchor="middle" fill="white" font-size="12" font-family="Arial" font-weight="bold">${initial}</text>
        </svg>`;
        img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
        this.state.iconImages[cacheKey] = img;
        return img;
    },

    // === 차트 아이콘 플러그인 ===
    chartIconPlugin: {
        id: 'chartIcons',
        afterDraw: (chart) => {
            const self = Dashboard;
            if (!self.state.settings?.showChartIcons) return;

            const ctx = chart.ctx;
            const chartType = chart.config.type;
            const stackMode = self.state.settings?.stackMode || 'stacked';
            const datasets = chart.data.datasets;

            // 아이콘 위치 계산 (겹침 방지)
            const iconPositions = [];

            datasets.forEach((dataset, datasetIndex) => {
                const meta = chart.getDatasetMeta(datasetIndex);
                if (meta.hidden) return;

                const img = self.state.iconImages[dataset.label];
                if (!img || !img.complete) return;

                const iconSize = 18;
                const data = dataset.data;

                if (chartType === 'bar' && stackMode !== 'stacked') {
                    // 개별 모드: 각 막대 위에 아이콘
                    meta.data.forEach((bar, index) => {
                        if (data[index] > 0) {
                            const x = bar.x - iconSize / 2;
                            const y = bar.y - iconSize - 4;
                            ctx.drawImage(img, x, y, iconSize, iconSize);
                        }
                    });
                } else if (chartType === 'bar' && stackMode === 'stacked') {
                    // 누적 모드: 최상단에만
                    if (datasetIndex === datasets.length - 1) {
                        meta.data.forEach((bar, index) => {
                            const x = bar.x - iconSize / 2;
                            const y = bar.y - iconSize - 4;
                            ctx.drawImage(img, x, y, iconSize, iconSize);
                        });
                    }
                } else if (chartType === 'line') {
                    // 선형: 최적 위치 계산
                    const bestIdx = self.findBestIconPosition(data, datasetIndex, datasets, iconPositions);
                    if (bestIdx >= 0 && data[bestIdx] > 0) {
                        const point = meta.data[bestIdx];
                        if (point) {
                            const x = point.x - iconSize / 2;
                            const y = point.y - iconSize - 6;
                            iconPositions.push({ x: point.x, y: point.y, idx: bestIdx });
                            ctx.drawImage(img, x, y, iconSize, iconSize);
                        }
                    }
                }
            });
        }
    },

    // 선형 그래프 최적 아이콘 위치 계산
    findBestIconPosition(data, datasetIndex, allDatasets, existingPositions) {
        if (!data || data.length === 0) return -1;

        let bestIdx = 0;
        let bestScore = -Infinity;

        for (let i = 0; i < data.length; i++) {
            if (data[i] <= 0) continue;

            let score = 0;

            // 1. 값이 클수록 좋음
            score += data[i] * 10;

            // 2. 다른 데이터셋과의 차이가 클수록 좋음
            let maxDiff = 0;
            allDatasets.forEach((ds, idx) => {
                if (idx !== datasetIndex && ds.data[i]) {
                    maxDiff = Math.max(maxDiff, Math.abs(data[i] - ds.data[i]));
                }
            });
            score += maxDiff * 5;

            // 3. 기존 아이콘 위치와 멀수록 좋음
            let minDist = Infinity;
            existingPositions.forEach(pos => {
                const dist = Math.abs(pos.idx - i);
                minDist = Math.min(minDist, dist);
            });
            if (minDist !== Infinity) {
                score += minDist * 3;
            }

            if (score > bestScore) {
                bestScore = score;
                bestIdx = i;
            }
        }

        return bestIdx;
    },

    // === 설정 ===
    async loadSettings() {
        try {
            const res = await fetch('/api/dashboard/settings');
            this.state.settings = await res.json();
        } catch {
            this.state.settings = { ...this.DEFAULT_SETTINGS };
        }
        this.applySettings();
    },

    async saveSettings() {
        try {
            await fetch('/api/dashboard/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.state.settings)
            });
        } catch (e) { console.error('설정 저장 실패:', e); }
        localStorage.setItem('dashboard_settings', JSON.stringify(this.state.settings));
    },

    applySettings() {
        const s = this.state.settings;

        if (s.theme === 'auto') document.documentElement.removeAttribute('data-theme');
        else document.documentElement.setAttribute('data-theme', s.theme);

        document.body.setAttribute('data-toolbar', s.toolbar);

        document.querySelectorAll('#themeOptions .setting-btn').forEach(b =>
            b.classList.toggle('active', b.dataset.value === s.theme));
        document.querySelectorAll('#toolbarOptions .setting-btn').forEach(b =>
            b.classList.toggle('active', b.dataset.value === s.toolbar));
        document.querySelectorAll('#chartTypeOptions .setting-btn').forEach(b =>
            b.classList.toggle('active', b.dataset.value === s.chartType));
        document.querySelectorAll('#stackModeOptions .setting-btn').forEach(b =>
            b.classList.toggle('active', b.dataset.value === s.stackMode));
        document.querySelectorAll('#periodOptions .setting-btn').forEach(b =>
            b.classList.toggle('active', b.dataset.value === s.period));

        const thresholdInput = document.getElementById('thresholdInput');
        if (thresholdInput) thresholdInput.value = s.calendarThreshold || 10;

        document.getElementById('showUnregisteredToggle')?.classList.toggle('active', s.showUnregistered);
        document.getElementById('showChartIconsToggle')?.classList.toggle('active', s.showChartIcons !== false);

        this.updatePeriodLabel();
    },

    updateTabIndicator() {
        const tab = document.querySelector('.tab-btn.active');
        const ind = document.getElementById('tabIndicator');
        if (tab && ind) {
            ind.style.width = tab.offsetWidth + 'px';
            ind.style.left = tab.offsetLeft + 'px';
        }
    },

    // === 기간 네비게이션 ===
    updatePeriodLabel() {
        const label = document.getElementById('periodLabel');
        if (!label) return;

        const period = this.state.settings?.period || 'week';
        const offset = this.state.currentPeriodOffset;
        const now = new Date();

        if (period === 'week') {
            const weekStart = new Date(now);
            weekStart.setDate(weekStart.getDate() - weekStart.getDay() + (offset * 7));
            const weekEnd = new Date(weekStart);
            weekEnd.setDate(weekEnd.getDate() + 6);

            const formatDate = d => `${d.getMonth() + 1}/${d.getDate()}`;
            label.textContent = `${formatDate(weekStart)} ~ ${formatDate(weekEnd)}`;
        } else {
            const targetDate = new Date(now.getFullYear(), now.getMonth() + offset, 1);
            label.textContent = `${targetDate.getFullYear()}년 ${targetDate.getMonth() + 1}월`;
        }
    },

    // === API ===
    async fetchAPI(url) {
        try {
            const res = await fetch(url);
            return res.ok ? await res.json() : null;
        } catch { return null; }
    },

    async loadGames() {
        const games = await this.fetchAPI('/processes');
        if (games) {
            this.state.games = games;
            this.state.gameNameMap = {};
            games.forEach((g, idx) => {
                this.state.gameNameMap[g.name.toLowerCase()] = g;
                this.getColorForGame(g.name, idx);
            });
            document.getElementById('statGames').innerHTML =
                `${games.length}<span class="stat-unit">개</span>`;
        }
    },

    async loadPlaytimeData() {
        const period = this.state.settings?.period || 'week';
        const offset = this.state.currentPeriodOffset;
        const showUnreg = this.state.settings?.showUnregistered ? 'true' : 'false';

        const data = await this.fetchAPI(
            `/api/dashboard/playtime?period=${period}&offset=${offset}&merge_names=true&show_unregistered=${showUnreg}`
        );

        if (data) {
            this.state.playtimeData = data;

            // 색상 할당 및 아이콘 프리로드
            const gameNames = Object.keys(data.games || {});
            gameNames.forEach((name, idx) => {
                this.getColorForGame(name, idx);
                this.preloadIcon(name, data.games[name].process_id);
            });

            setTimeout(() => this.updatePlaytimeChart(data), 100);
            this.updateStats(data);
        }

        this.updatePeriodLabel();
    },

    async loadCalendarData() {
        const threshold = this.state.settings?.calendarThreshold || 10;
        const showUnreg = this.state.settings?.showUnregistered ? 'true' : 'false';

        const data = await this.fetchAPI(
            `/api/dashboard/calendar?year=${this.state.currentYear}&month=${this.state.currentMonth}&threshold=${threshold}&show_unregistered=${showUnreg}`
        );

        if (data) {
            this.state.calendarData = data;
            this.renderCalendar(data, this.state.currentYear, this.state.currentMonth);
        }
    },

    updateStats(data) {
        if (data.stats) {
            document.getElementById('statToday').innerHTML =
                `${Math.round(data.stats.today_minutes || 0)}<span class="stat-unit">분</span>`;
            document.getElementById('statWeek').innerHTML =
                `${((data.stats.week_minutes || 0) / 60).toFixed(1)}<span class="stat-unit">시간</span>`;
            document.getElementById('statMonth').innerHTML =
                `${((data.stats.month_minutes || 0) / 60).toFixed(1)}<span class="stat-unit">시간</span>`;
        }
    },

    // === 차트 ===
    updatePlaytimeChart(data) {
        const ctx = document.getElementById('playtimeChart').getContext('2d');
        if (this.playtimeChart) this.playtimeChart.destroy();

        const chartType = this.state.settings?.chartType || 'bar';
        const stackMode = this.state.settings?.stackMode || 'stacked';

        const legendEl = document.getElementById('chartLegend');
        legendEl.innerHTML = '';

        const datasets = [];
        const gameNames = Object.keys(data.games || {});

        gameNames.forEach((name, idx) => {
            const gdata = data.games[name];
            const color = this.getColorForGame(name, idx);

            // 범례 아이템
            const item = document.createElement('div');
            item.className = 'legend-item';
            item.innerHTML = `<div class="legend-icon" style="background:${color}">
                <span class="fallback">${name.charAt(0).toUpperCase()}</span>
            </div><span>${name}</span>`;
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

        const isDark = getComputedStyle(document.documentElement)
            .getPropertyValue('--bg-primary').includes('0f0f23');
        const gridColor = isDark ? '#2d3748' : '#e9ecef';
        const textColor = isDark ? '#adb5bd' : '#6c757d';

        const labels = data.dates.map(d => {
            const p = d.split('-');
            return `${parseInt(p[1])}/${parseInt(p[2])}`;
        });

        this.playtimeChart = new Chart(ctx, {
            type: chartType,
            data: { labels, datasets },
            plugins: [this.chartIconPlugin],
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { intersect: false, mode: 'index' },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: { label: c => `${c.dataset.label}: ${c.parsed.y.toFixed(1)}시간` }
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
    },

    // === 달력 ===
    renderCalendar(data, year, month) {
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
            const dateStr = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
            const dayData = data.days?.[dateStr];

            const cell = document.createElement('div');
            cell.className = 'calendar-day';

            let iconsHtml = '';
            if (dayData?.games) {
                const showUnreg = this.state.settings?.showUnregistered;
                const gamesFiltered = showUnreg ? dayData.games :
                    dayData.games.filter(g => this.state.gameNameMap[g.name.toLowerCase()]);

                iconsHtml = gamesFiltered.map(g => {
                    const color = this.state.gameColors[g.name] || this.COLORS[0];
                    return `<div class="icon" title="${g.name}: ${Math.round(g.minutes)}분" style="background:${color}">${g.name.charAt(0).toUpperCase()}</div>`;
                }).join('');
            }

            cell.innerHTML = `<span class="date">${day}</span><div class="icons">${iconsHtml}</div>`;
            grid.appendChild(cell);
        }
    },

    // === 이벤트 ===
    initEvents() {
        // 탭 전환
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
                btn.classList.add('active');
                document.getElementById(btn.dataset.tab).classList.add('active');
                this.updateTabIndicator();
                if (btn.dataset.tab === 'calendar') this.loadCalendarData();
            });
        });

        // 기간 네비게이션
        document.getElementById('prevPeriod')?.addEventListener('click', () => {
            this.state.currentPeriodOffset--;
            this.loadPlaytimeData();
        });
        document.getElementById('nextPeriod')?.addEventListener('click', () => {
            this.state.currentPeriodOffset++;
            this.loadPlaytimeData();
        });

        // 월 네비게이션
        document.getElementById('prevMonth')?.addEventListener('click', () => {
            this.state.currentMonth--;
            if (this.state.currentMonth < 0) {
                this.state.currentMonth = 11;
                this.state.currentYear--;
            }
            this.loadCalendarData();
        });
        document.getElementById('nextMonth')?.addEventListener('click', () => {
            this.state.currentMonth++;
            if (this.state.currentMonth > 11) {
                this.state.currentMonth = 0;
                this.state.currentYear++;
            }
            this.loadCalendarData();
        });

        // 설정 모달
        document.getElementById('settingsBtn')?.addEventListener('click', () =>
            document.getElementById('settingsModal').classList.add('active'));
        document.getElementById('closeSettings')?.addEventListener('click', () =>
            document.getElementById('settingsModal').classList.remove('active'));
        document.getElementById('settingsModal')?.addEventListener('click', e => {
            if (e.target.id === 'settingsModal') e.target.classList.remove('active');
        });

        // 설정 옵션들
        const settingHandlers = [
            { id: 'themeOptions', key: 'theme', reload: false },
            { id: 'toolbarOptions', key: 'toolbar', reload: false },
            { id: 'chartTypeOptions', key: 'chartType', reload: true },
            { id: 'stackModeOptions', key: 'stackMode', reload: true },
            { id: 'periodOptions', key: 'period', reload: true, resetOffset: true }
        ];

        settingHandlers.forEach(({ id, key, reload, resetOffset }) => {
            document.querySelectorAll(`#${id} .setting-btn`).forEach(btn => {
                btn.addEventListener('click', () => {
                    this.state.settings[key] = btn.dataset.value;
                    if (resetOffset) this.state.currentPeriodOffset = 0;
                    this.applySettings();
                    this.saveSettings();
                    if (reload) this.loadPlaytimeData();
                });
            });
        });

        document.getElementById('thresholdInput')?.addEventListener('change', e => {
            this.state.settings.calendarThreshold = parseInt(e.target.value) || 10;
            this.saveSettings();
            this.loadCalendarData();
        });

        document.getElementById('showUnregisteredToggle')?.addEventListener('click', () => {
            this.state.settings.showUnregistered = !this.state.settings.showUnregistered;
            this.applySettings();
            this.saveSettings();
            this.loadPlaytimeData();
            if (this.state.calendarData) this.loadCalendarData();
        });

        document.getElementById('showChartIconsToggle')?.addEventListener('click', () => {
            this.state.settings.showChartIcons = !this.state.settings.showChartIcons;
            this.applySettings();
            this.saveSettings();
            if (this.state.playtimeData) this.updatePlaytimeChart(this.state.playtimeData);
        });

        window.addEventListener('resize', () => this.updateTabIndicator());
    }
};

// 플러그인 등록 및 초기화
Chart.register(Dashboard.chartIconPlugin);
Dashboard.init();
