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
  theme: 'system' | 'light' | 'dark';
  always_on_top: boolean;
  hide_on_game: boolean;
  run_as_admin: boolean;
  run_on_startup: boolean;
  sidebar_enabled: boolean;
  screenshot_enabled: boolean;
  recording_enabled: boolean;
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
    try {
      const body = await fetchJson<{ backups: Array<{ slot: number; modified_at: number; size: number }> }>('/api/beholder/backups');
      setBackups(body.backups || []);
    } catch (e: any) {
      setError(e.message);
    }
  };
  const restore = async (slot: number) => {
    if (!window.confirm(`backup.${slot}로 DB를 복구할까요? 현재 DB는 복구 직전 snapshot으로 보존됩니다.`)) return;
    setBusy(`restore-${slot}`);
    try {
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
  const [message, setMessage] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);

  const update = <K extends keyof GuiSettings>(key: K, value: GuiSettings[K]) => setForm((prev) => ({ ...prev, [key]: value }));

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
      onSaved();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal title="설정" onClose={onClose}>
      <form className="form-grid" onSubmit={submit}>
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
          <label className="check"><input type="checkbox" checked={form.sidebar_enabled} onChange={(e) => update('sidebar_enabled', e.target.checked)} /> 사이드바</label>
          <label className="check"><input type="checkbox" checked={form.screenshot_enabled} onChange={(e) => update('screenshot_enabled', e.target.checked)} /> 스크린샷</label>
          <label className="check"><input type="checkbox" checked={form.recording_enabled} onChange={(e) => update('recording_enabled', e.target.checked)} /> OBS 녹화</label>
        </div>
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

export default function App() {
  const rootRef = React.useRef<HTMLElement | null>(null);
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
    const incidentId = window.setInterval(() => {
      fetchJson<{ incidents: BeholderIncident[] }>('/api/beholder/incidents/active')
        .then((body) => {
          if (body.incidents?.[0]) setBeholderIncident(body.incidents[0]);
        })
        .catch(() => undefined);
    }, 2000);
    return () => {
      window.clearInterval(id);
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

  const processMenuItems = (process: ProcessRow): ContextMenuItem[] => [
    { label: '편집', action: () => setEditingProcess(process) },
    { label: '삭제', kind: 'danger', action: () => deleteProcess(process) },
  ];

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
