import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ClockCounterClockwise,
  UploadSimple,
  PingPong,
  ArrowClockwise,
  CheckCircle,
  FilmStrip,
  SignIn,
  SignOut,
  Trash,
  UserCircle,
} from '@phosphor-icons/react';
import Player from './player/Player';
import { preflight, type UploadPolicy } from './uploadPreflight';
import { time } from './player/time';
import { IconButton, ActionButton } from './ui/controls';
import { Brand } from './ui/Brand';
import { Notice } from './ui/Notice';
import { Dialog } from './ui/Dialog';
import { AccountForm } from './account/AccountForm';
import type { components } from './api.generated';
import './account/account.css';
import { Progress } from './ui/Progress';
import { ApiError, request, upload, track, type Video } from './api';

const stages: Record<string, string> = {
  preparing: '准备视频',
  queued: '等待分析',
  downloading: '准备视频',
  tad: '识别回合',
  ocr: '读取比分',
  postprocessing: '整理回合',
};
type Account = components['schemas']['Account'];
type Panel = 'history' | 'guest-upload' | 'quota' | 'login' | 'register' | 'delete';

async function refreshSession() {
  await request('/session', { method: 'POST' });
  return request<Account>('/account');
}

export default function App() {
  const client = useQueryClient(),
    input = useRef<HTMLInputElement>(null);
  const [selected, setSelected] = useState<string | null>(() =>
    new URLSearchParams(location.search).get('video'),
  );
  const [panel, setPanel] = useState<Panel | null>(null);
  const [deletion, setDeletion] = useState<Video | null>(null);
  const [panelError, setPanelError] = useState('');
  const [busy, setBusy] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const [uploading, setUploading] = useState<number | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<ApiError | null>(null),
    [retrying, setRetrying] = useState(false);
  const session = useQuery({
    queryKey: ['session'],
    queryFn: refreshSession,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    retry: 1,
  });
  const account = session.data?.username;
  const quota = session.data?.quota;
  const scope = session.data?.id ?? 'guest';
  const quotaFull = quota?.limit != null && quota.used >= quota.limit;
  const videos = useQuery({
    queryKey: ['videos', scope],
    queryFn: () => request<{ items: Video[] }>('/videos'),
    enabled: session.isSuccess,
    refetchInterval: () => (selected || uploading !== null ? 3000 : false),
  });
  const detail = useQuery({
    queryKey: ['video', scope, selected],
    queryFn: () => request<Video>('/videos/' + selected),
    enabled: session.isSuccess && !!selected,
    refetchInterval: (query) => {
      const status = query.state.data?.latest_analysis?.status;
      return status && ['succeeded', 'failed'].includes(status) ? false : 2000;
    },
  });
  const video = detail.isError ? undefined : detail.data,
    analysis = video?.latest_analysis;
  const completed = useRef<string | null>(null);
  useEffect(() => {
    if (analysis?.status === 'succeeded' && completed.current !== analysis.id) {
      completed.current = analysis.id;
      track({ name: 'analysis_completed', video_id: video?.id, analysis_id: analysis.id });
    }
  }, [analysis?.status, analysis?.id, video?.id]);
  function selectVideo(id: string | null) {
    setSelected(id);
    setError(null);
    const url = new URL(location.href);
    if (id) url.searchParams.set('video', id);
    else url.searchParams.delete('video');
    window.history.replaceState({}, '', url);
  }
  function choose(id: string) {
    selectVideo(id);
    setPanel(null);
  }
  function openPanel(next: Panel) {
    setPanelError('');
    setPanel(next);
    if (next === 'history' || next === 'guest-upload' || next === 'quota') {
      void client.invalidateQueries({ queryKey: ['session'] });
      void client.invalidateQueries({ queryKey: ['videos'] });
    }
  }
  function beginUpload() {
    if (account) input.current?.click();
    else openPanel(quotaFull ? 'quota' : 'guest-upload');
  }
  async function authenticate(mode: 'login' | 'register', username: string, password: string) {
    await client.cancelQueries({ queryKey: ['session'] });
    const current = await request<Account>('/account/' + mode, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    client.setQueryData(['session'], current);
    setPanel(null);
  }
  async function logout() {
    setSigningOut(true);
    try {
      await client.cancelQueries({ queryKey: ['session'] });
      await request('/account/logout', { method: 'POST' });
      selectVideo(null);
      client.setQueryData(['session'], await refreshSession());
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError('退出登录失败，请重试。'));
    } finally {
      setSigningOut(false);
    }
  }
  async function removeVideo() {
    if (!deletion || busy) return;
    setBusy(true);
    setPanelError('');
    try {
      await request('/videos/' + deletion.id, { method: 'DELETE' });
      if (selected === deletion.id) selectVideo(null);
      await Promise.all([
        client.invalidateQueries({ queryKey: ['session'] }),
        client.invalidateQueries({ queryKey: ['videos'] }),
      ]);
      setDeletion(null);
      setPanel('history');
    } catch (e) {
      setPanelError(e instanceof ApiError ? e.message : '删除失败，请重试。');
    } finally {
      setBusy(false);
    }
  }
  async function onUpload(file?: File) {
    if (!file || uploading !== null) return;
    setError(null);
    setUploading(0);
    setChecking(true);
    try {
      const policy = await request<UploadPolicy>('/upload-policy');
      await preflight(file, policy);
      await request('/availability');
      setChecking(false);
      const result = await upload(file, setUploading);
      client.setQueryData(['video', scope, result.id], result);
      choose(result.id);
      void client.invalidateQueries({ queryKey: ['videos'] });
      void client.invalidateQueries({ queryKey: ['session'] });
    } catch (e) {
      if (e instanceof ApiError && e.code === 'guest_quota') openPanel('quota');
      else setError(e instanceof ApiError ? e : new ApiError('上传失败，请重试'));
      track({ name: 'upload_failed' });
    } finally {
      setUploading(null);
      setChecking(false);
      if (input.current) input.current.value = '';
    }
  }
  async function retry() {
    if (!video || retrying) return;
    setRetrying(true);
    setError(null);
    try {
      await request('/videos/' + video.id + '/analyses', {
        method: 'POST',
        headers: { 'Idempotency-Key': crypto.randomUUID?.() || String(Date.now()) },
      });
      await client.invalidateQueries({ queryKey: ['video', scope, video.id] });
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError('重试失败'));
    } finally {
      setRetrying(false);
    }
  }
  const failure = error || session.error || detail.error || videos.error;
  return (
    <div className="app-shell product-app">
      <a className="skip-link" href="#main-content">
        跳到内容
      </a>
      <header className="app-header">
        <Brand />
        <nav aria-label="视频操作">
          <IconButton
            label={account ? '账户 · ' + account : '登录或注册'}
            icon={account ? UserCircle : SignIn}
            disabled={!session.isSuccess || uploading !== null || signingOut}
            onClick={() => openPanel(account ? 'history' : 'login')}
          />
          <IconButton
            label="历史视频"
            icon={ClockCounterClockwise}
            onClick={() => openPanel('history')}
          />
          <IconButton
            label="上传视频"
            icon={UploadSimple}
            disabled={!session.isSuccess || uploading !== null || signingOut}
            onClick={beginUpload}
          />
        </nav>
      </header>
      <input
        ref={input}
        type="file"
        name="file"
        aria-label="上传原视频"
        accept="video/mp4,video/quicktime,.mp4,.mov,.m4v"
        hidden
        onChange={(e) => void onUpload(e.target.files?.[0])}
      />
      <main id="main-content">
        {failure && (
          <div className="error-banner" role="alert">
            <span>
              {failure.message}
              {failure instanceof ApiError && failure.requestId && (
                <small>问题编号 {failure.requestId}</small>
              )}
            </span>
            <IconButton
              icon={ArrowClockwise}
              label="重新连接"
              onClick={() => {
                setError(null);
                void client.invalidateQueries();
              }}
            />
          </div>
        )}
        {uploading !== null ? (
          <section className="status-page" aria-live="polite">
            <UploadSimple size={44} aria-hidden="true" />
            <h1>{checking ? '检查视频' : uploading < 100 ? '视频上传' : '视频校验'}</h1>
            <p>{checking ? '尚未上传' : uploading < 100 ? uploading + '%' : '即将分析'}</p>
            <Progress label="上传进度" value={checking ? undefined : uploading} max={100} />
            <p className="muted">上传期间请保持此页面打开</p>
          </section>
        ) : video && analysis?.status === 'succeeded' ? (
          <>
            <div className="workspace-toolbar">
              <div className="workspace-title">
                <FilmStrip aria-hidden="true" />
                <h1>{video.title}</h1>
              </div>
            </div>
            <Player key={analysis.id} video={video} analysis={analysis} />
            <Notice messages={analysis.warnings} />
            <p className="expiry">
              {account
                ? '保存至 ' + new Date(video.expires_at).toLocaleDateString('zh-CN')
                : '访客记录仅在本次会话有效'}
            </p>
          </>
        ) : video && analysis?.status === 'failed' ? (
          <section className="status-page">
            <FilmStrip size={44} aria-hidden="true" />
            <h1>分析失败</h1>
            <p>{analysis.error?.message || '请稍后重试'}</p>
            {analysis.error?.request_id && <small>问题编号 {analysis.error.request_id}</small>}
            <ActionButton
              icon={ArrowClockwise}
              label={retrying ? '重试中' : '重试'}
              tone="primary"
              disabled={retrying}
              onClick={() => void retry()}
            />
          </section>
        ) : video && analysis ? (
          <section className="status-page" aria-live="polite">
            <div className="activity">
              <PingPong weight="fill" aria-hidden="true" />
            </div>
            <h1>{stages[analysis.status] || '分析中'}</h1>
            <p className="status-title">{video.title}</p>
            {analysis.progress && analysis.progress.total > 0 ? (
              <>
                <Progress
                  label="分析进度"
                  value={analysis.progress.completed}
                  max={analysis.progress.total}
                />
                <span>
                  {analysis.progress.completed} / {analysis.progress.total}
                </span>
              </>
            ) : (
              <Progress label="分析进行中" />
            )}
            <p className="muted">
              {account
                ? '可以离开页面，稍后从历史中查看结果'
                : '请保持页面打开，登录后可在其他设备回看'}
            </p>
          </section>
        ) : selected && (detail.isPending || session.isPending) ? (
          <section className="status-page">
            <p>读取视频</p>
          </section>
        ) : (
          <section className="welcome">
            <div className="welcome-icon">
              <PingPong weight="fill" aria-hidden="true" />
            </div>
            <h1>每一回合，直接回看。</h1>
            <p>
              上传比赛视频，自动标记回合与比分。
              <br />
              在原视频中自由跳转，专注每一次交锋。
            </p>
            <ActionButton
              icon={UploadSimple}
              label="选择视频"
              tone="primary"
              disabled={!session.isSuccess || signingOut}
              onClick={beginUpload}
            />
            <small>MP4 / MOV · 最大 500 MB / 15 分钟</small>
            {!!videos.data?.items.length && (
              <ActionButton
                icon={ClockCounterClockwise}
                label="历史视频"
                onClick={() => openPanel('history')}
              />
            )}
          </section>
        )}
      </main>
      <footer className="bottom-actions">
        <ActionButton
          icon={ClockCounterClockwise}
          label="历史"
          onClick={() => openPanel('history')}
        />
        <ActionButton
          icon={UploadSimple}
          label="上传"
          tone="primary"
          disabled={!session.isSuccess || uploading !== null || signingOut}
          onClick={beginUpload}
        />
      </footer>
      <Dialog
        open={panel !== null}
        onClose={() => {
          if (!busy) setPanel(null);
        }}
        title={
          panel === 'guest-upload'
            ? '以访客身份上传'
            : panel === 'quota'
              ? '访客存储空间已满'
              : panel === 'login'
                ? '登录 RallyMark'
                : panel === 'register'
                  ? '注册 RallyMark'
                  : panel === 'delete'
                    ? '删除视频'
                    : '历史视频'
        }
        side={panel === 'history'}
      >
        {(panel === 'guest-upload' || panel === 'quota') && (
          <div className="product-dialog">
            <p>
              {panel === 'quota' || quotaFull
                ? '登录后会自动保存本次记录。也可以删除一个视频，再继续上传。'
                : '退出页面后，本次视频和分析记录会失效。登录可保存记录，并在其他设备查看。'}
            </p>
            <div className="product-dialog-actions">
              <ActionButton
                icon={SignIn}
                label="现在登录"
                tone="primary"
                onClick={() => openPanel('login')}
              />
              {panel === 'quota' || quotaFull ? (
                <ActionButton
                  icon={ClockCounterClockwise}
                  label="管理视频"
                  onClick={() => openPanel('history')}
                />
              ) : (
                <ActionButton
                  icon={UploadSimple}
                  label="继续上传"
                  onClick={() => {
                    setPanel(null);
                    input.current?.click();
                  }}
                />
              )}
            </div>
          </div>
        )}
        {(panel === 'login' || panel === 'register') && (
          <AccountForm
            key={panel}
            mode={panel}
            onSubmit={(username, password) => authenticate(panel, username, password)}
            onSwitch={() => openPanel(panel === 'login' ? 'register' : 'login')}
            onBusy={setBusy}
          />
        )}
        {panel === 'delete' && deletion && (
          <div className="product-dialog">
            <p>删除「{deletion.title}」及其分析记录？</p>
            {panelError && (
              <p className="error" role="alert">
                {panelError}
              </p>
            )}
            <div className="product-dialog-actions">
              <ActionButton
                icon={Trash}
                label="删除视频"
                tone="danger"
                disabled={busy}
                onClick={() => void removeVideo()}
              />
              <ActionButton
                icon={ClockCounterClockwise}
                label="返回历史"
                disabled={busy}
                onClick={() => openPanel('history')}
              />
            </div>
          </div>
        )}
        {panel === 'history' && (
          <>
            <div className="history-account">
              <div>
                <strong>{account || '访客'}</strong>
                {quota && (
                  <p className="muted">
                    存储空间 {quota.used}
                    {quota.limit == null ? ' 个视频' : '/' + quota.limit}
                  </p>
                )}
              </div>
              {account ? (
                <ActionButton
                  icon={SignOut}
                  label="退出登录"
                  disabled={signingOut || uploading !== null}
                  onClick={() => void logout()}
                />
              ) : (
                <ActionButton
                  icon={SignIn}
                  label="登录"
                  disabled={uploading !== null}
                  onClick={() => openPanel('login')}
                />
              )}
            </div>
            {quotaFull && <p className="muted">存储空间已满。登录或删除一个视频后可继续上传。</p>}
            {videos.isLoading ? (
              <p>读取中…</p>
            ) : !videos.data?.items.length ? (
              <p className="empty">还没有视频，开始第一次分析吧。</p>
            ) : (
              videos.data.items.map((v) => (
                <div className="history-row" key={v.id}>
                  <button
                    className={'history-item ' + (v.id === selected ? 'chosen' : '')}
                    onClick={() => choose(v.id)}
                  >
                    <span>
                      <strong>{v.title}</strong>
                      <small>
                        {time(v.duration_s)} · {new Date(v.created_at).toLocaleDateString('zh-CN')}
                      </small>
                    </span>
                    {v.latest_analysis?.status === 'succeeded' ? (
                      <CheckCircle aria-hidden="true" />
                    ) : (
                      <span className="history-status">
                        {v.latest_analysis?.status === 'failed'
                          ? '分析失败'
                          : stages[v.latest_analysis?.status || ''] || '正在处理'}
                      </span>
                    )}
                  </button>
                  <IconButton
                    icon={Trash}
                    tone="danger"
                    label={'删除 ' + v.title}
                    disabled={Boolean(
                      v.latest_analysis &&
                      !['succeeded', 'failed'].includes(v.latest_analysis.status),
                    )}
                    onClick={() => {
                      setDeletion(v);
                      openPanel('delete');
                    }}
                  />
                </div>
              ))
            )}
          </>
        )}
      </Dialog>
    </div>
  );
}
