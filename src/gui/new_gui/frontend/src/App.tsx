import React from 'react';
import { getCurrentWebview } from '@tauri-apps/api/webview';
import { invoke } from '@tauri-apps/api/core';
import { currentMonitor, getCurrentWindow, LogicalSize, PhysicalPosition, primaryMonitor } from '@tauri-apps/api/window';

type Progress = {
  kind: 'time' | 'stamina';
  percent: number;
  label: string;
  current?: number;
  max?: number;
  hoyolab_game_id?: string;
};

type ProcessRow = {
  id: string;
  name: string;
  monitoring_path?: string | null;
  launch_path?: string | null;
  preferred_launch_type: 'shortcut' | 'direct' | 'launcher';
  last_played_timestamp?: number | null;
  server_reset_time_str?: string | null;
  user_cycle_hours?: number | null;
  mandatory_times_str?: string[] | null;
  is_mandatory_time_enabled: boolean;
  user_preset_id?: string | null;
  stamina_tracking_enabled: boolean;
  hoyolab_game_id?: string | null;
  stamina_current?: number | null;
  stamina_max?: number | null;
  stamina_updated_at?: number | null;
  status: string;
  progress: Progress;
  icon_url: string;
};

type WebShortcut = {
  id: string;
  name: string;
  url: string;
  refresh_time_str?: string | null;
  last_reset_timestamp?: number | null;
  state: 'default' | 'due' | 'done';
};

type GuiSettings = {
  sleep_start_time_str: string;
  sleep_end_time_str: string;
  sleep_correction_advance_notify_hours: number;
  cycle_deadline_advance_notify_hours: number;
  run_on_startup: boolean;
  always_on_top: boolean;
  run_as_admin: boolean;
  notify_on_mandatory_time: boolean;
  notify_on_cycle_deadline: boolean;
  notify_on_sleep_correction: boolean;
  notify_on_daily_reset: boolean;
  stamina_notify_enabled: boolean;
  stamina_notify_threshold: number;
  theme: 'system' | 'light' | 'dark';
  hide_on_game: boolean;
  sidebar_enabled: boolean;
  sidebar_auto_hide_ms: number;
  sidebar_edge_width_px: number;
  sidebar_trigger_y_start: number;
  sidebar_trigger_y_end: number;
  sidebar_effect: string;
  sidebar_height_ratio: number;
  sidebar_opacity: number;
  sidebar_clock_enabled: boolean;
  sidebar_clock_format: string;
  sidebar_playtime_enabled: boolean;
  sidebar_playtime_prefix: string;
  sidebar_volume_section_enabled: boolean;
  screenshot_enabled: boolean;
  screenshot_save_dir: string;
  screenshot_gamepad_trigger: boolean;
  screenshot_disable_gamebar: boolean;
  screenshot_capture_mode: 'fullscreen' | 'game_window' | 'window';
  screenshot_gamepad_button_index: number;
  screenshot_trigger_vk: number;
  recording_enabled: boolean;
  obs_host: string;
  obs_port: number;
  obs_password: string;
  obs_exe_path: string;
  obs_auto_launch: boolean;
  obs_launch_hidden: boolean;
  obs_watch_output_dir: boolean;
  obs_recording_output_dir: string;
  recording_hold_threshold_ms: number;
};

type HoYoLabGame = {
  id: 'honkai_starrail' | 'zenless_zone_zero';
  name: string;
  stamina_name: string;
};

type HoYoLabStatus = {
  configured: boolean;
  credentials_file_exists: boolean;
  credentials_loadable: boolean;
  credentials_path: string;
  service_available: boolean;
  dpapi_available: boolean;
  extractor_available: boolean;
  supported_browsers: string[];
  supported_games: HoYoLabGame[];
};

type HoYoLabCredentialForm = {
  ltuid: string;
  ltoken_v2: string;
  ltmid_v2: string;
  test_game_id: HoYoLabGame['id'];
};

type BeholderAction = {
  id: string;
  label: string;
  description?: string;
  recommended?: boolean;
  danger?: boolean;
};

type BeholderIncident = {
  id: number;
  severity: 'info' | 'warning' | 'critical';
  status: string;
  operation_kind: string;
  actor: string;
  target_summary?: string | null;
  suspected_cause?: string | null;
  current_state_summary?: string | null;
  proposed_change_summary?: string | null;
  risk_score: number;
  risk_factors: string[];
  safe_recommendation?: string | null;
  user_title?: string | null;
  user_summary?: string | null;
  user_impact?: string | null;
  recommended_action?: string | null;
  available_actions?: BeholderAction[];
  created_at: number;
};

class BeholderIncidentError extends Error {
  incident: BeholderIncident;
  constructor(incident: BeholderIncident) {
    super(incident.user_summary || incident.safe_recommendation || 'Beholder가 비정상 데이터 변경을 차단했습니다.');
    this.incident = incident;
  }
}

type MainState = {
  generated_at: string;
  settings: GuiSettings;
  processes: ProcessRow[];
  web_shortcuts: WebShortcut[];
  dashboard_url: string;
};

type ProcessForm = {
  id?: string;
  name: string;
  monitoring_path: string;
  launch_path: string;
  preferred_launch_type: 'shortcut' | 'direct' | 'launcher';
  server_reset_time_str: string;
  user_cycle_hours: string;
  mandatory_times_str: string;
  is_mandatory_time_enabled: boolean;
  stamina_tracking_enabled: boolean;
  hoyolab_game_id: string;
};

type ShortcutForm = {
  id?: string;
  name: string;
  url: string;
  refresh_time_str: string;
};

type LaunchPreference = ProcessRow['preferred_launch_type'];

type ContextMenuItem = {
  label: string;
  action: () => void;
  kind?: 'normal' | 'danger';
  disabled?: boolean;
};

type ContextMenuState = {
  x: number;
  y: number;
  items: ContextMenuItem[];
};

const API_BASE = import.meta.env.DEV ? '' : 'http://127.0.0.1:8000';
const WINDOW_POS_KEY = 'hh-main-gui-window-position-v1';
const SIDEBAR_PANEL_WIDTH = 320;
const SIDEBAR_HANDLE_WIDTH = 28;
const SIDEBAR_TOTAL_WIDTH = SIDEBAR_PANEL_WIDTH + SIDEBAR_HANDLE_WIDTH;
const SIDEBAR_MIN_HEIGHT = 360;
const clamp = (n: number, min: number, max: number) => Math.max(min, Math.min(max, n));
const isTauriRuntime = () => typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 409 && body.beholder_incident) throw new BeholderIncidentError(body.beholder_incident);
    throw new Error(body.detail || `요청 실패 (${response.status})`);
  }
  return body as T;
}

function useContentSizedWindow(ref: React.RefObject<HTMLElement | null>, enabled: boolean) {
  React.useEffect(() => {
    if (!enabled || !ref.current) return;
    const win = getCurrentWindow();
    let resizeToken = 0;

    const resize = () => {
      const target = ref.current;
      if (!target) return;
      const token = ++resizeToken;
      window.requestAnimationFrame(() => {
        if (token !== resizeToken || !ref.current) return;
        const root = ref.current;
        const rect = root.getBoundingClientRect();
        const measuredWidth = Math.max(root.scrollWidth, Math.ceil(rect.width));
        const measuredHeight = Math.max(root.scrollHeight, Math.ceil(rect.height));

        void (async () => {
          try {
            const monitor = await currentMonitor() || await primaryMonitor();
            const scale = monitor?.scaleFactor || window.devicePixelRatio || 1;
            const maxWidth = monitor ? Math.floor(monitor.workArea.size.width / scale) - 24 : 1400;
            const maxHeight = monitor ? Math.floor(monitor.workArea.size.height / scale) - 24 : 1000;
            const width = clamp(Math.ceil(measuredWidth) + 2, 500, Math.max(500, maxWidth));
            const height = clamp(Math.ceil(measuredHeight) + 2, 260, Math.max(260, maxHeight));

            await win.setSize(new LogicalSize(width, height));
            await win.setResizable(false);

            if (!monitor) return;
            const [position, outerSize] = await Promise.all([win.outerPosition(), win.outerSize()]);
            const minX = monitor.workArea.position.x;
            const minY = monitor.workArea.position.y;
            const maxX = minX + monitor.workArea.size.width - outerSize.width;
            const maxY = minY + monitor.workArea.size.height - outerSize.height;
            const x = clamp(position.x, minX, Math.max(minX, maxX));
            const y = clamp(position.y, minY, Math.max(minY, maxY));
            if (x !== position.x || y !== position.y) {
              await win.setPosition(new PhysicalPosition(x, y));
            }
          } catch {
            // Browser preview or platforms with incomplete window APIs keep the CSS size.
          }
        })();
      });
    };

    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(ref.current);
    window.addEventListener('resize', resize);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', resize);
    };
  }, [enabled, ref]);
}

function useWindowPlacement(enabled: boolean) {
  React.useEffect(() => {
    if (!enabled) return;
    const win = getCurrentWindow();
    const raw = localStorage.getItem(WINDOW_POS_KEY);
    if (raw) {
      try {
        const pos = JSON.parse(raw) as { x: number; y: number };
        if (Number.isFinite(pos.x) && Number.isFinite(pos.y)) {
          win.setPosition(new PhysicalPosition(pos.x, pos.y)).catch(() => undefined);
        }
      } catch {
        localStorage.removeItem(WINDOW_POS_KEY);
      }
    }
    let unlisten: (() => void) | undefined;
    win.onMoved(({ payload }) => {
      localStorage.setItem(WINDOW_POS_KEY, JSON.stringify({ x: payload.x, y: payload.y }));
    }).then((fn) => {
      unlisten = fn;
    }).catch(() => undefined);
    return () => unlisten?.();
  }, [enabled]);
}

function useSidebarDrawerWindow(settings: GuiSettings | null, open: boolean, enabled: boolean) {
  React.useEffect(() => {
    if (!enabled || !settings) return;
    const win = getCurrentWindow();
    let cancelled = false;
    const applyGeometry = async () => {
      try {
        const monitor = await currentMonitor() || await primaryMonitor();
        if (!monitor || cancelled) return;
        const scale = monitor.scaleFactor || window.devicePixelRatio || 1;
        const work = monitor.workArea;
        const logicalHeight = clamp(
          Math.floor((work.size.height / scale) * clamp(settings.sidebar_height_ratio ?? 1, 0.3, 1)),
          SIDEBAR_MIN_HEIGHT,
          Math.max(SIDEBAR_MIN_HEIGHT, Math.floor(work.size.height / scale)),
        );
        const physicalHeight = Math.floor(logicalHeight * scale);
        const visibleWidth = open ? SIDEBAR_TOTAL_WIDTH : SIDEBAR_HANDLE_WIDTH;
        const x = Math.floor(work.position.x + work.size.width - visibleWidth * scale);
        const y = Math.floor(work.position.y + (work.size.height - physicalHeight) / 2);

        await win.setResizable(false);
        await win.setAlwaysOnTop(true);
        await win.setDecorations(false);
        await win.setSkipTaskbar(true);
        await win.setSize(new LogicalSize(SIDEBAR_TOTAL_WIDTH, logicalHeight));
        await win.setPosition(new PhysicalPosition(x, y));
        if (settings.sidebar_enabled) await win.show();
        else await win.hide();
      } catch {
        // Browser preview and incomplete platform APIs keep the CSS preview geometry.
      }
    };

    applyGeometry();
    window.addEventListener('resize', applyGeometry);
    const id = window.setInterval(applyGeometry, 2000);
    return () => {
      cancelled = true;
      window.removeEventListener('resize', applyGeometry);
      window.clearInterval(id);
    };
  }, [settings, open, enabled]);
}

function StatusBadge({ status }: { status: string }) {
  const kind = status === '실행중' ? 'running' : status === '미완료' ? 'incomplete' : 'done';
  return <span className={`status ${kind}`}>{status}</span>;
}

function ProgressBar({ progress }: { progress: Progress }) {
  return (
    <div className="progress" aria-label={progress.label}>
      <div className="progress-meta">
        <span>{progress.kind === 'stamina' ? '스태미나' : '남은 시간'}</span>
        <strong>{progress.label}</strong>
      </div>
      <div className="track">
        <div className="fill" style={{ width: `${clamp(progress.percent, 0, 100)}%` }} />
      </div>
    </div>
  );
}

function processToForm(process?: ProcessRow): ProcessForm {
  return {
    id: process?.id,
    name: process?.name || '',
    monitoring_path: process?.monitoring_path || '',
    launch_path: process?.launch_path || '',
    preferred_launch_type: process?.preferred_launch_type || 'shortcut',
    server_reset_time_str: process?.server_reset_time_str || '',
    user_cycle_hours: String(process?.user_cycle_hours ?? 24),
    mandatory_times_str: (process?.mandatory_times_str || []).join(', '),
    is_mandatory_time_enabled: Boolean(process?.is_mandatory_time_enabled),
    stamina_tracking_enabled: Boolean(process?.stamina_tracking_enabled),
    hoyolab_game_id: process?.hoyolab_game_id || '',
  };
}

function processPayload(form: ProcessForm) {
  return {
    name: form.name.trim(),
    monitoring_path: form.monitoring_path.trim(),
    launch_path: form.launch_path.trim() || form.monitoring_path.trim(),
    preferred_launch_type: form.preferred_launch_type,
    server_reset_time_str: form.server_reset_time_str.trim() || null,
    user_cycle_hours: Number.parseInt(form.user_cycle_hours, 10) || 24,
    mandatory_times_str: form.mandatory_times_str
      .split(',')
      .map((item) => item.trim())
      .filter(Boolean),
    is_mandatory_time_enabled: form.is_mandatory_time_enabled,
    stamina_tracking_enabled: form.stamina_tracking_enabled,
    hoyolab_game_id: form.stamina_tracking_enabled && form.hoyolab_game_id ? form.hoyolab_game_id : null,
  };
}

function shortcutToForm(shortcut?: WebShortcut): ShortcutForm {
  return {
    id: shortcut?.id,
    name: shortcut?.name || '',
    url: shortcut?.url || 'https://',
    refresh_time_str: shortcut?.refresh_time_str || '',
  };
}


function ContextMenu({ menu, onClose }: { menu: ContextMenuState; onClose: () => void }) {
  React.useEffect(() => {
    const close = () => onClose();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('mousedown', close);
    window.addEventListener('blur', close);
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('mousedown', close);
      window.removeEventListener('blur', close);
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [onClose]);

  const x = Math.min(menu.x, Math.max(8, window.innerWidth - 178));
  const y = Math.min(menu.y, Math.max(8, window.innerHeight - (menu.items.length * 34 + 12)));

  return (
    <div
      className="context-menu"
      role="menu"
      style={{ left: x, top: y }}
      onContextMenu={(event) => event.preventDefault()}
      onMouseDown={(event) => event.stopPropagation()}
    >
      {menu.items.map((item) => (
        <button
          key={item.label}
          className={item.kind === 'danger' ? 'danger-item' : undefined}
          role="menuitem"
          disabled={item.disabled}
          onClick={() => {
            if (item.disabled) return;
            onClose();
            item.action();
          }}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}

function Modal({ title, children, onClose }: React.PropsWithChildren<{ title: string; onClose: () => void }>) {
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section className="modal" role="dialog" aria-modal="true" aria-label={title} onMouseDown={(e) => e.stopPropagation()}>
        <header className="modal-head">
          <h2>{title}</h2>
          <button className="ghost" onClick={onClose}>닫기</button>
        </header>
        {children}
      </section>
    </div>
  );
}


function BeholderModal({ incident, onClose, onResolved }: { incident: BeholderIncident; onClose: () => void; onResolved: () => void }) {
  const [busy, setBusy] = React.useState<string | null>(null);
  const [message, setMessage] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [backups, setBackups] = React.useState<Array<{ slot: number; modified_at: number; size: number }>>([]);
  const [restorePreview, setRestorePreview] = React.useState<{ backup: { slot: number; modified_at: number; size: number }; current: { path: string; size: number } } | null>(null);
  const resolve = async (action: string) => {
    setBusy(action);
    setError(null);
    setMessage(null);
    try {
      const result = await fetchJson<{ override_token?: string }>(`/api/beholder/incidents/${incident.id}/resolve`, {
        method: 'POST',
        body: JSON.stringify({ action }),
      });
      if (action === 'allow_once' && result.override_token) {
        setMessage('1회 허용 토큰이 발급되었습니다. 동일 작업을 다시 시도하면 한 번만 허용됩니다.');
      } else {
        onResolved();
        onClose();
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };
  const loadBackups = async () => {
    setError(null);
    setRestorePreview(null);
    try {
      const body = await fetchJson<{ backups: Array<{ slot: number; modified_at: number; size: number }> }>('/api/beholder/backups');
      setBackups(body.backups || []);
    } catch (e: any) {
      setError(e.message);
    }
  };
  const restore = async (slot: number) => {
    setError(null);
    setMessage(null);
    setBusy(`restore-${slot}`);
    try {
      const preview = await fetchJson<{ backup: { slot: number; modified_at: number; size: number }; current: { path: string; size: number } }>('/api/beholder/backups/restore-preview', {
        method: 'POST',
        body: JSON.stringify({ slot }),
      });
      setRestorePreview(preview);
      if (!window.confirm(`backup.${slot}로 DB를 복구할까요?\n\n현재 DB: ${preview.current.size} bytes\n복구 백업: ${preview.backup.size} bytes\n\n현재 DB는 복구 직전 snapshot으로 보존됩니다.`)) return;
      await fetchJson('/api/beholder/backups/restore', { method: 'POST', body: JSON.stringify({ slot }) });
      setMessage('백업 복구가 완료되었습니다. 앱을 재시작해 주세요.');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(null);
    }
  };
  return (
    <Modal title="Beholder 데이터 보호 경고" onClose={onClose}>
      <div className="beholder-panel">
        <strong>{incident.user_title || '데이터 변경 확인이 필요합니다'}</strong>
        <p>{incident.user_summary || 'Beholder가 저장 전에 변경 내용을 확인했습니다.'}</p>
        <dl>
          <dt>사용자 영향</dt><dd>{incident.user_impact || '-'}</dd>
          <dt>권장 조치</dt><dd>{incident.safe_recommendation || '차단을 유지하세요.'}</dd>
          <dt>심각도 / 위험도</dt><dd>{incident.severity} · {incident.risk_score}/100</dd>
          <dt>동작</dt><dd>{incident.operation_kind} / {incident.actor}</dd>
          <dt>현재 DB 상태</dt><dd>{incident.current_state_summary || '-'}</dd>
          <dt>저장하려던 변경</dt><dd>{incident.proposed_change_summary || '-'}</dd>
          <dt>위험 신호</dt><dd>{(incident.risk_factors || []).join(', ') || '-'}</dd>
        </dl>
        {backups.length > 0 && (
          <div className="backup-list">
            {backups.map((backup) => (
              <button className="ghost" key={backup.slot} onClick={() => restore(backup.slot)}>
                backup.{backup.slot} · {new Date(backup.modified_at * 1000).toLocaleString()} · {backup.size} bytes
              </button>
            ))}
          </div>
        )}
        {restorePreview && (
          <div className="notice compact">
            복구 미리보기: 현재 DB {restorePreview.current.size} bytes → backup.{restorePreview.backup.slot} {restorePreview.backup.size} bytes
          </div>
        )}
        {message && <div className="notice compact">{message}</div>}
        {error && <div className="error compact">{error}</div>}
        <div className="modal-actions">
          {(incident.available_actions || [
            { id: 'deny', label: '차단 유지' },
            { id: 'quarantine', label: '격리' },
            { id: 'allow_once', label: '이번 한 번 허용', danger: true },
          ]).map((action) => (
            <button
              key={action.id}
              className={action.danger ? 'danger' : action.recommended ? 'primary' : 'ghost'}
              title={action.description || ''}
              disabled={Boolean(busy)}
              onClick={() => resolve(action.id)}
            >
              {action.recommended ? '★ ' : ''}{action.label}
            </button>
          ))}
          <button className="ghost" disabled={Boolean(busy)} onClick={loadBackups}>백업에서 복구</button>
        </div>
      </div>
    </Modal>
  );
}

function ProcessModal({ process, onClose, onSaved }: { process?: ProcessRow; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = React.useState<ProcessForm>(() => processToForm(process));
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  const update = <K extends keyof ProcessForm>(key: K, value: ProcessForm[K]) => setForm((prev) => ({ ...prev, [key]: value }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim() || !form.monitoring_path.trim()) {
      setError('이름과 모니터링 경로는 필수입니다.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const path = form.id ? `/api/gui/processes/${form.id}` : '/api/gui/processes';
      await fetchJson(path, {
        method: form.id ? 'PUT' : 'POST',
        body: JSON.stringify(processPayload(form)),
      });
      onSaved();
      onClose();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={form.id ? '게임 편집' : '게임 추가'} onClose={onClose}>
      <form className="form-grid" onSubmit={submit}>
        <label>이름<input value={form.name} onChange={(e) => update('name', e.target.value)} /></label>
        <label>모니터링 경로<input value={form.monitoring_path} onChange={(e) => update('monitoring_path', e.target.value)} placeholder="C:\\Games\\Game.exe" /></label>
        <label>실행 경로<input value={form.launch_path} onChange={(e) => update('launch_path', e.target.value)} placeholder="비우면 모니터링 경로 사용" /></label>
        <div className="field-row">
          <label>실행 방식
            <select value={form.preferred_launch_type} onChange={(e) => update('preferred_launch_type', e.target.value as ProcessForm['preferred_launch_type'])}>
              <option value="shortcut">바로가기 선호</option>
              <option value="direct">프로세스 선호</option>
              <option value="launcher">런처 우선</option>
            </select>
          </label>
          <label>주기(시간)<input value={form.user_cycle_hours} onChange={(e) => update('user_cycle_hours', e.target.value)} inputMode="numeric" /></label>
        </div>
        <div className="field-row">
          <label>서버 초기화<input value={form.server_reset_time_str} onChange={(e) => update('server_reset_time_str', e.target.value)} placeholder="HH:MM" /></label>
          <label>특정 접속<input value={form.mandatory_times_str} onChange={(e) => update('mandatory_times_str', e.target.value)} placeholder="12:00, 18:00" /></label>
        </div>
        <label className="check"><input type="checkbox" checked={form.is_mandatory_time_enabled} onChange={(e) => update('is_mandatory_time_enabled', e.target.checked)} /> 특정 접속 시각 사용</label>
        <label className="check"><input type="checkbox" checked={form.stamina_tracking_enabled} onChange={(e) => update('stamina_tracking_enabled', e.target.checked)} /> HoYoLab 스태미나 표시</label>
        {form.stamina_tracking_enabled && (
          <label>HoYoLab 게임
            <select value={form.hoyolab_game_id} onChange={(e) => update('hoyolab_game_id', e.target.value)}>
              <option value="">선택 안 함</option>
              <option value="honkai_starrail">붕괴: 스타레일</option>
              <option value="zenless_zone_zero">젠레스 존 제로</option>
            </select>
          </label>
        )}
        {error && <div className="error compact">{error}</div>}
        <div className="modal-actions">
          <button type="button" className="ghost" onClick={onClose}>취소</button>
          <button type="submit" disabled={saving}>{saving ? '저장 중…' : '저장'}</button>
        </div>
      </form>
    </Modal>
  );
}

function ShortcutModal({ shortcut, onClose, onSaved }: { shortcut?: WebShortcut; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = React.useState<ShortcutForm>(() => shortcutToForm(shortcut));
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);
  const update = <K extends keyof ShortcutForm>(key: K, value: ShortcutForm[K]) => setForm((prev) => ({ ...prev, [key]: value }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const path = form.id ? `/api/gui/web-shortcuts/${form.id}` : '/api/gui/web-shortcuts';
      await fetchJson(path, {
        method: form.id ? 'PUT' : 'POST',
        body: JSON.stringify({
          name: form.name.trim(),
          url: form.url.trim(),
          refresh_time_str: form.refresh_time_str.trim() || null,
        }),
      });
      onSaved();
      onClose();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title={form.id ? '웹 바로가기 편집' : '웹 바로가기 추가'} onClose={onClose}>
      <form className="form-grid" onSubmit={submit}>
        <label>버튼 이름<input value={form.name} onChange={(e) => update('name', e.target.value)} /></label>
        <label>URL<input value={form.url} onChange={(e) => update('url', e.target.value)} /></label>
        <label>매일 초기화 시각<input value={form.refresh_time_str} onChange={(e) => update('refresh_time_str', e.target.value)} placeholder="HH:MM, 선택" /></label>
        {error && <div className="error compact">{error}</div>}
        <div className="modal-actions">
          <button type="button" className="ghost" onClick={onClose}>취소</button>
          <button type="submit" disabled={saving}>{saving ? '저장 중…' : '저장'}</button>
        </div>
      </form>
    </Modal>
  );
}

function SettingsModal({ settings, onClose, onSaved }: { settings: GuiSettings; onClose: () => void; onSaved: () => void }) {
  const [form, setForm] = React.useState(settings);
  const [activeTab, setActiveTab] = React.useState<'general' | 'notify' | 'sidebar' | 'screenshot' | 'recording' | 'hoyolab'>('general');
  const [hoyolabStatus, setHoyolabStatus] = React.useState<HoYoLabStatus | null>(null);
  const [screenshotKeyInfo, setScreenshotKeyInfo] = React.useState<{ display_name: string; hex: string; capture_supported: boolean } | null>(null);
  const [hoyolabForm, setHoyolabForm] = React.useState<HoYoLabCredentialForm>({
    ltuid: '',
    ltoken_v2: '',
    ltmid_v2: '',
    test_game_id: 'honkai_starrail',
  });
  const [message, setMessage] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  const update = <K extends keyof GuiSettings>(key: K, value: GuiSettings[K]) => setForm((prev) => ({ ...prev, [key]: value }));
  const updateHoYoLab = <K extends keyof HoYoLabCredentialForm>(key: K, value: HoYoLabCredentialForm[K]) => setHoyolabForm((prev) => ({ ...prev, [key]: value }));
  const updateNumber = <K extends keyof GuiSettings>(key: K, value: string) => {
    const parsed = Number(value);
    update(key, (Number.isFinite(parsed) ? parsed : 0) as GuiSettings[K]);
  };

  const loadHoYoLabStatus = React.useCallback(async () => {
    const status = await fetchJson<HoYoLabStatus>('/api/gui/hoyolab/status');
    setHoyolabStatus(status);
  }, []);

  React.useEffect(() => {
    if (activeTab === 'hoyolab') {
      loadHoYoLabStatus().catch((e: any) => setError(e.message));
    }
  }, [activeTab, loadHoYoLabStatus]);

  React.useEffect(() => {
    if (activeTab === 'screenshot') {
      fetchJson<{ display_name: string; hex: string; capture_supported: boolean }>(`/api/gui/screenshot/vk/${form.screenshot_trigger_vk}`)
        .then(setScreenshotKeyInfo)
        .catch(() => setScreenshotKeyInfo(null));
    }
  }, [activeTab, form.screenshot_trigger_vk]);

  const applyPrivilege = async () => {
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const result = await fetchJson<{ ok: boolean; action: string }>('/api/gui/settings/apply-privilege', { method: 'POST' });
      setMessage(result.ok
        ? (result.action === 'none' ? '현재 권한 상태가 설정과 일치합니다.' : '권한 전환 요청을 보냈습니다.')
        : '권한 전환 요청에 실패했습니다.');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const saved = await fetchJson<GuiSettings & { startup_applied?: boolean | null; admin_restart_required?: boolean }>('/api/gui/settings', {
        method: 'PATCH',
        body: JSON.stringify(form),
      });
      if (isTauriRuntime()) {
        getCurrentWindow().setAlwaysOnTop(saved.always_on_top).catch(() => undefined);
      }
      setMessage(saved.admin_restart_required ? '관리자 권한 변경은 다음 실행/재시작 후 완전히 반영됩니다.' : '설정을 저장했습니다.');
      setForm(saved);
      onSaved();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const saveHoYoLabCredentials = async () => {
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const ltuid = Number(hoyolabForm.ltuid);
      if (!Number.isInteger(ltuid) || ltuid <= 0) throw new Error('LTUID는 양의 정수여야 합니다.');
      const status = await fetchJson<HoYoLabStatus & { ok: boolean }>('/api/gui/hoyolab/credentials', {
        method: 'PUT',
        body: JSON.stringify({
          ltuid,
          ltoken_v2: hoyolabForm.ltoken_v2.trim(),
          ltmid_v2: hoyolabForm.ltmid_v2.trim(),
        }),
      });
      setHoyolabStatus(status);
      setHoyolabForm((prev) => ({ ...prev, ltoken_v2: '', ltmid_v2: '' }));
      setMessage('HoYoLab 인증 정보를 저장했습니다.');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const clearHoYoLabCredentials = async () => {
    if (!window.confirm('저장된 HoYoLab 인증 정보를 삭제할까요?')) return;
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const status = await fetchJson<HoYoLabStatus & { ok: boolean }>('/api/gui/hoyolab/credentials', { method: 'DELETE' });
      setHoyolabStatus(status);
      setMessage('HoYoLab 인증 정보를 삭제했습니다.');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const extractHoYoLabCredentials = async (browser: string) => {
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const status = await fetchJson<HoYoLabStatus & { ok: boolean; browser: string }>('/api/gui/hoyolab/extract', {
        method: 'POST',
        body: JSON.stringify({ browser }),
      });
      setHoyolabStatus(status);
      setMessage(`${browser}에서 HoYoLab 쿠키를 추출해 저장했습니다.`);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const testHoYoLabStamina = async () => {
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const result = await fetchJson<{ game_name: string; current: number; max: number; recover_time: number }>('/api/gui/hoyolab/stamina', {
        method: 'POST',
        body: JSON.stringify({ game_id: hoyolabForm.test_game_id }),
      });
      setMessage(`${result.game_name}: ${result.current}/${result.max} · 완전 회복까지 약 ${Math.floor(result.recover_time / 60)}분`);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const importObsConfig = async () => {
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const cfg = await fetchJson<{ port: number; password: string; output_dir: string; exe_path: string }>('/api/gui/recording/obs-config');
      setForm((prev) => ({
        ...prev,
        obs_port: cfg.port,
        obs_password: cfg.password,
        obs_exe_path: cfg.exe_path || prev.obs_exe_path,
        obs_recording_output_dir: cfg.output_dir || prev.obs_recording_output_dir,
      }));
      setMessage('OBS 설정을 불러왔습니다. 적용하려면 저장을 누르세요.');
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const captureScreenshotKey = async () => {
    setSaving(true);
    setError(null);
    setMessage('캡처할 키를 10초 안에 누르세요. ESC는 취소입니다.');
    try {
      const captured = await fetchJson<{ vk: number; display_name: string; hex: string }>('/api/gui/screenshot/capture-key', {
        method: 'POST',
        body: JSON.stringify({ timeout_sec: 10 }),
      });
      update('screenshot_trigger_vk', captured.vk);
      setScreenshotKeyInfo({ display_name: captured.display_name, hex: captured.hex, capture_supported: true });
      setMessage(`${captured.display_name} (${captured.hex}) 키를 캡처했습니다. 적용하려면 저장을 누르세요.`);
    } catch (e: any) {
      setError(e.message);
      setMessage(null);
    } finally {
      setSaving(false);
    }
  };

  const tabs: Array<{ id: typeof activeTab; label: string }> = [
    { id: 'general', label: '일반' },
    { id: 'notify', label: '알림' },
    { id: 'sidebar', label: '사이드바' },
    { id: 'screenshot', label: '스크린샷' },
    { id: 'recording', label: 'OBS 녹화' },
    { id: 'hoyolab', label: 'HoYoLab' },
  ];

  return (
    <Modal title="설정" onClose={onClose}>
      <form className="form-grid settings-form" onSubmit={submit}>
        <div className="settings-tabs" role="tablist" aria-label="설정 섹션">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={activeTab === tab.id ? 'active' : 'ghost'}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {activeTab === 'general' && (
          <section className="settings-section">
            <label>테마
              <select value={form.theme} onChange={(e) => update('theme', e.target.value as GuiSettings['theme'])}>
                <option value="system">시스템</option>
                <option value="light">라이트</option>
                <option value="dark">다크</option>
              </select>
            </label>
            <div className="toggle-list">
              <label className="check"><input type="checkbox" checked={form.always_on_top} onChange={(e) => update('always_on_top', e.target.checked)} /> 항상 위</label>
              <label className="check"><input type="checkbox" checked={form.hide_on_game} onChange={(e) => update('hide_on_game', e.target.checked)} /> 게임 실행 시 숨김</label>
              <label className="check"><input type="checkbox" checked={form.run_on_startup} onChange={(e) => update('run_on_startup', e.target.checked)} /> Windows 시작 시 실행</label>
              <label className="check"><input type="checkbox" checked={form.run_as_admin} onChange={(e) => update('run_as_admin', e.target.checked)} /> 관리자 권한으로 실행</label>
            </div>
          </section>
        )}

        {activeTab === 'notify' && (
          <section className="settings-section">
            <div className="field-row">
              <label>수면 시작<input value={form.sleep_start_time_str} onChange={(e) => update('sleep_start_time_str', e.target.value)} placeholder="HH:MM" /></label>
              <label>수면 종료<input value={form.sleep_end_time_str} onChange={(e) => update('sleep_end_time_str', e.target.value)} placeholder="HH:MM" /></label>
            </div>
            <div className="field-row">
              <label>수면 보정 알림(시간 전)<input type="number" min="0" max="5" step="0.5" value={form.sleep_correction_advance_notify_hours} onChange={(e) => updateNumber('sleep_correction_advance_notify_hours', e.target.value)} /></label>
              <label>주기 마감 알림(시간 전)<input type="number" min="0" max="12" step="0.25" value={form.cycle_deadline_advance_notify_hours} onChange={(e) => updateNumber('cycle_deadline_advance_notify_hours', e.target.value)} /></label>
            </div>
            <div className="toggle-list">
              <label className="check"><input type="checkbox" checked={form.notify_on_mandatory_time} onChange={(e) => update('notify_on_mandatory_time', e.target.checked)} /> 고정 접속 시간 알림</label>
              <label className="check"><input type="checkbox" checked={form.notify_on_cycle_deadline} onChange={(e) => update('notify_on_cycle_deadline', e.target.checked)} /> 사용자 주기 만료 임박 알림</label>
              <label className="check"><input type="checkbox" checked={form.notify_on_sleep_correction} onChange={(e) => update('notify_on_sleep_correction', e.target.checked)} /> 수면 보정 알림</label>
              <label className="check"><input type="checkbox" checked={form.notify_on_daily_reset} onChange={(e) => update('notify_on_daily_reset', e.target.checked)} /> 일일 리셋 알림</label>
              <label className="check"><input type="checkbox" checked={form.stamina_notify_enabled} onChange={(e) => update('stamina_notify_enabled', e.target.checked)} /> 스태미나 가득 참 알림</label>
            </div>
            <label>스태미나 알림 시점<input type="number" min="1" max="100" value={form.stamina_notify_threshold} onChange={(e) => updateNumber('stamina_notify_threshold', e.target.value)} /></label>
          </section>
        )}

        {activeTab === 'sidebar' && (
          <section className="settings-section">
            <div className="toggle-list">
              <label className="check"><input type="checkbox" checked={form.sidebar_enabled} onChange={(e) => update('sidebar_enabled', e.target.checked)} /> 사이드바 사용</label>
              <label className="check"><input type="checkbox" checked={form.sidebar_clock_enabled} onChange={(e) => update('sidebar_clock_enabled', e.target.checked)} /> 현재 시간 표시</label>
              <label className="check"><input type="checkbox" checked={form.sidebar_playtime_enabled} onChange={(e) => update('sidebar_playtime_enabled', e.target.checked)} /> 플레이타임 표시</label>
              <label className="check"><input type="checkbox" checked={form.sidebar_volume_section_enabled} onChange={(e) => update('sidebar_volume_section_enabled', e.target.checked)} /> 볼륨 섹션 표시</label>
            </div>
            <div className="field-row">
              <label>높이 비율<input type="number" min="0.3" max="1" step="0.05" value={form.sidebar_height_ratio} onChange={(e) => updateNumber('sidebar_height_ratio', e.target.value)} /></label>
              <label>투명도<input type="number" min="0.1" max="1" step="0.05" value={form.sidebar_opacity} onChange={(e) => updateNumber('sidebar_opacity', e.target.value)} /></label>
            </div>
            <div className="field-row">
              <label>자동 숨김(ms)<input type="number" min="0" max="60000" step="100" value={form.sidebar_auto_hide_ms} onChange={(e) => updateNumber('sidebar_auto_hide_ms', e.target.value)} /></label>
              <label>엣지 감지(px)<input type="number" min="1" max="50" value={form.sidebar_edge_width_px} onChange={(e) => updateNumber('sidebar_edge_width_px', e.target.value)} /></label>
            </div>
            <div className="field-row">
              <label>트리거 시작 Y<input type="number" min="0" max="1" step="0.01" value={form.sidebar_trigger_y_start} onChange={(e) => updateNumber('sidebar_trigger_y_start', e.target.value)} /></label>
              <label>트리거 종료 Y<input type="number" min="0" max="1" step="0.01" value={form.sidebar_trigger_y_end} onChange={(e) => updateNumber('sidebar_trigger_y_end', e.target.value)} /></label>
            </div>
            <label>효과<input value={form.sidebar_effect} onChange={(e) => update('sidebar_effect', e.target.value)} placeholder="acrylic" /></label>
            <label>시간 포맷<input value={form.sidebar_clock_format} onChange={(e) => update('sidebar_clock_format', e.target.value)} placeholder="%H:%M:%S" /></label>
            <label>플레이타임 접두어<input value={form.sidebar_playtime_prefix} onChange={(e) => update('sidebar_playtime_prefix', e.target.value)} /></label>
          </section>
        )}

        {activeTab === 'screenshot' && (
          <section className="settings-section">
            <div className="toggle-list">
              <label className="check"><input type="checkbox" checked={form.screenshot_enabled} onChange={(e) => update('screenshot_enabled', e.target.checked)} /> 스크린샷 기능 사용</label>
              <label className="check"><input type="checkbox" checked={form.screenshot_gamepad_trigger} onChange={(e) => update('screenshot_gamepad_trigger', e.target.checked)} /> 게임패드 트리거</label>
              <label className="check"><input type="checkbox" checked={form.screenshot_disable_gamebar} onChange={(e) => update('screenshot_disable_gamebar', e.target.checked)} /> Game Bar 캡처 비활성화</label>
            </div>
            <label>저장 경로<input value={form.screenshot_save_dir || ''} onChange={(e) => update('screenshot_save_dir', e.target.value)} placeholder="비우면 기본 경로" /></label>
            <label>캡처 대상
              <select value={form.screenshot_capture_mode} onChange={(e) => update('screenshot_capture_mode', e.target.value as GuiSettings['screenshot_capture_mode'])}>
                <option value="fullscreen">전체 화면</option>
                <option value="game_window">포커스된 게임 창</option>
                <option value="window">창</option>
              </select>
            </label>
            <div className="field-row">
              <label>게임패드 버튼 index<input type="number" min="-1" max="32" value={form.screenshot_gamepad_button_index} onChange={(e) => updateNumber('screenshot_gamepad_button_index', e.target.value)} /></label>
              <label>트리거 VK<input type="number" min="0" max="255" value={form.screenshot_trigger_vk} onChange={(e) => updateNumber('screenshot_trigger_vk', e.target.value)} /></label>
            </div>
            <div className="field-row">
              <div className="key-chip">{screenshotKeyInfo ? `${screenshotKeyInfo.display_name} (${screenshotKeyInfo.hex})` : `VK ${form.screenshot_trigger_vk}`}</div>
              <button type="button" className="ghost" disabled={saving || screenshotKeyInfo?.capture_supported === false} onClick={captureScreenshotKey}>키 입력 캡처</button>
            </div>
            <p className="hint">키 캡처는 Windows WH_KEYBOARD_LL 경로를 사용합니다. macOS 개발 환경에서는 이름 확인/숫자 입력만 가능하며, 실제 캡처는 Windows smoke에서 확인합니다.</p>
          </section>
        )}

        {activeTab === 'recording' && (
          <section className="settings-section">
            <div className="toggle-list">
              <label className="check"><input type="checkbox" checked={form.recording_enabled} onChange={(e) => update('recording_enabled', e.target.checked)} /> 녹화 기능 사용</label>
              <label className="check"><input type="checkbox" checked={form.obs_auto_launch} onChange={(e) => update('obs_auto_launch', e.target.checked)} /> OBS 자동 실행</label>
              <label className="check"><input type="checkbox" checked={form.obs_launch_hidden} onChange={(e) => update('obs_launch_hidden', e.target.checked)} /> 최소화 상태로 실행</label>
              <label className="check"><input type="checkbox" checked={form.obs_watch_output_dir} onChange={(e) => update('obs_watch_output_dir', e.target.checked)} /> 출력 폴더 감시</label>
            </div>
            <div className="field-row">
              <label>OBS 호스트<input value={form.obs_host} onChange={(e) => update('obs_host', e.target.value)} placeholder="localhost" /></label>
              <label>OBS 포트<input type="number" min="1" max="65535" value={form.obs_port} onChange={(e) => updateNumber('obs_port', e.target.value)} /></label>
            </div>
            <label>OBS 비밀번호<input type="password" value={form.obs_password || ''} onChange={(e) => update('obs_password', e.target.value)} placeholder="비밀번호 없으면 비움" /></label>
            <label>OBS 실행 파일<input value={form.obs_exe_path || ''} onChange={(e) => update('obs_exe_path', e.target.value)} placeholder="obs64.exe 경로" /></label>
            <label>녹화 출력 폴더<input value={form.obs_recording_output_dir || ''} onChange={(e) => update('obs_recording_output_dir', e.target.value)} placeholder="비우면 OBS 설정 감지" /></label>
            <label>홀드 임계값(ms)<input type="number" min="100" max="2000" step="100" value={form.recording_hold_threshold_ms} onChange={(e) => updateNumber('recording_hold_threshold_ms', e.target.value)} /></label>
            <div className="field-row">
              <button type="button" className="ghost" disabled={saving} onClick={importObsConfig}>OBS 설정 불러오기</button>
            </div>
            <p className="hint">로컬 OBS WebSocket/프로필 설정을 읽어 포트, 비밀번호, 실행 파일, 출력 폴더를 채웁니다. 적용하려면 저장을 누르세요.</p>
          </section>
        )}

        {activeTab === 'hoyolab' && (
          <section className="settings-section">
            <div className={`hoyolab-status ${hoyolabStatus?.configured ? 'ok' : 'warn'}`}>
              <strong>{hoyolabStatus?.configured ? 'HoYoLab 인증 정보가 준비됨' : 'HoYoLab 인증 정보가 필요함'}</strong>
              <span>
                {hoyolabStatus?.credentials_file_exists
                  ? (hoyolabStatus.credentials_loadable ? '저장된 쿠키를 읽을 수 있습니다.' : '쿠키 파일은 있지만 이 환경에서 복호화할 수 없습니다.')
                  : '저장된 쿠키 파일이 없습니다.'}
              </span>
              <small>저장 위치: {hoyolabStatus?.credentials_path || '확인 중…'}</small>
            </div>
            <p className="hint">
              쿠키는 로컬 Windows 사용자 계정에 묶인 암호화 파일로 저장되며, 새 GUI는 토큰 값을 다시 표시하지 않습니다.
              macOS 개발 환경에서는 기존 Windows DPAPI 쿠키를 복호화할 수 없어도 실제 Windows 설치본에서는 기존 방식 그대로 동작합니다.
            </p>
            <div className="field-row">
              <button type="button" className="ghost" disabled={saving} onClick={() => extractHoYoLabCredentials('chrome')}>크롬에서 추출</button>
              <button type="button" className="ghost" disabled={saving} onClick={() => extractHoYoLabCredentials('edge')}>엣지에서 추출</button>
              <button type="button" className="ghost" disabled={saving} onClick={() => extractHoYoLabCredentials('firefox')}>파이어폭스에서 추출</button>
            </div>
            <div className="field-row">
              <label>LTUID<input value={hoyolabForm.ltuid} onChange={(e) => updateHoYoLab('ltuid', e.target.value)} placeholder="숫자로 된 사용자 ID" /></label>
              <label>테스트 게임
                <select value={hoyolabForm.test_game_id} onChange={(e) => updateHoYoLab('test_game_id', e.target.value as HoYoLabCredentialForm['test_game_id'])}>
                  <option value="honkai_starrail">붕괴: 스타레일</option>
                  <option value="zenless_zone_zero">젠레스 존 제로</option>
                </select>
              </label>
            </div>
            <label>LTOKEN_V2<input type="password" value={hoyolabForm.ltoken_v2} onChange={(e) => updateHoYoLab('ltoken_v2', e.target.value)} placeholder="ltoken_v2 쿠키 값" /></label>
            <label>LTMID_V2<input type="password" value={hoyolabForm.ltmid_v2} onChange={(e) => updateHoYoLab('ltmid_v2', e.target.value)} placeholder="ltmid_v2 쿠키 값" /></label>
            <div className="field-row">
              <button type="button" disabled={saving} onClick={saveHoYoLabCredentials}>수동 쿠키 저장</button>
              <button type="button" className="ghost" disabled={saving || !hoyolabStatus?.configured} onClick={testHoYoLabStamina}>스태미나 조회 테스트</button>
              <button type="button" className="danger" disabled={saving || !hoyolabStatus?.credentials_file_exists} onClick={clearHoYoLabCredentials}>인증 정보 삭제</button>
            </div>
          </section>
        )}

        {message && <div className="notice compact">{message}</div>}
        {error && <div className="error compact">{error}</div>}
        <div className="modal-actions">
          <button type="button" className="ghost" disabled={saving} onClick={applyPrivilege}>권한 재시작 적용</button>
          <button type="button" className="ghost" onClick={onClose}>닫기</button>
          <button type="submit" disabled={saving}>{saving ? '저장 중…' : '저장'}</button>
        </div>
      </form>
    </Modal>
  );
}

function formatPlaytime(timestamp?: number | null) {
  if (!timestamp) return '대기 중';
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - timestamp));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return hours > 0 ? `${hours}시간 ${minutes}분` : `${minutes}분`;
}

function SidebarApp() {
  const [state, setState] = React.useState<MainState | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [open, setOpen] = React.useState(false);
  const [pinned, setPinned] = React.useState(false);
  const [hoveringControls, setHoveringControls] = React.useState(false);
  const [clock, setClock] = React.useState(() => new Date());
  const hideTimerRef = React.useRef<number | null>(null);
  const isTauri = isTauriRuntime();

  const settings = state?.settings || null;
  const activeProcess = React.useMemo(
    () => state?.processes.find((process) => process.status === '실행중') || null,
    [state],
  );
  const recordingEnabled = Boolean(settings?.recording_enabled);
  const screenshotEnabled = Boolean(settings?.screenshot_enabled);
  const sidebarEnabled = settings?.sidebar_enabled ?? true;
  const autoHideMs = Math.max(0, settings?.sidebar_auto_hide_ms ?? 3000);

  useSidebarDrawerWindow(settings, open || pinned, isTauri);

  const load = React.useCallback(() => {
    fetchJson<MainState>('/api/gui/main-state')
      .then((body) => {
        setState(body);
        setError(null);
      })
      .catch((e: any) => setError(e.message || String(e)));
  }, []);

  React.useEffect(() => {
    load();
    const id = window.setInterval(load, 1000);
    const clockId = window.setInterval(() => setClock(new Date()), 1000);
    return () => {
      window.clearInterval(id);
      window.clearInterval(clockId);
    };
  }, [load]);

  React.useEffect(() => {
    if (!sidebarEnabled) return;
    if (pinned || hoveringControls) {
      if (hideTimerRef.current) window.clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
      return;
    }
    if (open && autoHideMs > 0) {
      if (hideTimerRef.current) window.clearTimeout(hideTimerRef.current);
      hideTimerRef.current = window.setTimeout(() => setOpen(false), autoHideMs);
    }
    return () => {
      if (hideTimerRef.current) window.clearTimeout(hideTimerRef.current);
      hideTimerRef.current = null;
    };
  }, [autoHideMs, hoveringControls, open, pinned, sidebarEnabled]);

  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setPinned(false);
        setOpen(false);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const reveal = () => {
    if (!sidebarEnabled) return;
    setOpen(true);
  };
  const scheduleHide = () => {
    if (pinned || hoveringControls || autoHideMs === 0) return;
    if (hideTimerRef.current) window.clearTimeout(hideTimerRef.current);
    hideTimerRef.current = window.setTimeout(() => setOpen(false), autoHideMs);
  };
  const togglePinned = () => {
    setPinned((value) => {
      const next = !value;
      setOpen(next || open);
      return next;
    });
  };

  if (!sidebarEnabled) {
    return <main className="sidebar-drawer disabled" aria-label="HomeworkHelper 사이드바 비활성" />;
  }

  return (
    <main
      className={`sidebar-drawer ${open || pinned ? 'open' : 'peek'} ${pinned ? 'pinned' : ''}`}
      style={{ opacity: clamp(settings?.sidebar_opacity ?? 0.85, 0.1, 1) }}
      onMouseEnter={reveal}
      onMouseLeave={scheduleHide}
    >
      <button
        className="drawer-handle"
        aria-label={open || pinned ? '사이드바 접기' : '사이드바 열기'}
        onClick={() => (open || pinned ? (setPinned(false), setOpen(false)) : reveal())}
      >
        <span className="handle-grip" />
        {recordingEnabled && <span className="handle-dot" title="녹화 기능 사용 가능" />}
        <span className="handle-text">{activeProcess ? 'PLAY' : 'HH'}</span>
      </button>

      <section className="drawer-panel">
        <header className="drawer-head">
          <div>
            <div className="eyebrow">Smart Drawer</div>
            <h2>{activeProcess?.name || '사이드바 대기'}</h2>
          </div>
          <div className="drawer-head-actions">
            <button className={pinned ? 'primary tiny' : 'ghost tiny'} onClick={togglePinned}>{pinned ? '고정됨' : 'Pin'}</button>
            <button className="ghost tiny" onClick={() => { setPinned(false); setOpen(false); }}>닫기</button>
          </div>
        </header>

        {error && <div className="error compact">{error}</div>}

        <div className="drawer-card focus">
          <span>{settings?.sidebar_playtime_prefix || '오늘 플레이 시간'}</span>
          <strong>{formatPlaytime(activeProcess?.last_played_timestamp)}</strong>
          <small>{activeProcess ? activeProcess.status : '게임 실행 중 우측 손잡이로 빠르게 열 수 있습니다.'}</small>
        </div>

        {settings?.sidebar_clock_enabled && (
          <div className="drawer-card clock-card">
            <span>현재 시간</span>
            <strong>{clock.toLocaleTimeString()}</strong>
            <small>{settings.sidebar_clock_format || '%H:%M:%S'}</small>
          </div>
        )}

        {settings?.sidebar_volume_section_enabled && (
          <div
            className="drawer-card"
            onMouseEnter={() => setHoveringControls(true)}
            onMouseLeave={() => setHoveringControls(false)}
          >
            <div className="drawer-row">
              <span>앱 볼륨</span>
              <strong>{activeProcess ? '준비됨' : '대기'}</strong>
            </div>
            <input className="drawer-slider" type="range" min="0" max="100" defaultValue="100" disabled={!activeProcess} />
            <small>실제 볼륨 제어는 runtime API 연결 후 Beholder 경계를 통해 처리됩니다.</small>
          </div>
        )}

        <div className="drawer-grid">
          <div className={`drawer-chip ${screenshotEnabled ? 'on' : ''}`}>
            <span>스크린샷</span>
            <strong>{screenshotEnabled ? 'ON' : 'OFF'}</strong>
          </div>
          <div className={`drawer-chip ${recordingEnabled ? 'on recording' : ''}`}>
            <span>녹화</span>
            <strong>{recordingEnabled ? 'READY' : 'OFF'}</strong>
          </div>
        </div>

        <footer className="drawer-foot">
          <span>hover/click으로 열기 · Esc로 닫기</span>
          <span>{pinned ? '자동숨김 일시정지' : `자동숨김 ${autoHideMs}ms`}</span>
        </footer>
      </section>
    </main>
  );
}

function MainApp() {
  const rootRef = React.useRef<HTMLElement | null>(null);
  const appInstanceIdRef = React.useRef<string>(globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`);
  const [state, setState] = React.useState<MainState | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busyId, setBusyId] = React.useState<string | null>(null);
  const [editingProcess, setEditingProcess] = React.useState<ProcessRow | 'new' | null>(null);
  const [editingShortcut, setEditingShortcut] = React.useState<WebShortcut | 'new' | null>(null);
  const [settingsOpen, setSettingsOpen] = React.useState(false);
  const [beholderIncident, setBeholderIncident] = React.useState<BeholderIncident | null>(null);
  const [contextMenu, setContextMenu] = React.useState<ContextMenuState | null>(null);
  const isTauri = isTauriRuntime();

  const handleError = React.useCallback((e: any) => {
    if (e instanceof BeholderIncidentError) {
      setBeholderIncident(e.incident);
      if (isTauri) getCurrentWindow().show().then(() => getCurrentWindow().setFocus()).catch(() => undefined);
      return;
    }
    setError(e.message || String(e));
  }, [isTauri]);

  useContentSizedWindow(rootRef, isTauri);
  useWindowPlacement(isTauri);

  const load = React.useCallback(() => {
    fetchJson<MainState>('/api/gui/main-state')
      .then((body) => {
        setState(body);
        setError(null);
        if (isTauri) {
          getCurrentWindow().setAlwaysOnTop(body.settings.always_on_top).catch(() => undefined);
          getCurrentWebview().setZoom(1).catch(() => undefined);
        }
      })
      .catch(handleError);
  }, [handleError, isTauri]);

  React.useEffect(() => {
    load();
    const id = window.setInterval(load, 1000);
    const sendHeartbeat = (shutdown = false) => {
      fetchJson('/api/beholder/runtime/heartbeat', {
        method: 'POST',
        body: JSON.stringify({ app_instance_id: appInstanceIdRef.current, runtime_kind: 'tauri-preview', shutdown }),
      }).catch(() => undefined);
    };
    sendHeartbeat();
    const heartbeatId = window.setInterval(() => sendHeartbeat(), 30000);
    const incidentId = window.setInterval(() => {
      fetchJson<{ incidents: BeholderIncident[] }>('/api/beholder/incidents/active')
        .then((body) => {
          if (body.incidents?.[0]) setBeholderIncident(body.incidents[0]);
        })
        .catch(() => undefined);
    }, 2000);
    return () => {
      sendHeartbeat(true);
      window.clearInterval(id);
      window.clearInterval(heartbeatId);
      window.clearInterval(incidentId);
    };
  }, [load]);

  const launch = async (process: ProcessRow) => {
    setBusyId(process.id);
    try {
      await fetchJson(`/api/gui/processes/${process.id}/launch`, { method: 'POST' });
      if (isTauri && state?.settings.hide_on_game) {
        getCurrentWindow().hide().catch(() => undefined);
      }
      load();
    } catch (e: any) {
      handleError(e);
    } finally {
      setBusyId(null);
    }
  };

  const openContextMenu = (event: React.MouseEvent, items: ContextMenuItem[]) => {
    event.preventDefault();
    event.stopPropagation();
    setContextMenu({ x: event.clientX, y: event.clientY, items });
  };

  const deleteProcess = async (process: ProcessRow) => {
    if (!window.confirm(`'${process.name}' 게임을 삭제할까요?`)) return;
    try {
      await fetchJson(`/api/gui/processes/${process.id}`, { method: 'DELETE' });
      load();
    } catch (e: any) {
      handleError(e);
    }
  };

  const setLaunchPreference = async (process: ProcessRow, preference: LaunchPreference) => {
    try {
      await fetchJson(`/api/gui/processes/${process.id}`, {
        method: 'PUT',
        body: JSON.stringify(processPayload({
          ...processToForm(process),
          preferred_launch_type: preference,
        })),
      });
      load();
    } catch (e: any) {
      handleError(e);
    }
  };

  const refreshStamina = async (process: ProcessRow) => {
    if (!process.hoyolab_game_id) return;
    setBusyId(process.id);
    try {
      await fetchJson<{ game_name: string; current: number; max: number }>('/api/gui/hoyolab/stamina', {
        method: 'POST',
        body: JSON.stringify({
          game_id: process.hoyolab_game_id,
          process_id: process.id,
          persist_to_process: true,
        }),
      });
      setError(null);
      load();
    } catch (e: any) {
      handleError(e);
    } finally {
      setBusyId(null);
    }
  };

  const processMenuItems = (process: ProcessRow): ContextMenuItem[] => {
    const items: ContextMenuItem[] = [
      { label: '편집', action: () => setEditingProcess(process) },
    ];
    if (process.stamina_tracking_enabled && process.hoyolab_game_id) {
      items.push({
        label: '스태미나 새로고침',
        disabled: busyId === process.id,
        action: () => refreshStamina(process),
      });
    }
    items.push({ label: '삭제', kind: 'danger', action: () => deleteProcess(process) });
    return items;
  };

  const launchPreferenceItems = (process: ProcessRow): ContextMenuItem[] => [
    { label: '바로가기 선호', disabled: process.preferred_launch_type === 'shortcut', action: () => setLaunchPreference(process, 'shortcut') },
    { label: '프로세스 선호', disabled: process.preferred_launch_type === 'direct', action: () => setLaunchPreference(process, 'direct') },
    { label: '런처 우선', disabled: process.preferred_launch_type === 'launcher', action: () => setLaunchPreference(process, 'launcher') },
  ];

  const shortcutMenuItems = (shortcut: WebShortcut): ContextMenuItem[] => [
    { label: '편집', action: () => setEditingShortcut(shortcut) },
    { label: '삭제', kind: 'danger', action: () => deleteShortcut(shortcut) },
  ];

  const openUrl = async (url: string) => {
    const target = url.startsWith('/') ? `${API_BASE}${url}` : url;
    try {
      if (isTauri) {
        await invoke('open_external_url', { url: target });
      } else {
        window.open(target, '_blank', 'noopener,noreferrer');
      }
    } catch (e: any) {
      setError(e?.message || '외부 링크를 열 수 없습니다.');
    }
  };

  const openShortcut = async (shortcut: WebShortcut) => {
    try {
      await fetchJson(`/api/gui/web-shortcuts/${shortcut.id}/open`, { method: 'POST' });
      await openUrl(shortcut.url);
      load();
    } catch (e: any) {
      handleError(e);
    }
  };

  const deleteShortcut = async (shortcut: WebShortcut) => {
    if (!window.confirm(`'${shortcut.name}' 바로가기를 삭제할까요?`)) return;
    try {
      await fetchJson(`/api/gui/web-shortcuts/${shortcut.id}`, { method: 'DELETE' });
      load();
    } catch (e: any) {
      handleError(e);
    }
  };

  if (!state) {
    return (
      <main className="shell loading" ref={rootRef}>
        <div className="brand">HomeworkHelper</div>
        <p>{error || '메인 GUI 상태를 불러오는 중…'}</p>
      </main>
    );
  }

  return (
    <main className="shell" ref={rootRef} data-theme={state.settings.theme}>
      <header className="topbar">
        <div>
          <div className="eyebrow">HomeworkHelper 새 GUI 미리보기</div>
          <h1>숙제 관리자</h1>
        </div>
        <div className="actions">
          <button onClick={() => setEditingProcess('new')}>+ 게임</button>
          <button onClick={() => setEditingShortcut('new')}>+ 웹</button>
          <button onClick={() => openUrl(state.dashboard_url)}>📊 대시보드</button>
          <button className="ghost" onClick={() => setSettingsOpen(true)}>설정</button>
        </div>
      </header>

      {error && <div className="error">API 오류: {error}</div>}

      {state.web_shortcuts.length > 0 && (
        <section className="shortcut-card" aria-label="웹 바로가기">
          {state.web_shortcuts.map((shortcut) => (
            <div
              className={`shortcut ${shortcut.state}`}
              key={shortcut.id}
              onContextMenu={(event) => openContextMenu(event, shortcutMenuItems(shortcut))}
            >
              <button onClick={() => openShortcut(shortcut)} title={`${shortcut.url} · 우클릭: 편집/삭제`}>{shortcut.name}</button>
            </div>
          ))}
        </section>
      )}

      <section className="table-card">
        <div className="table-head">
          <span>게임</span>
          <span>진행률</span>
          <span>실행</span>
          <span>상태</span>
        </div>
        {state.processes.length === 0 ? (
          <div className="empty">등록된 게임이 없습니다. + 게임으로 기존 PyQt와 같은 DB에 추가할 수 있습니다.</div>
        ) : (
          state.processes.map((process) => (
            <article className="row" key={process.id} onContextMenu={(event) => openContextMenu(event, processMenuItems(process))}>
              <div className="game">
                <img src={`${API_BASE}${process.icon_url}`} alt="" />
                <div>
                  <strong>{process.name}</strong>
                  <span title={process.preferred_launch_type === 'direct' ? '프로세스 선호' : process.preferred_launch_type === 'launcher' ? '런처 우선' : '바로가기 선호'}>{process.preferred_launch_type === 'direct' ? '프로세스' : process.preferred_launch_type === 'launcher' ? '런처' : '바로가기'}</span>
                </div>
              </div>
              <ProgressBar progress={process.progress} />
              <button
                className="launch"
                disabled={busyId === process.id}
                onClick={() => launch(process)}
                onContextMenu={(event) => openContextMenu(event, launchPreferenceItems(process))}
                title="우클릭: 실행 방식 선택"
              >
                {busyId === process.id ? '실행 중…' : '실행'}
              </button>
              <StatusBadge status={process.status} />
            </article>
          ))
        )}
      </section>

      <footer>
        <span>마지막 갱신 {new Date(state.generated_at).toLocaleTimeString()}</span>
        <span>{state.settings.always_on_top ? '항상 위' : '일반 창'} · {state.settings.hide_on_game ? '게임 시 숨김' : '항상 표시'}</span>
      </footer>

      {contextMenu && <ContextMenu menu={contextMenu} onClose={() => setContextMenu(null)} />}

      {editingProcess && (
        <ProcessModal
          process={editingProcess === 'new' ? undefined : editingProcess}
          onClose={() => setEditingProcess(null)}
          onSaved={load}
        />
      )}
      {editingShortcut && (
        <ShortcutModal
          shortcut={editingShortcut === 'new' ? undefined : editingShortcut}
          onClose={() => setEditingShortcut(null)}
          onSaved={load}
        />
      )}
      {settingsOpen && <SettingsModal settings={state.settings} onClose={() => setSettingsOpen(false)} onSaved={load} />}
      {beholderIncident && <BeholderModal incident={beholderIncident} onClose={() => setBeholderIncident(null)} onResolved={load} />}
    </main>
  );
}

export default function App() {
  const label = isTauriRuntime() ? getCurrentWindow().label : 'main';
  if (label === 'sidebar') return <SidebarApp />;
  return <MainApp />;
}
