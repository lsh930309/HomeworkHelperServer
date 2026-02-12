// dashboard.js - 대시보드 JavaScript v6

const Dashboard = {
    // === 상태 ===
    state: {
        currentPeriodOffset: 0,
        games: [],
        gameNameMap: {},
        gameColors: {},
        playtimeData: null,
        settings: null,
        iconImages: {},
        iconCache: {},
        dataCache: {},       // { offset: data }
        isNavigating: false,
        selectedGames: new Set(),  // 선택된 게임들
        globalMaxY: 0  // 전체 기간의 Y축 최댓값
    },

    chartInstances: {},  // { canvasId: Chart instance }

    // === 한국 공휴일 데이터 (2025-2027) ===
    koreanHolidays: {
        '2025': ['01-01', '01-28', '01-29', '01-30', '03-01', '03-03', '05-05', '05-06', '06-06', '08-15', '09-06', '09-07', '09-08', '10-03', '10-09', '12-25'],
        '2026': ['01-01', '02-16', '02-17', '02-18', '03-01', '05-05', '05-24', '06-06', '08-15', '09-26', '09-27', '09-28', '10-03', '10-05', '12-25'],
        '2027': ['01-01', '02-06', '02-07', '02-08', '03-01', '05-05', '05-13', '06-06', '08-15', '09-15', '09-16', '09-17', '10-03', '10-04', '12-25']
    },

    // 날짜가 공휴일인지 확인
    isHoliday(dateStr) {
        const [year, month, day] = dateStr.split('-');
        const mmdd = `${month}-${day}`;
        return this.koreanHolidays[year]?.includes(mmdd) || false;
    },

    // 날짜의 요일 확인 (0: 일요일, 6: 토요일)
    getDayOfWeek(dateStr) {
        const date = new Date(dateStr);
        return date.getDay();
    },

    // 날짜 레이블 색상 결정
    getDateLabelColor(dateStr, isDark) {
        const dayOfWeek = this.getDayOfWeek(dateStr);
        const isHoliday = this.isHoliday(dateStr);

        if (dayOfWeek === 0 || isHoliday) {
            return '#dc3545';  // 일요일 또는 공휴일: 빨간색
        } else if (dayOfWeek === 6) {
            return '#0d6efd';  // 토요일: 파란색
        } else {
            return isDark ? '#adb5bd' : '#6c757d';  // 평일: 기본 색상
        }
    },

    // HSL 기반 동적 색상 생성 (Hue 균등분할, S=80%, L=55%)
    generateColors(count) {
        if (count <= 0) return [];
        const S = 80;
        const L = 55;
        const colors = [];
        for (let i = 0; i < count; i++) {
            const H = Math.round((360 / count) * i);
            colors.push(`hsl(${H}, ${S}%, ${L}%)`);
        }
        return colors;
    },

    DEFAULT_SETTINGS: {
        theme: 'auto',
        toolbar: 'top',
        chartType: 'bar',
        stackMode: 'stacked',
        period: 'week',
        showUnregistered: false,
        showChartIcons: true,
        chartIconSize: 64,
        barIconSizeMode: 'auto',
        barIconMargin: 1.5
    },

    // === 초기화 ===
    async init() {
        await this.loadSettings();
        this.initEvents();
        await this.loadGames();
        await this.loadAllPeriodData();
        requestAnimationFrame(() => {
            this.updateTabIndicator();
            this.updateToggleIndicators();
        });
    },

    // === 색상 ===
    assignColorsForGames(gameNames) {
        const sorted = [...gameNames].sort();
        const colors = this.generateColors(sorted.length);
        this.state.gameColors = {};
        sorted.forEach((name, idx) => {
            this.state.gameColors[name] = colors[idx];
        });
    },

    getColorForGame(name) {
        return this.state.gameColors[name] || 'hsl(0, 80%, 55%)';
    },

    // === 아이콘 ===
    async preloadIcon(name, processId, targetSize = null) {
        if (this.state.iconImages[name]) return this.state.iconImages[name];

        const img = new Image();

        const loadPromise = new Promise((resolve) => {
            img.onload = () => {
                this.state.iconImages[name] = img;
                resolve(img);
            };
            img.onerror = () => {
                const color = this.state.gameColors[name] || 'hsl(0, 80%, 55%)';
                const initial = name.charAt(0).toUpperCase();
                const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
                    <rect width="24" height="24" rx="4" fill="${color}"/>
                    <text x="12" y="16" text-anchor="middle" fill="white" font-size="12" font-family="Arial" font-weight="bold">${initial}</text>
                </svg>`;
                img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
                this.state.iconImages[name] = img;
                resolve(img);
            };
        });

        if (processId) {
            const iconSize = targetSize || this.state.settings?.chartIconSize || 64;
            img.src = `/api/dashboard/icons/${processId}?size=${iconSize}`;
        } else {
            const color = this.state.gameColors[name] || 'hsl(0, 80%, 55%)';
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

    // === 차트 최댓값 텍스트 플러그인 ===
    maxValuePlugin: {
        id: 'maxValueLabels',
        afterDatasetsDraw: (chart) => {
            const self = Dashboard;
            const ctx = chart.ctx;
            const stackMode = self.state.settings?.stackMode || 'stacked';
            const datasets = chart.data.datasets;
            const iconSize = self.state.settings?.chartIconSize || 64;

            ctx.save();
            ctx.font = 'bold 11px Satoshi, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'bottom';

            if (stackMode === 'stacked') {
                // 누적 모드: 총합 최댓값 1개
                let maxSum = 0;
                let maxIndex = -1;

                const dataLength = datasets[0]?.data?.length || 0;
                for (let i = 0; i < dataLength; i++) {
                    let sum = 0;
                    datasets.forEach(dataset => {
                        const meta = chart.getDatasetMeta(datasets.indexOf(dataset));
                        if (!meta.hidden && dataset.data[i] !== undefined) {
                            sum += dataset.data[i];
                        }
                    });

                    if (sum > maxSum) {
                        maxSum = sum;
                        maxIndex = i;
                    }
                }

                if (maxIndex >= 0 && maxSum > 0) {
                    // 스택의 최상단 데이터셋 찾기
                    let topDatasetIndex = -1;
                    for (let di = datasets.length - 1; di >= 0; di--) {
                        const meta = chart.getDatasetMeta(di);
                        if (!meta.hidden && datasets[di].data[maxIndex] > 0) {
                            topDatasetIndex = di;
                            break;
                        }
                    }

                    if (topDatasetIndex >= 0) {
                        const meta = chart.getDatasetMeta(topDatasetIndex);
                        const point = meta.data[maxIndex];
                        if (point) {
                            const text = `${maxSum.toFixed(1)}시간`;
                            ctx.fillStyle = '#000000';
                            ctx.strokeStyle = '#ffffff';
                            ctx.lineWidth = 3;

                            // 아이콘 회피: 위쪽 여유 공간 확보
                            const yOffset = self.state.settings?.showChartIcons ? iconSize + 16 : 8;
                            ctx.strokeText(text, point.x, point.y - yOffset);
                            ctx.fillText(text, point.x, point.y - yOffset);
                        }
                    }
                }
            } else {
                // 개별 모드: 각 게임별 최댓값 1개씩
                datasets.forEach((dataset, datasetIndex) => {
                    const meta = chart.getDatasetMeta(datasetIndex);
                    if (meta.hidden) return;

                    let maxValue = 0;
                    let maxIndex = -1;

                    dataset.data.forEach((value, i) => {
                        if (value > maxValue) {
                            maxValue = value;
                            maxIndex = i;
                        }
                    });

                    if (maxIndex >= 0 && maxValue > 0) {
                        const point = meta.data[maxIndex];
                        if (point) {
                            const text = `${maxValue.toFixed(1)}시간`;
                            ctx.fillStyle = dataset.borderColor;
                            ctx.strokeStyle = '#ffffff';
                            ctx.lineWidth = 3;

                            // 아이콘 회피: 위쪽 여유 공간 확보
                            const yOffset = self.state.settings?.showChartIcons ? iconSize + 16 : 8;
                            ctx.strokeText(text, point.x, point.y - yOffset);
                            ctx.fillText(text, point.x, point.y - yOffset);
                        }
                    }
                });
            }

            ctx.restore();
        }
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

            if (chartType === 'bar') return;

            const iconPositions = [];

            datasets.forEach((dataset, datasetIndex) => {
                const meta = chart.getDatasetMeta(datasetIndex);
                if (meta.hidden) return;

                const img = self.state.iconImages[dataset.label];
                if (!img || !img.complete) return;

                const iconSize = self.state.settings?.chartIconSize || 64;
                const data = dataset.data;

                if (chartType === 'line') {
                    const bestIdx = self.findBestIconPosition(data, datasetIndex, datasets, iconPositions, chart);
                    if (bestIdx >= 0 && data[bestIdx] > 0) {
                        const point = meta.data[bestIdx];
                        if (point) {
                            const x = point.x - iconSize / 2;
                            const y = point.y - iconSize - 6;
                            iconPositions.push({ x: point.x, y: point.y, idx: bestIdx });

                            const borderWidth = 2;
                            const borderRadius = 4;
                            ctx.save();
                            ctx.strokeStyle = dataset.borderColor;
                            ctx.lineWidth = borderWidth;
                            ctx.beginPath();
                            ctx.roundRect(
                                x - borderWidth / 2,
                                y - borderWidth / 2,
                                iconSize + borderWidth,
                                iconSize + borderWidth,
                                borderRadius
                            );
                            ctx.stroke();
                            ctx.restore();

                            ctx.drawImage(img, x, y, iconSize, iconSize);
                        }
                    }
                }
            });
        }
    },

    findBestIconPosition(data, datasetIndex, allDatasets, existingPositions, chart) {
        if (!data || data.length === 0) return -1;

        const MIN_X_DISTANCE = 40;
        const MIN_Y_DISTANCE = (this.state.settings?.chartIconSize || 64) + 20;  // 아이콘 크기 + 여유 공간
        const EDGE_BUFFER = 1;

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

        const meta = chart.getDatasetMeta(datasetIndex);
        let bestIdx = -1;
        let bestScore = -Infinity;

        for (let i = EDGE_BUFFER; i < data.length - EDGE_BUFFER; i++) {
            if (data[i] <= 0) continue;
            const point = meta.data[i];
            if (!point) continue;

            // X좌표 겹침 체크 (Y좌표 차이가 충분하면 허용)
            let xOverlapPenalty = 0;
            let hasBlockingOverlap = false;

            existingPositions.forEach(pos => {
                const xDist = Math.abs(pos.x - point.x);
                const yDist = Math.abs(pos.y - point.y);

                if (xDist < MIN_X_DISTANCE) {
                    if (yDist < MIN_Y_DISTANCE) {
                        // Y좌표도 가까우면 완전 차단
                        hasBlockingOverlap = true;
                    } else {
                        // Y좌표가 멀면 페널티만 부여
                        xOverlapPenalty += 50 * (1 - xDist / MIN_X_DISTANCE);
                    }
                }
            });

            if (hasBlockingOverlap) continue;

            let score = 0;
            score += separationScores[i] * 100;
            score += data[i] * 10;
            const centerDist = Math.abs(i - data.length / 2);
            score += (data.length - centerDist) * 5;

            // X좌표 거리 보너스
            let minXDist = Infinity;
            existingPositions.forEach(pos => {
                const xDist = Math.abs(pos.x - point.x);
                minXDist = Math.min(minXDist, xDist);
            });
            if (minXDist !== Infinity) {
                score += Math.min(minXDist, 100) * 2;  // X좌표 겹침 최소화 보너스
            }

            // 인덱스 거리 보너스
            let minIdxDist = Infinity;
            existingPositions.forEach(pos => {
                if (pos.idx !== undefined) {
                    minIdxDist = Math.min(minIdxDist, Math.abs(pos.idx - i));
                }
            });
            if (minIdxDist !== Infinity) score += minIdxDist * 3;

            // X좌표 겹침 페널티 적용
            score -= xOverlapPenalty;

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
        document.querySelectorAll('#barIconSizeOptions .setting-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.value === (s.barIconSizeMode || 'auto'));
        });

        document.getElementById('showUnregisteredToggle')?.classList.toggle('active', s.showUnregistered);
        document.getElementById('showChartIconsToggle')?.classList.toggle('active', s.showChartIcons !== false);

        document.querySelectorAll('.period-toggle-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.period === s.period);
        });

        document.querySelectorAll('.stack-toggle-btn').forEach(b => {
            b.classList.toggle('active', b.dataset.stack === s.stackMode);
        });

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
        requestAnimationFrame(() => this.updateToggleIndicators());
    },

    updateTabIndicator() {
        const tab = document.querySelector('.tab-btn.active');
        const ind = document.getElementById('tabIndicator');
        if (tab && ind) {
            ind.style.width = tab.offsetWidth + 'px';
            ind.style.left = tab.offsetLeft + 'px';
        }
    },

    updateToggleIndicators() {
        // 주간/월간 토글 인디케이터
        const periodBtn = document.querySelector('.period-toggle-btn.active');
        const periodInd = document.getElementById('periodToggleIndicator');
        if (periodBtn && periodInd) {
            periodInd.style.width = periodBtn.offsetWidth + 'px';
            periodInd.style.left = periodBtn.offsetLeft + 'px';
        }

        // 누적/개별 토글 인디케이터
        const stackBtn = document.querySelector('.stack-toggle-btn.active');
        const stackInd = document.getElementById('stackToggleIndicator');
        if (stackBtn && stackInd) {
            stackInd.style.width = stackBtn.offsetWidth + 'px';
            stackInd.style.left = stackBtn.offsetLeft + 'px';
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
            games.forEach(g => {
                this.state.gameNameMap[g.name.toLowerCase()] = g;
            });
            const statGamesEl = document.getElementById('statGames');
            statGamesEl.textContent = games.length.toString();
            const unitSpan = document.createElement('span');
            unitSpan.className = 'stat-unit';
            unitSpan.textContent = '개';
            statGamesEl.appendChild(unitSpan);
        }
    },

    // === 전체 기간 Y축 최댓값 계산 ===
    calculateGlobalMaxY(offsets) {
        const stackMode = this.state.settings?.stackMode || 'stacked';
        let maxY = 0;

        // selectedGames가 비어있으면 모든 게임을 포함
        const useAllGames = this.state.selectedGames.size === 0;

        offsets.forEach(o => {
            const data = this.state.dataCache[o];
            if (!data?.games || !data?.dates) return;

            const dateCount = data.dates.length;
            for (let i = 0; i < dateCount; i++) {
                if (stackMode === 'stacked') {
                    // 누적 모드: 각 날짜별 모든 게임의 합계
                    let sum = 0;
                    Object.keys(data.games).forEach(name => {
                        if (useAllGames || this.state.selectedGames.has(name)) {
                            sum += (data.games[name].minutes[i] || 0) / 60;
                        }
                    });
                    maxY = Math.max(maxY, sum);
                } else {
                    // 개별 모드: 각 게임별 최댓값
                    Object.keys(data.games).forEach(name => {
                        if (useAllGames || this.state.selectedGames.has(name)) {
                            const value = (data.games[name].minutes[i] || 0) / 60;
                            maxY = Math.max(maxY, value);
                        }
                    });
                }
            }
        });

        this.state.globalMaxY = Math.ceil(maxY * 1.1);  // 10% 여유 공간
    },

    // === 데이터 로딩 (3기간 동시) ===
    async loadAllPeriodData() {
        const offset = this.state.currentPeriodOffset;
        const period = this.state.settings?.period || 'week';
        const showUnreg = this.state.settings?.showUnregistered ? 'true' : 'false';

        // 현재 및 인접 기간 데이터 가져오기 (캐시된 것은 건너뜀)
        const offsets = [offset - 1, offset, offset + 1];
        await Promise.all(offsets.map(async (o) => {
            if (this.state.dataCache[o] !== undefined) return;
            const data = await this.fetchAPI(
                `/api/dashboard/playtime?period=${period}&offset=${o}&merge_names=true&show_unregistered=${showUnreg}`
            );
            this.state.dataCache[o] = data || { games: {}, dates: [], stats: {} };
        }));

        // 표시 중인 3기간의 모든 게임 이름 수집 → 전역 색상 할당
        const visibleGameNames = new Set();
        this.state.games.forEach(g => visibleGameNames.add(g.name));
        offsets.forEach(o => {
            const data = this.state.dataCache[o];
            if (data?.games) Object.keys(data.games).forEach(n => visibleGameNames.add(n));
        });
        this.assignColorsForGames([...visibleGameNames]);

        // 3기간 아이콘 프리로드
        const targetSize = this.state.settings?.chartIconSize || 64;
        const iconPromises = [];
        offsets.forEach(o => {
            const data = this.state.dataCache[o];
            if (data?.games) {
                Object.keys(data.games).forEach(name => {
                    if (!this.state.iconImages[name]) {
                        iconPromises.push(this.preloadIcon(name, data.games[name].process_id, targetSize));
                    }
                });
            }
        });
        await Promise.all(iconPromises);

        // 현재 데이터 설정
        this.state.playtimeData = this.state.dataCache[offset];

        // 전체 기간의 Y축 최댓값 계산
        this.calculateGlobalMaxY(offsets);

        // 3개 차트 모두 렌더링 (네비게이션 중이면 애니메이션 비활성화)
        this.renderAllCharts(!this.state.isNavigating);
        this.updateStats(this.state.dataCache[offset]);
        this.updatePeriodLabel();

        // 오래된 캐시 정리
        Object.keys(this.state.dataCache).forEach(key => {
            if (Math.abs(parseInt(key) - offset) > 3) {
                delete this.state.dataCache[key];
            }
        });
    },

    updateStats(data) {
        if (data?.stats) {
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

    // === 차트 렌더링 ===
    renderChartOnCanvas(canvasId, data, animate = true) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;
        const ctx = canvas.getContext('2d');

        // 중앙 차트만 X축 레이블 표시
        const isMainChart = canvasId === 'playtimeChart';

        if (this.chartInstances[canvasId]) {
            this.chartInstances[canvasId].destroy();
            this.chartInstances[canvasId] = null;
        }

        const chartType = this.state.settings?.chartType || 'bar';
        const stackMode = this.state.settings?.stackMode || 'stacked';

        const datasets = [];
        const gameNames = Object.keys(data?.games || {}).sort();

        // 선택된 게임만 필터링 (비어있으면 모든 게임)
        const selectedGameNames = this.state.selectedGames.size === 0
            ? gameNames
            : gameNames.filter(name => this.state.selectedGames.has(name));

        selectedGameNames.forEach((name, idx) => {
            const gdata = data.games[name];
            const color = this.getColorForGame(name);

            const bgOpacity = chartType === 'bar' ? 0.8 : (stackMode === 'stacked' ? 0.5 : 0.2);
            const bg = color.replace('hsl(', 'hsla(').replace(')', `, ${bgOpacity})`);

            // 누적 모드: 레이어드 fill (무지개떡 방식)
            let fillMode = false;
            if (chartType === 'line' && stackMode === 'stacked') {
                fillMode = idx === 0 ? 'origin' : '-1';
            }

            datasets.push({
                label: name,
                data: gdata.minutes.map(m => m / 60),
                backgroundColor: bg,
                borderColor: color,
                borderWidth: 2,
                fill: fillMode,
                tension: 0.4,
                pointRadius: chartType === 'line' ? 4 : 0,
                pointBackgroundColor: color
            });
        });

        const theme = document.documentElement.getAttribute('data-theme');
        const isDark = theme === 'dark' || (!theme && window.matchMedia('(prefers-color-scheme: dark)').matches);
        const gridColor = isDark ? '#333333' : '#e9ecef';
        const textColor = isDark ? '#adb5bd' : '#6c757d';

        const dates = data?.dates || [];
        const labels = dates.map(d => {
            const p = d.split('-');
            return `${parseInt(p[1])}/${parseInt(p[2])}`;
        });

        this.chartInstances[canvasId] = new Chart(ctx, {
            type: chartType,
            data: { labels, datasets },
            plugins: [this.maxValuePlugin, this.chartIconPlugin],
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: animate ? {
                    duration: 400,
                    easing: 'easeInOutQuart'
                } : false,
                interaction: { intersect: false, mode: 'index' },
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        enabled: canvasId === 'playtimeChart',
                        callbacks: { label: c => `${c.dataset.label}: ${c.parsed.y.toFixed(1)}시간` }
                    }
                },
                scales: {
                    x: {
                        stacked: stackMode === 'stacked',
                        grid: {
                            color: gridColor,
                            drawBorder: false
                        },
                        ticks: {
                            display: isMainChart,
                            color: (context) => {
                                const index = context.index;
                                if (index >= 0 && index < dates.length) {
                                    return this.getDateLabelColor(dates[index], isDark);
                                }
                                return textColor;
                            },
                            font: { size: 10 }
                        }
                    },
                    y: {
                        stacked: stackMode === 'stacked',
                        beginAtZero: true,
                        max: this.state.globalMaxY > 0 ? this.state.globalMaxY : undefined,
                        grid: {
                            color: gridColor,
                            drawBorder: false
                        },
                        ticks: {
                            display: false  // Y축 레이블 숨김
                        }
                    }
                },
                layout: {
                    padding: {
                        left: 0,
                        right: 0,
                        top: this.state.settings?.showChartIcons ? 80 : 20,
                        bottom: isMainChart ? 0 : 0
                    }
                }
            }
        });
    },

    updateLegend(data) {
        const legendEl = document.getElementById('chartLegend');
        if (!legendEl) return;
        legendEl.innerHTML = '';

        const gameNames = Object.keys(data?.games || {}).sort();

        // 초기 선택 상태 설정 (모든 게임 선택)
        if (this.state.selectedGames.size === 0) {
            gameNames.forEach(name => this.state.selectedGames.add(name));
        }

        gameNames.forEach(name => {
            const color = this.getColorForGame(name);
            const isSelected = this.state.selectedGames.has(name);

            const item = document.createElement('div');
            item.className = 'legend-item';

            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.className = 'legend-checkbox';
            checkbox.checked = isSelected;

            const toggleSelection = () => {
                if (checkbox.checked) {
                    checkbox.checked = false;
                    this.state.selectedGames.delete(name);
                } else {
                    checkbox.checked = true;
                    this.state.selectedGames.add(name);
                }
                this.state.dataCache = {};
                this.loadAllPeriodData();
            };

            checkbox.addEventListener('change', (e) => {
                e.stopPropagation();
                if (checkbox.checked) {
                    this.state.selectedGames.add(name);
                } else {
                    this.state.selectedGames.delete(name);
                }
                this.state.dataCache = {};
                this.loadAllPeriodData();
            });

            // 항목 전체 클릭 시 토글
            item.addEventListener('click', (e) => {
                if (e.target !== checkbox) {
                    toggleSelection();
                }
            });

            const colorDot = document.createElement('div');
            colorDot.className = 'legend-color';
            colorDot.style.background = color;

            const iconContainer = document.createElement('div');
            iconContainer.className = 'legend-icon';

            const iconImg = this.state.iconImages[name];
            if (iconImg && iconImg.complete) {
                const img = document.createElement('img');
                img.src = iconImg.src;
                img.alt = name;
                iconContainer.appendChild(img);
            } else {
                iconContainer.style.background = color;
                const fallback = document.createElement('span');
                fallback.className = 'fallback';
                fallback.textContent = name.charAt(0).toUpperCase();
                iconContainer.appendChild(fallback);
            }

            const nameSpan = document.createElement('span');
            nameSpan.textContent = name;

            item.appendChild(checkbox);
            item.appendChild(colorDot);
            item.appendChild(iconContainer);
            item.appendChild(nameSpan);
            legendEl.appendChild(item);
        });
    },

    updateYAxis() {
        const yAxisEl = document.getElementById('chartYAxis');
        if (!yAxisEl) return;

        yAxisEl.innerHTML = '';
        const maxY = this.state.globalMaxY || 10;
        const steps = 5;

        for (let i = steps; i >= 0; i--) {
            const value = (maxY / steps * i).toFixed(0);
            const label = document.createElement('div');
            label.textContent = `${value}h`;
            label.style.lineHeight = '1';
            yAxisEl.appendChild(label);
        }
    },

    renderAllCharts(animate = true) {
        const offset = this.state.currentPeriodOffset;
        this.renderChartOnCanvas('prevChart', this.state.dataCache[offset - 1], animate);
        this.renderChartOnCanvas('playtimeChart', this.state.dataCache[offset], animate);
        this.renderChartOnCanvas('nextChart', this.state.dataCache[offset + 1], animate);
        this.updateLegend(this.state.dataCache[offset]);
        this.updateYAxis();
    },

    // === 스와이프 네비게이션 (3패널 슬라이더) ===
    initSwipeNavigation() {
        const chartCard = document.querySelector('#playtime .card');
        const slider = document.getElementById('chartSlider');
        if (!chartCard || !slider) return;

        let startX = 0;
        let currentDragX = 0;
        let isDragging = false;
        let isSwipe = false;
        const THRESHOLD = 80;
        const DEAD_ZONE = 8;

        chartCard.style.touchAction = 'pan-y';
        chartCard.style.userSelect = 'none';

        chartCard.addEventListener('pointerdown', (e) => {
            if (this.state.isNavigating) return;
            if (e.target.closest('.chart-controls') || e.target.closest('.card-header') || e.target.closest('.chart-period-toggle')) return;
            isDragging = true;
            isSwipe = false;
            startX = e.clientX;
            currentDragX = 0;
            chartCard.setPointerCapture(e.pointerId);
            slider.classList.remove('animating');
        });

        chartCard.addEventListener('pointermove', (e) => {
            if (!isDragging) return;
            currentDragX = e.clientX - startX;

            if (!isSwipe && Math.abs(currentDragX) < DEAD_ZONE) return;
            isSwipe = true;

            // 경계 체크: 이전/다음 데이터 존재 여부
            const offset = this.state.currentPeriodOffset;
            const prevData = this.state.dataCache[offset - 1];
            const nextData = this.state.dataCache[offset + 1];
            const canGoPrev = prevData && Object.keys(prevData.games || {}).length > 0;
            const canGoNext = nextData && Object.keys(nextData.games || {}).length > 0;

            let adjustedDrag = currentDragX;
            if ((currentDragX > 0 && !canGoPrev) || (currentDragX < 0 && !canGoNext)) {
                adjustedDrag = currentDragX * 0.15;  // 고무줄 효과
            }

            const containerWidth = chartCard.querySelector('.chart-container').offsetWidth;
            const dragPercent = (adjustedDrag / containerWidth) * 33.333;
            slider.style.transform = `translateX(${-33.333 + dragPercent}%)`;
        });

        const endDrag = () => {
            if (!isDragging) return;
            isDragging = false;

            if (!isSwipe) return;

            slider.classList.add('animating');

            const offset = this.state.currentPeriodOffset;
            const prevData = this.state.dataCache[offset - 1];
            const nextData = this.state.dataCache[offset + 1];
            const canGoPrev = prevData && Object.keys(prevData.games || {}).length > 0;
            const canGoNext = nextData && Object.keys(nextData.games || {}).length > 0;

            if (currentDragX > THRESHOLD && canGoPrev) {
                // 이전으로: 슬라이더를 오른쪽으로 완전히 이동
                slider.style.transform = 'translateX(0%)';
                slider.addEventListener('transitionend', () => {
                    this.navigatePeriod(-1);
                }, { once: true });
            } else if (currentDragX < -THRESHOLD && canGoNext) {
                // 다음으로: 슬라이더를 왼쪽으로 완전히 이동
                slider.style.transform = 'translateX(-66.666%)';
                slider.addEventListener('transitionend', () => {
                    this.navigatePeriod(1);
                }, { once: true });
            } else {
                // 원위치 스냅백
                slider.style.transform = 'translateX(-33.333%)';
            }

            currentDragX = 0;
        };

        chartCard.addEventListener('pointerup', endDrag);
        chartCard.addEventListener('pointercancel', endDrag);
    },

    async navigatePeriod(direction) {
        this.state.isNavigating = true;
        this.state.currentPeriodOffset += direction;

        // 슬라이더 즉시 중앙으로 리셋 (애니메이션 없이)
        const slider = document.getElementById('chartSlider');
        slider.classList.remove('animating');
        slider.style.transform = 'translateX(-33.333%)';

        await this.loadAllPeriodData();
        this.state.isNavigating = false;
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
            });
        });

        // 스와이프 네비게이션
        this.initSwipeNavigation();

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
            { id: 'themeOptions', key: 'theme', action: 'none' },
            { id: 'toolbarOptions', key: 'toolbar', action: 'none' }
        ];

        settingHandlers.forEach(({ id, key, action }) => {
            document.querySelectorAll(`#${id} .setting-btn`).forEach(btn => {
                btn.addEventListener('click', () => {
                    this.state.settings[key] = btn.dataset.value;
                    this.applySettings();
                    this.saveSettings();
                });
            });
        });

        document.getElementById('showUnregisteredToggle')?.addEventListener('click', () => {
            this.state.settings.showUnregistered = !this.state.settings.showUnregistered;
            this.applySettings();
            this.saveSettings();
            this.state.dataCache = {};
            this.loadAllPeriodData();
        });

        document.getElementById('showChartIconsToggle')?.addEventListener('click', () => {
            this.state.settings.showChartIcons = !this.state.settings.showChartIcons;
            this.applySettings();
            this.saveSettings();
            this.renderAllCharts();
        });

        // 아이콘 크기 설정
        document.querySelectorAll('#iconSizeOptions .setting-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                if (btn.dataset.value === 'custom') {
                    const customInput = document.getElementById('customIconSizeInput');
                    const customValue = parseInt(customInput?.value || '64');
                    this.state.settings.chartIconSize = Math.max(1, Math.min(256, customValue));
                } else {
                    this.state.settings.chartIconSize = parseInt(btn.dataset.value);
                }
                this.applySettings();
                this.saveSettings();
                this.state.iconImages = {};
                this.state.dataCache = {};
                this.loadAllPeriodData();
            });
        });

        document.getElementById('customIconSizeInput')?.addEventListener('change', e => {
            const value = parseInt(e.target.value) || 64;
            const clamped = Math.max(1, Math.min(256, value));
            e.target.value = clamped;
            this.state.settings.chartIconSize = clamped;
            this.saveSettings();
            this.state.iconImages = {};
            this.state.dataCache = {};
            this.loadAllPeriodData();
        });

        // 막대 차트 아이콘 크기 모드 설정
        document.querySelectorAll('#barIconSizeOptions .setting-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                this.state.settings.barIconSizeMode = btn.dataset.value;
                this.applySettings();
                this.saveSettings();
                this.renderAllCharts();
            });
        });

        // 차트 기간 토글
        document.querySelectorAll('.period-toggle-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const newPeriod = btn.dataset.period;
                if (this.state.settings.period === newPeriod) return;

                document.querySelectorAll('.period-toggle-btn').forEach(b => {
                    b.classList.toggle('active', b.dataset.period === newPeriod);
                });

                this.updateToggleIndicators();

                this.state.settings.period = newPeriod;
                this.state.currentPeriodOffset = 0;
                this.saveSettings();
                this.state.dataCache = {};
                this.loadAllPeriodData();
            });
        });

        // 차트 누적/개별 토글
        document.querySelectorAll('.stack-toggle-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const newStack = btn.dataset.stack;
                if (this.state.settings.stackMode === newStack) return;

                document.querySelectorAll('.stack-toggle-btn').forEach(b => {
                    b.classList.toggle('active', b.dataset.stack === newStack);
                });

                this.updateToggleIndicators();

                this.state.settings.stackMode = newStack;
                this.saveSettings();
                this.state.dataCache = {};
                this.loadAllPeriodData();
            });
        });

        window.addEventListener('resize', () => {
            this.updateTabIndicator();
            this.updateToggleIndicators();
        });
    }
};

// 플러그인 등록 및 초기화
Chart.register(Dashboard.maxValuePlugin);
Chart.register(Dashboard.chartIconPlugin);
Dashboard.init();
