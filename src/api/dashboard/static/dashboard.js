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
        showChartIcons: true,
        chartIconSize: 64,
        barIconSizeMode: 'auto',  // 'auto' | 'fixed'
        barIconMargin: 1.5        // percentage margin
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
    async preloadIcon(name, processId, targetSize = null) {
        // 캐시 키는 항상 name으로 통일 (chartIconPlugin에서 dataset.label로 찾음)
        if (this.state.iconImages[name]) return this.state.iconImages[name];

        const img = new Image();

        // 이미지 로드 완료 대기를 위한 Promise
        const loadPromise = new Promise((resolve) => {
            img.onload = () => {
                this.state.iconImages[name] = img;
                resolve(img);
            };
            img.onerror = () => {
                // 실패 시 폴백 SVG
                const color = this.state.gameColors[name] || this.COLORS[0];
                const initial = name.charAt(0).toUpperCase();
                const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
                    <rect width="24" height="24" rx="4" fill="${color}"/>
                    <text x="12" y="16" text-anchor="middle" fill="white" font-size="12" font-family="Arial" font-weight="bold">${initial}</text>
                </svg>`;
                img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
                // 재귀 방지를 위해 바로 저장
                this.state.iconImages[name] = img;
                resolve(img);
            };
        });

        // 실제 아이콘 먼저 시도
        if (processId) {
            const iconSize = targetSize || this.state.settings?.chartIconSize || 64;
            img.src = `/api/dashboard/icons/${processId}?size=${iconSize}`;
        } else {
            // processId 없으면 바로 폴백
            const color = this.state.gameColors[name] || this.COLORS[0];
            const initial = name.charAt(0).toUpperCase();
            const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
                <rect width="24" height="24" rx="4" fill="${color}"/>
                <text x="12" y="16" text-anchor="middle" fill="white" font-size="12" font-family="Arial" font-weight="bold">${initial}</text>
            </svg>`;
            img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
            this.state.iconImages[name] = img;
        }

        return loadPromise;
    },


    // === 차트 아이콘 플러그인 ===
    chartIconPlugin: {
        id: 'chartIcons',
        afterDraw: (chart) => {
            const self = Dashboard;
            if (!self.state.settings?.showChartIcons) return;

            const ctx = chart.ctx;
            const chartType = chart.config.type;
            const datasets = chart.data.datasets;

            // 막대 그래프에서는 아이콘 표시 안 함 (범례에만 표시)
            if (chartType === 'bar') return;

            // 아이콘 위치 계산 (겹침 방지)
            const iconPositions = [];

            datasets.forEach((dataset, datasetIndex) => {
                const meta = chart.getDatasetMeta(datasetIndex);
                if (meta.hidden) return;

                const img = self.state.iconImages[dataset.label];
                if (!img || !img.complete) return;

                const iconSize = self.state.settings?.chartIconSize || 64;
                const data = dataset.data;

                if (chartType === 'line') {
                    // 선형: 최적 위치 계산
                    const bestIdx = self.findBestIconPosition(data, datasetIndex, datasets, iconPositions, chart);
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
    findBestIconPosition(data, datasetIndex, allDatasets, existingPositions, chart) {
        if (!data || data.length === 0) return -1;

        // 설정
        const MIN_X_DISTANCE = 40;  // 픽셀 단위 최소 거리
        const EDGE_BUFFER = 1;      // 첫/마지막 인덱스 피하기

        // 1단계: 각 위치의 시각적 분리도 점수 계산
        const separationScores = data.map((value, i) => {
            if (value <= 0) return -Infinity;

            let minGap = Infinity;
            allDatasets.forEach((ds, idx) => {
                if (idx !== datasetIndex && ds.data[i] !== undefined) {
                    minGap = Math.min(minGap, Math.abs(value - ds.data[i]));
                }
            });
            return minGap;
        });

        // 2단계: 메타데이터로 좌표 접근
        const meta = chart.getDatasetMeta(datasetIndex);

        // 3단계: 제약조건을 만족하는 최적 위치 찾기
        let bestIdx = -1;
        let bestScore = -Infinity;

        for (let i = EDGE_BUFFER; i < data.length - EDGE_BUFFER; i++) {
            if (data[i] <= 0) continue;

            const point = meta.data[i];
            if (!point) continue;

            // 하드 제약: x축 겹침 확인
            const hasOverlap = existingPositions.some(pos =>
                Math.abs(pos.x - point.x) < MIN_X_DISTANCE
            );
            if (hasOverlap) continue;

            // 점수: 시각적 분리 우선
            let score = 0;
            score += separationScores[i] * 100;  // 시각적 분리 (최우선)
            score += data[i] * 10;                // 값 크기

            // 중앙 위치 선호
            const centerDist = Math.abs(i - data.length / 2);
            score += (data.length - centerDist) * 5;

            // 기존 아이콘과의 간격
            let minDist = Infinity;
            existingPositions.forEach(pos => {
                if (pos.idx !== undefined) {
                    minDist = Math.min(minDist, Math.abs(pos.idx - i));
                }
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

        document.querySelectorAll('#themeOptions .setting-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.value === s.theme);
        });
        document.querySelectorAll('#toolbarOptions .setting-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.value === s.toolbar);
        });
        document.querySelectorAll('#chartTypeOptions .setting-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.value === s.chartType);
        });
        document.querySelectorAll('#stackModeOptions .setting-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.value === s.stackMode);
        });
        document.querySelectorAll('#periodOptions .setting-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.value === s.period);
        });
        document.querySelectorAll('#barIconSizeOptions .setting-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.value === (s.barIconSizeMode || 'auto'));
        });

        const thresholdInput = document.getElementById('thresholdInput');
        if (thresholdInput) thresholdInput.value = s.calendarThreshold || 10;

        document.getElementById('showUnregisteredToggle')?.classList.toggle('active', s.showUnregistered);
        document.getElementById('showChartIconsToggle')?.classList.toggle('active', s.showChartIcons !== false);

        // 아이콘 크기 설정
        const iconSize = s.chartIconSize || 64;
        const isCustomSize = ![32, 64, 96, 128].includes(iconSize);

        document.querySelectorAll('#iconSizeOptions .setting-btn').forEach(b => {
            if (b.dataset.value === 'custom') {
                b.classList.toggle('active', isCustomSize);
            } else {
                b.classList.toggle('active', b.dataset.value === String(iconSize));
            }
        });

        const customWrapper = document.getElementById('customIconSizeWrapper');
        const customInput = document.getElementById('customIconSizeInput');
        if (customWrapper && customInput) {
            customWrapper.style.display = isCustomSize ? 'block' : 'none';
            customInput.value = iconSize;
        }

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
            const statGamesEl = document.getElementById('statGames');
            statGamesEl.textContent = games.length.toString();
            const unitSpan = document.createElement('span');
            unitSpan.className = 'stat-unit';
            unitSpan.textContent = '개';
            statGamesEl.appendChild(unitSpan);
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

            // 색상 할당 및 아이콘 프리로드 (완료 대기)
            const gameNames = Object.keys(data.games || {});
            const targetSize = this.state.settings?.chartIconSize || 64;
            const iconPromises = gameNames.map((name, idx) => {
                this.getColorForGame(name, idx);
                return this.preloadIcon(name, data.games[name].process_id, targetSize);
            });

            // 모든 아이콘 로드 완료 후 차트 렌더링
            await Promise.all(iconPromises);
            this.updatePlaytimeChart(data);
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
            const statTodayEl = document.getElementById('statToday');
            statTodayEl.textContent = Math.round(data.stats.today_minutes || 0).toString();
            const todayUnit = document.createElement('span');
            todayUnit.className = 'stat-unit';
            todayUnit.textContent = '분';
            statTodayEl.appendChild(todayUnit);

            const statWeekEl = document.getElementById('statWeek');
            statWeekEl.textContent = ((data.stats.week_minutes || 0) / 60).toFixed(1);
            const weekUnit = document.createElement('span');
            weekUnit.className = 'stat-unit';
            weekUnit.textContent = '시간';
            statWeekEl.appendChild(weekUnit);

            const statMonthEl = document.getElementById('statMonth');
            statMonthEl.textContent = ((data.stats.month_minutes || 0) / 60).toFixed(1);
            const monthUnit = document.createElement('span');
            monthUnit.className = 'stat-unit';
            monthUnit.textContent = '시간';
            statMonthEl.appendChild(monthUnit);
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

            // 범례 아이템 (아이콘 포함)
            const item = document.createElement('div');
            item.className = 'legend-item';

            const iconContainer = document.createElement('div');
            iconContainer.className = 'legend-icon';
            iconContainer.style.background = color;

            const iconImg = this.state.iconImages[name];
            if (iconImg && iconImg.complete) {
                // 아이콘 이미지가 로드된 경우
                const img = document.createElement('img');
                img.src = iconImg.src;
                img.alt = name;
                img.style.width = '100%';
                img.style.height = '100%';
                img.style.objectFit = 'cover';
                img.style.borderRadius = '4px';
                iconContainer.appendChild(img);
            } else {
                // 폴백: 색상 + 이니셜
                const fallback = document.createElement('span');
                fallback.className = 'fallback';
                fallback.textContent = name.charAt(0).toUpperCase();
                iconContainer.appendChild(fallback);
            }

            const nameSpan = document.createElement('span');
            nameSpan.textContent = name;

            item.appendChild(iconContainer);
            item.appendChild(nameSpan);
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
        headers.forEach(h => {
            grid.appendChild(h);
        });

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

            const dateSpan = document.createElement('span');
            dateSpan.className = 'date';
            dateSpan.textContent = day;
            cell.appendChild(dateSpan);

            const iconsDiv = document.createElement('div');
            iconsDiv.className = 'icons';

            if (dayData?.games) {
                const showUnreg = this.state.settings?.showUnregistered;
                const gamesFiltered = showUnreg ? dayData.games :
                    dayData.games.filter(g => this.state.gameNameMap[g.name.toLowerCase()]);

                gamesFiltered.slice(0, 9).forEach(g => {
                    const gameInfo = this.state.gameNameMap[g.name.toLowerCase()];
                    const processId = gameInfo?.id || g.id;

                    const img = document.createElement('img');
                    img.className = 'icon';
                    img.src = `/api/dashboard/icons/${processId}?size=64`;
                    img.alt = g.name;
                    img.title = `${g.name}: ${Math.round(g.minutes)}분`;
                    img.loading = 'lazy';
                    img.onerror = function() { this.style.display = 'none'; };

                    iconsDiv.appendChild(img);
                });
            }

            cell.appendChild(iconsDiv);
            grid.appendChild(cell);
        }

        // 아이콘 크기 자동 조정 (렌더링 완료 후)
        requestAnimationFrame(() => this.adjustCalendarIconSizes());
    },

    adjustCalendarIconSizes() {
        const cells = document.querySelectorAll('.calendar-day:not(.empty)');
        if (cells.length === 0) return;

        // 첫 번째 셀의 실제 크기 측정
        const sampleCell = cells[0];
        const cellWidth = sampleCell.offsetWidth;
        const cellHeight = sampleCell.offsetHeight;

        // 날짜 텍스트 높이 측정
        const dateEl = sampleCell.querySelector('.date');
        const dateHeight = dateEl ? dateEl.offsetHeight : 14;

        // 아이콘 영역 가용 크기 계산
        const GRID_COLS = 3;
        const GAP = 1;
        const PADDING_H = 4;  // 좌우 패딩
        const PADDING_V = 8;  // 상하 패딩
        const DATE_MARGIN = 2;  // 날짜와 아이콘 사이 여백

        // 가용 너비/높이
        const availableWidth = cellWidth - (PADDING_H * 2);
        const availableHeight = cellHeight - dateHeight - DATE_MARGIN - (PADDING_V * 2);

        // 아이콘 크기 계산 (3x3 그리드 기준)
        const iconWidthByWidth = Math.floor((availableWidth - (GRID_COLS - 1) * GAP) / GRID_COLS);
        const iconHeightByHeight = Math.floor((availableHeight - (GRID_COLS - 1) * GAP) / GRID_COLS);

        // 작은 값 선택 (정사각형 유지) + 최대/최소 제한
        let iconSize = Math.min(iconWidthByWidth, iconHeightByHeight);
        iconSize = Math.max(12, Math.min(24, iconSize));  // 12px ~ 24px 범위

        // 모든 아이콘에 크기 적용
        document.querySelectorAll('.calendar-day .icon').forEach(icon => {
            icon.style.width = `${iconSize}px`;
            icon.style.height = `${iconSize}px`;
        });
    },

    // === 이벤트 ===
    initEvents() {
        // 탭 전환
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.tab-btn').forEach(b => {
                    b.classList.remove('active');
                });
                document.querySelectorAll('.tab-panel').forEach(p => {
                    p.classList.remove('active');
                });
                btn.classList.add('active');
                document.getElementById(btn.dataset.tab).classList.add('active');
                this.updateTabIndicator();
                if (btn.dataset.tab === 'calendar') {
                    this.loadCalendarData();
                    // 탭 전환 시 아이콘 크기 조정
                    requestAnimationFrame(() => this.adjustCalendarIconSizes());
                }
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

        // 아이콘 크기 설정
        document.querySelectorAll('#iconSizeOptions .setting-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                if (btn.dataset.value === 'custom') {
                    // 사용자 지정 모드 활성화
                    const customInput = document.getElementById('customIconSizeInput');
                    const customValue = parseInt(customInput?.value || '64');
                    this.state.settings.chartIconSize = Math.max(1, Math.min(256, customValue));
                } else {
                    // 프리셋 크기 선택
                    this.state.settings.chartIconSize = parseInt(btn.dataset.value);
                }
                this.applySettings();
                this.saveSettings();
                if (this.state.playtimeData) this.updatePlaytimeChart(this.state.playtimeData);
            });
        });

        document.getElementById('customIconSizeInput')?.addEventListener('change', e => {
            const value = parseInt(e.target.value) || 64;
            const clamped = Math.max(1, Math.min(256, value));
            e.target.value = clamped;
            this.state.settings.chartIconSize = clamped;
            this.saveSettings();
            if (this.state.playtimeData) this.updatePlaytimeChart(this.state.playtimeData);
        });

        // 막대 차트 아이콘 크기 모드 설정
        document.querySelectorAll('#barIconSizeOptions .setting-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this.state.settings.barIconSizeMode = btn.dataset.value;
                this.applySettings();
                this.saveSettings();
                if (this.state.playtimeData) this.updatePlaytimeChart(this.state.playtimeData);
            });
        });

        window.addEventListener('resize', () => {
            this.updateTabIndicator();
            // 달력이 활성화되어 있으면 아이콘 크기 재조정
            if (document.getElementById('calendar').classList.contains('active')) {
                this.adjustCalendarIconSizes();
            }
        });
    }
};

// 플러그인 등록 및 초기화
Chart.register(Dashboard.chartIconPlugin);
Dashboard.init();
