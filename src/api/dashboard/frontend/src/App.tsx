import React from 'react';
import * as echarts from 'echarts';
import './style.css';

type Range = { start: string; end: string };
type GameInsight = {
  smart_average_session_seconds?: number;
  longest_normal_session_seconds?: number;
  very_short_session_count?: number;
  long_session_count?: number;
  long_session_threshold_seconds?: number;
  long_session_recent_date?: string | null;
  long_session_average_interval_days?: number | null;
  weekly_average_seconds?: number;
  favorite_weekday?: number | null;
  favorite_hour?: number | null;
  weekday_weekend_preference?: string;
};
type GameMetric = {
  game_key: string;
  display_name: string;
  process_ids?: string[];
  process_id?: string;
  process_name?: string;
  icon_process_id?: string | null;
  color?: string;
  total_seconds: number;
  share?: number;
  insights?: GameInsight;
};
type ApiData = { timeline: any; summary: any; patterns: any; sessions: any };
type ApiRange = { start: string; end: string };

const WEEKDAYS = ['월', '화', '수', '목', '금', '토', '일'];
const fmtDate = (d: Date) => d.toISOString().slice(0, 10);
const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const secondsToText = (seconds = 0) => { const mins = Math.round(seconds / 60); const h = Math.floor(mins / 60); const m = mins % 60; return h ? `${h}시간 ${m}분` : `${m}분`; };
const hourLabel = (hour: number) => `${hour < 12 ? 'AM' : 'PM'} ${hour % 12 === 0 ? 0 : hour % 12}시`;
const preferenceText = (value?: string) => ({ weekday: '평일 선호', weekend: '주말 선호', balanced: '평일/주말 균형', none: '데이터 없음' }[value || 'none'] || '데이터 없음');
const deltaText = (delta: any) => !delta ? '이전 기간 데이터 없음' : delta.percent === null ? (delta.current ? '이전 기간 0분' : '변화 없음') : `${delta.change > 0 ? '+' : ''}${delta.percent}%`;
const fetchJson = async (url: string) => { const response = await fetch(url); const contentType = response.headers.get('content-type') || ''; if (!contentType.includes('application/json')) throw new Error(`API가 JSON이 아닌 응답을 반환했습니다 (${response.status})`); const body = await response.json(); if (!response.ok || body.detail) throw new Error(body.detail || `API 요청 실패 (${response.status})`); return body; };
const iconUrl = (g: GameMetric, size = 128) => `/api/dashboard/icons/${g.icon_process_id || g.process_ids?.[0] || g.process_id}?size=${size}`;

function EChart({ option, className = 'chart', onBrush }: { option: echarts.EChartsCoreOption; className?: string; onBrush?: (event: any) => void }) {
  const ref = React.useRef<HTMLDivElement | null>(null); const chart = React.useRef<echarts.ECharts | null>(null);
  React.useEffect(() => { if (!ref.current) return; chart.current = echarts.init(ref.current); const resize = () => chart.current?.resize(); window.addEventListener('resize', resize); return () => { window.removeEventListener('resize', resize); chart.current?.dispose(); }; }, []);
  React.useEffect(() => { chart.current?.setOption(option, true); }, [option]);
  React.useEffect(() => { if (!chart.current || !onBrush) return; chart.current.on('brushSelected', onBrush); return () => { chart.current?.off('brushSelected', onBrush); }; }, [onBrush]);
  return <div ref={ref} className={className} />;
}
function Metric({ label, value, delta }: { label: string; value: string; delta?: any }) { return <section className="card metric"><div className="label">{label}</div><div className="value">{value}</div><div className="delta">{deltaText(delta)}</div></section>; }
function InsightLine({ label, value }: { label: string; value: React.ReactNode }) { return <div className="insight-line"><span>{label}</span><strong>{value}</strong></div>; }

export default function App() {
  const today = React.useMemo(() => new Date(), []);
  const [range, setRange] = React.useState<Range>({ start: fmtDate(addDays(today, -29)), end: fmtDate(today) });
  const [gameId, setGameId] = React.useState('all');
  const [chartMode, setChartMode] = React.useState<'area' | 'bar'>('area');
  const [allGames, setAllGames] = React.useState<GameMetric[]>([]);
  const [data, setData] = React.useState<ApiData | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [drawer, setDrawer] = React.useState<any>(null);

  React.useEffect(() => { fetchJson('/api/analytics/games').then((body) => setAllGames(body.games || [])).catch((e) => setError(e.message)); }, []);
  React.useEffect(() => {
    const q = new URLSearchParams({ start: range.start, end: range.end, ...(gameId !== 'all' ? { game_id: gameId } : {}) });
    setError(null);
    Promise.all(['timeline','summary','patterns','sessions'].map((n) => fetchJson(`/api/analytics/${n}?${q}`))).then(([timeline, summary, patterns, sessions]) => {
      setData({ timeline, summary, patterns, sessions });
      if (timeline.range) setRange((current) => current.start === timeline.range.start && current.end === timeline.range.end ? current : timeline.range);
    }).catch((e) => setError(e.message));
  }, [range.start, range.end, gameId]);

  const quick = (name: string) => { const now = new Date(); if (name === '7d') setRange({ start: fmtDate(addDays(now, -6)), end: fmtDate(now) }); if (name === '30d') setRange({ start: fmtDate(addDays(now, -29)), end: fmtDate(now) }); if (name === 'month') setRange({ start: fmtDate(new Date(now.getFullYear(), now.getMonth(), 1)), end: fmtDate(now) }); if (name === 'all') { const q = new URLSearchParams(gameId !== 'all' ? { game_id: gameId } : {}); fetchJson(`/api/analytics/range?${q}`).then((bounds: ApiRange) => setRange(bounds)).catch((e) => setError(e.message)); } };
  if (!data) return <main className="app"><div className="card loading">플레이 데이터를 불러오는 중…{error && ` ${error}`}</div></main>;

  const games: GameMetric[] = data.summary.metrics.games || [];
  const timelineGames: GameMetric[] = data.timeline.games || games;
  const timelineSeries = timelineGames.map((g) => ({
    name: g.display_name || g.process_name,
    type: chartMode === 'bar' ? 'bar' : 'line',
    stack: gameId === 'all' ? 'play' : undefined,
    smooth: chartMode === 'area',
    showSymbol: false,
    areaStyle: chartMode === 'area' ? { opacity: gameId === 'all' ? 0.46 : 0.22 } : undefined,
    lineStyle: { width: gameId === 'all' ? 2 : 3, color: g.color },
    itemStyle: { color: g.color },
    emphasis: { focus: 'series' },
    data: data.timeline.days.map((d: any) => d.games.find((x: any) => x.game_key === g.game_key)?.total_seconds || 0),
  }));
  const timelineOption: echarts.EChartsCoreOption = { dataZoom: [{ type: 'inside', zoomOnMouseWheel: true, moveOnMouseWheel: true }, { type: 'slider', bottom: 18 }], brush: { toolbox: ['lineX', 'clear'], xAxisIndex: 0 }, tooltip: { trigger: 'axis', valueFormatter: secondsToText }, legend: { textStyle: { color: '#cbd5e1' }, top: 0 }, grid: { left: 44, right: 24, top: 48, bottom: 72 }, xAxis: { type: 'category', data: data.timeline.days.map((d: any) => d.date) }, yAxis: { type: 'value', axisLabel: { formatter: (v: number) => `${Math.round(v / 3600)}h` } }, series: timelineSeries };
  const heatmapOption: echarts.EChartsCoreOption = { tooltip: { formatter: (p: any) => `${data.patterns.weekdays[p.value[1]]} ${hourLabel(p.value[0])}<br/>${secondsToText(p.value[2])}` }, grid: { left: 62, right: 20, top: 24, bottom: 58 }, xAxis: { type: 'category', data: data.patterns.hours.map(hourLabel), axisLabel: { interval: 1, rotate: 35 } }, yAxis: { type: 'category', data: data.patterns.weekdays, axisLabel: { color: (value: string) => value === '토' || value === '일' ? '#fbbf24' : '#cbd5e1', fontWeight: (value: string) => value === '토' || value === '일' ? 800 : 500 } }, visualMap: { min: 0, max: Math.max(3600, ...data.patterns.heatmap.map((h: any) => h.total_seconds)), calculable: true, orient: 'horizontal', left: 'center', bottom: 4, inRange: { color: ['#111827', '#312e81', '#7c3aed', '#22d3ee'] } }, series: [{ type: 'heatmap', data: data.patterns.heatmap.map((h: any) => ({ value: [h.hour, h.weekday, h.total_seconds], itemStyle: h.weekday >= 5 ? { borderColor: 'rgba(251,191,36,.28)', borderWidth: 1, opacity: 0.96 } : undefined })) }] };
  const onBrush = (event: any) => { const area = event.batch?.[0]?.areas?.[0]; if (!area?.coordRange?.length) return; const [a, b] = area.coordRange.map((n: number) => Math.max(0, Math.min(data.timeline.days.length - 1, Math.round(n)))).sort((x: number, y: number) => x - y); setRange({ start: data.timeline.days[a].date, end: data.timeline.days[b].date }); };

  return <main className="app"><header className="hero"><div><div className="kicker">Timeline + Insights</div><h1>플레이 데이터 전용 분석 대시보드</h1><p>정규화된 게임 그룹, 부드러운 영역선, 게임별 인사이트를 한 화면에서 확인합니다.</p></div></header><div className="toolbar"><div className="quick"><button onClick={() => quick('7d')}>최근 7일</button><button onClick={() => quick('30d')}>최근 30일</button><button onClick={() => quick('month')}>이번 달</button><button onClick={() => quick('all')}>전체 기간</button></div><div className="filters"><input type="date" value={range.start} onChange={(e) => setRange((r) => ({ ...r, start: e.target.value }))}/><span>~</span><input type="date" value={range.end} onChange={(e) => setRange((r) => ({ ...r, end: e.target.value }))}/><select value={gameId} onChange={(e) => setGameId(e.target.value)}><option value="all">모든 게임</option>{allGames.map((g) => <option key={g.game_key} value={g.game_key}>{g.display_name}</option>)}</select></div></div>{error && <div className="error">API 오류: {error}</div>}<section className="card timeline-card"><div className="card-title-row"><h2>연속 플레이 타임라인</h2><div className="segmented"><button className={chartMode === 'area' ? 'active' : ''} onClick={() => setChartMode('area')}>영역선</button><button className={chartMode === 'bar' ? 'active' : ''} onClick={() => setChartMode('bar')}>막대</button></div></div>{timelineGames.length ? <EChart option={timelineOption} onBrush={onBrush}/> : <div className="empty">선택한 기간에 플레이 기록이 없습니다.</div>}</section><section className="grid"><Metric label="총 플레이 시간" value={secondsToText(data.summary.metrics.total_seconds)} delta={data.summary.deltas.total_seconds}/><Metric label="일평균" value={secondsToText(data.summary.metrics.daily_average_seconds)} delta={data.summary.deltas.daily_average_seconds}/><Metric label="플레이한 날" value={`${data.summary.metrics.played_days}일`} delta={data.summary.deltas.played_days}/><Metric label="평균 세션" value={secondsToText(data.summary.metrics.average_session_seconds)} delta={data.summary.deltas.session_count}/><section className="card split"><h2>게임별 누적 통계</h2><table className="table"><tbody>{games.slice(0,8).map((g) => <tr key={g.game_key} onClick={() => setGameId(g.game_key)}><td><span className="game-chip"><img src={iconUrl(g, 48)}/>{g.display_name}</span></td><td>{secondsToText(g.total_seconds)}</td><td>{Math.round((g.share || 0) * 100)}%</td></tr>)}</tbody></table></section><section className="card split"><h2>요일/시간대 패턴</h2><EChart option={heatmapOption} className="chart heatmap"/></section><section className="card split"><h2>세션 상세</h2><table className="table"><tbody>{data.sessions.sessions.slice(0,10).map((s: any) => <tr key={s.id} onClick={() => setDrawer(s)}><td>{s.display_name || s.process_name}</td><td>{new Date(s.start_timestamp * 1000).toLocaleString()}</td><td>{secondsToText(s.duration_seconds)}{s.is_active ? ' · 진행 중' : ''}</td></tr>)}</tbody></table></section><section className="card split"><h2>게임별 인사이트</h2><div className="insight-list">{games.slice(0,4).map((g) => <article className="insight-card" key={g.game_key}><div className="insight-head"><img src={iconUrl(g, 128)}/><div><strong>{g.display_name}</strong><span>{secondsToText(g.total_seconds)}</span></div></div><InsightLine label="스마트 평균" value={secondsToText(g.insights?.smart_average_session_seconds || 0)}/><InsightLine label="최장 정상 세션" value={secondsToText(g.insights?.longest_normal_session_seconds || 0)}/><InsightLine label="주간 평균" value={secondsToText(g.insights?.weekly_average_seconds || 0)}/><InsightLine label="선호 시간" value={`${g.insights?.favorite_weekday == null ? '-' : WEEKDAYS[g.insights.favorite_weekday]} · ${g.insights?.favorite_hour == null ? '-' : hourLabel(g.insights.favorite_hour)}`}/><InsightLine label="평일/주말" value={preferenceText(g.insights?.weekday_weekend_preference)}/><InsightLine label="특이 세션" value={`1분 미만 ${g.insights?.very_short_session_count || 0}회 · 장시간 ${g.insights?.long_session_count || 0}회`}/><InsightLine label="최근 장시간" value={g.insights?.long_session_recent_date || '없음'}/><InsightLine label="장시간 주기" value={g.insights?.long_session_average_interval_days == null ? '없음' : `${g.insights.long_session_average_interval_days}일`}/></article>)}</div></section></section>{drawer && <div className="drawer-backdrop" onClick={() => setDrawer(null)}><aside className="drawer" onClick={(e) => e.stopPropagation()}><div className="drawer-header"><h2>세션 상세</h2><button onClick={() => setDrawer(null)}>닫기</button></div><pre>{JSON.stringify(drawer, null, 2)}</pre></aside></div>}</main>;
}
