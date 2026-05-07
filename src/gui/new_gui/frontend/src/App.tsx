import React from 'react';
import { getCurrentWebview } from '@tauri-apps/api/webview';
import { invoke } from '@tauri-apps/api/core';
import { getCurrentWindow, LogicalSize } from '@tauri-apps/api/window';

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
  monitoring_path?: string;
  launch_path?: string;
  preferred_launch_type: string;
  status: string;
  progress: Progress;
  icon_url: string;
};

type WebShortcut = {
  id: string;
  name: string;
  url: string;
};

type MainState = {
  generated_at: string;
  settings: {
    theme: 'system' | 'light' | 'dark';
    always_on_top: boolean;
    hide_on_game: boolean;
    run_as_admin: boolean;
  };
  processes: ProcessRow[];
  web_shortcuts: WebShortcut[];
  dashboard_url: string;
};

const API_BASE = 'http://127.0.0.1:8000';
const clamp = (n: number, min: number, max: number) => Math.max(min, Math.min(max, n));

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `요청 실패 (${response.status})`);
  return body as T;
}

function useContentSizedWindow(ref: React.RefObject<HTMLElement | null>, enabled: boolean) {
  React.useEffect(() => {
    if (!enabled || !ref.current) return;
    const win = getCurrentWindow();
    const resize = () => {
      if (!ref.current) return;
      const rect = ref.current.getBoundingClientRect();
      const height = clamp(Math.ceil(rect.height) + 2, 260, 920);
      win.setSize(new LogicalSize(520, height)).catch(() => undefined);
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, [enabled, ref]);
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

export default function App() {
  const rootRef = React.useRef<HTMLElement | null>(null);
  const [state, setState] = React.useState<MainState | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busyId, setBusyId] = React.useState<string | null>(null);
  const isTauri = typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;

  useContentSizedWindow(rootRef, isTauri);

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
      .catch((e) => setError(e.message));
  }, [isTauri]);

  React.useEffect(() => {
    load();
    const id = window.setInterval(load, 1000);
    return () => window.clearInterval(id);
  }, [load]);

  const launch = async (process: ProcessRow) => {
    setBusyId(process.id);
    try {
      await fetchJson(`/api/gui/processes/${process.id}/launch`, { method: 'POST' });
      load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusyId(null);
    }
  };

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

  if (!state) {
    return (
      <main className="shell loading" ref={rootRef}>
        <div className="brand">HomeworkHelper</div>
        <p>{error || '메인 GUI 상태를 불러오는 중…'}</p>
      </main>
    );
  }

  return (
    <main className="shell" ref={rootRef}>
      <header className="topbar">
        <div>
          <div className="eyebrow">Windows Compact GUI</div>
          <h1>숙제 관리자</h1>
        </div>
        <div className="actions">
          <button onClick={() => openUrl(state.dashboard_url)}>📊</button>
          {state.web_shortcuts.map((shortcut) => (
            <button key={shortcut.id} onClick={() => openUrl(shortcut.url)} title={shortcut.url}>
              {shortcut.name}
            </button>
          ))}
        </div>
      </header>

      {error && <div className="error">API 오류: {error}</div>}

      <section className="table-card">
        <div className="table-head">
          <span>게임</span>
          <span>진행률</span>
          <span>실행</span>
          <span>상태</span>
        </div>
        {state.processes.length === 0 ? (
          <div className="empty">등록된 게임이 없습니다. 설정/추가 모달은 다음 단계에서 연결됩니다.</div>
        ) : (
          state.processes.map((process) => (
            <article className="row" key={process.id}>
              <div className="game">
                <img src={`${API_BASE}${process.icon_url}`} alt="" />
                <div>
                  <strong>{process.name}</strong>
                  <span>{process.preferred_launch_type === 'direct' ? '프로세스 선호' : '바로가기 선호'}</span>
                </div>
              </div>
              <ProgressBar progress={process.progress} />
              <button className="launch" disabled={busyId === process.id} onClick={() => launch(process)}>
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
    </main>
  );
}
