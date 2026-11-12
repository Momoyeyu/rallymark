import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ClockCounterClockwise,
  UploadSimple,
  PingPong,
  X,
  ArrowClockwise,
  CheckCircle,
  FilmStrip,
} from '@phosphor-icons/react';
import Player, { time } from './player/Player';
import { ApiError, request, upload, track, type Video } from './api';

const stages: Record<string, string> = {
  queued: '等待分析',
  downloading: '准备视频',
  tad: '识别回合',
  ocr: '读取比分',
  postprocessing: '整理回合',
};
export default function App() {
  const client = useQueryClient(),
    input = useRef<HTMLInputElement>(null);
  const [selected, setSelected] = useState<string | null>(() =>
    new URLSearchParams(location.search).get('video'),
  );
  const [history, setHistory] = useState(false),
    [uploading, setUploading] = useState<number | null>(null);
  const [error, setError] = useState<ApiError | null>(null),
    [retrying, setRetrying] = useState(false);
  const session = useQuery({
    queryKey: ['session'],
    queryFn: () => request('/session', { method: 'POST' }),
    staleTime: Infinity,
    retry: 1,
  });
  const videos = useQuery({
    queryKey: ['videos'],
    queryFn: () => request<{ items: Video[] }>('/videos'),
    enabled: session.isSuccess,
    refetchInterval: () => (selected || uploading !== null ? 3000 : false),
  });
  const detail = useQuery({
    queryKey: ['video', selected],
    queryFn: () => request<Video>('/videos/' + selected),
    enabled: session.isSuccess && !!selected,
    refetchInterval: (query) => {
      const status = query.state.data?.latest_analysis?.status;
      return status && ['succeeded', 'failed'].includes(status) ? false : 2000;
    },
  });
  const video = detail.data,
    analysis = video?.latest_analysis;
  useEffect(() => {
    if (!history) return;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = document.querySelector<HTMLElement>('.history-drawer');
    const items = () =>
      Array.from(dialog?.querySelectorAll<HTMLElement>('button,[href],input') || []);
    items()[0]?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setHistory(false);
      if (event.key === 'Tab') {
        const controls = items(),
          first = controls[0],
          last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener('keydown', key);
    return () => {
      document.removeEventListener('keydown', key);
      previous?.focus();
    };
  }, [history]);
  const completed = useRef<string | null>(null);
  useEffect(() => {
    if (analysis?.status === 'succeeded' && completed.current !== analysis.id) {
      completed.current = analysis.id;
      track({ name: 'analysis_completed', video_id: video?.id, analysis_id: analysis.id });
    }
  }, [analysis?.status, analysis?.id, video?.id]);
  function choose(id: string) {
    setSelected(id);
    setHistory(false);
    setError(null);
    const url = new URL(location.href);
    url.searchParams.set('video', id);
    window.history.replaceState({}, '', url);
  }
  async function onUpload(file?: File) {
    if (!file || uploading !== null) return;
    if (file.size > 500_000_000) {
      setError(new ApiError('视频需要小于 500 MB'));
      return;
    }
    setError(null);
    setUploading(0);
    try {
      const result = await upload(file, setUploading);
      client.setQueryData(['video', result.id], result);
      choose(result.id);
      void client.invalidateQueries({ queryKey: ['videos'] });
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError('上传失败，请重试'));
      track({ name: 'upload_failed' });
    } finally {
      setUploading(null);
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
      await client.invalidateQueries({ queryKey: ['video', video.id] });
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError('重试失败'));
    } finally {
      setRetrying(false);
    }
  }
  const failure = error || session.error || detail.error || videos.error;
  return (
    <div className="app-shell">
      <header className="app-header">
        <a href="/" className="brand" aria-label="RallyMark 首页">
          <PingPong weight="fill" />
          <span>
            Rally<span>Mark</span>
          </span>
        </a>
        <nav>
          <button aria-label="历史视频" onClick={() => setHistory(true)}>
            <ClockCounterClockwise />
          </button>
          <button
            aria-label="上传视频"
            disabled={!session.isSuccess || uploading !== null}
            onClick={() => input.current?.click()}
          >
            <UploadSimple />
          </button>
        </nav>
      </header>
      <input
        ref={input}
        type="file"
        accept="video/mp4,.mp4"
        hidden
        onChange={(e) => void onUpload(e.target.files?.[0])}
      />
      <main>
        {failure && (
          <div className="error-banner" role="alert">
            <span>
              {failure.message}
              {failure instanceof ApiError && failure.requestId && (
                <small>问题编号 {failure.requestId}</small>
              )}
            </span>
            <button
              aria-label="重新连接"
              onClick={() => {
                setError(null);
                void client.invalidateQueries();
              }}
            >
              <ArrowClockwise />
            </button>
          </div>
        )}
        {uploading !== null ? (
          <section className="status-page" aria-live="polite">
            <UploadSimple size={44} />
            <h1>{uploading < 100 ? '正在上传' : '正在校验视频'}</h1>
            <p>{uploading < 100 ? uploading + '%' : '上传完成，即将开始分析'}</p>
            <progress max="100" value={uploading} />
            <p className="muted">上传期间请保持此页面打开</p>
          </section>
        ) : video && analysis?.status === 'succeeded' ? (
          <>
            <div className="video-title">
              <FilmStrip />
              <h1>{video.title}</h1>
            </div>
            <Player key={analysis.id} video={video} analysis={analysis} />
            {analysis.warnings.map((warning, i) => (
              <p className="notice" key={i}>
                {warning}
              </p>
            ))}
            <p className="expiry">
              保存至 {new Date(video.expires_at).toLocaleDateString('zh-CN')}
            </p>
          </>
        ) : video && analysis?.status === 'failed' ? (
          <section className="status-page">
            <FilmStrip size={44} />
            <h1>本次分析未完成</h1>
            <p>{analysis.error?.message || '请稍后重试'}</p>
            {analysis.error?.request_id && <small>问题编号 {analysis.error.request_id}</small>}
            <button className="primary action" disabled={retrying} onClick={() => void retry()}>
              <ArrowClockwise />
              {retrying ? '正在重试' : '重新分析'}
            </button>
          </section>
        ) : video && analysis ? (
          <section className="status-page" aria-live="polite">
            <div className="activity">
              <PingPong weight="fill" />
            </div>
            <h1>{stages[analysis.status] || '分析中'}</h1>
            <p>{video.title}</p>
            {analysis.progress && analysis.progress.total > 0 ? (
              <>
                <progress value={analysis.progress.completed} max={analysis.progress.total} />
                <span>
                  {analysis.progress.completed} / {analysis.progress.total}
                </span>
              </>
            ) : (
              <span className="indeterminate" aria-label="分析进行中" />
            )}
            <p className="muted">可以离开页面，稍后从历史中查看结果</p>
          </section>
        ) : selected && (detail.isPending || session.isPending) ? (
          <section className="status-page">
            <p>正在读取视频…</p>
          </section>
        ) : (
          <section className="welcome">
            <div className="welcome-icon">
              <PingPong weight="fill" />
            </div>
            <h1>每一回合，直接回看。</h1>
            <p>
              上传比赛视频，自动标记回合与比分。
              <br />
              在原视频中自由跳转，专注每一次交锋。
            </p>
            <button
              className="primary action"
              disabled={!session.isSuccess}
              onClick={() => input.current?.click()}
            >
              <UploadSimple />
              选择视频
            </button>
            <small>MP4 · H.264 · 最大 500 MB / 15 分钟</small>
            {!!videos.data?.items.length && (
              <button className="text-button" onClick={() => setHistory(true)}>
                查看历史视频
              </button>
            )}
          </section>
        )}
      </main>
      <footer className="bottom-actions">
        <button onClick={() => setHistory(true)}>
          <ClockCounterClockwise />
          历史
        </button>
        <button
          className="primary"
          disabled={!session.isSuccess || uploading !== null}
          onClick={() => input.current?.click()}
        >
          <UploadSimple />
          上传
        </button>
      </footer>
      {history && (
        <div className="drawer-backdrop" onClick={() => setHistory(false)}>
          <section
            role="dialog"
            aria-modal="true"
            aria-label="历史视频"
            className="history-drawer"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="drawer-heading">
              <h2>历史视频</h2>
              <button aria-label="关闭历史" onClick={() => setHistory(false)}>
                <X />
              </button>
            </div>
            <p className="muted">保留七天，仅此浏览器可见</p>
            {videos.isLoading ? (
              <p>读取中…</p>
            ) : !videos.data?.items.length ? (
              <p className="empty">还没有视频，开始第一次分析吧。</p>
            ) : (
              videos.data.items.map((v) => (
                <button
                  key={v.id}
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
                    <CheckCircle />
                  ) : (
                    <span className="history-status">
                      {v.latest_analysis?.status === 'failed'
                        ? '未完成'
                        : stages[v.latest_analysis?.status || ''] || '处理中'}
                    </span>
                  )}
                </button>
              ))
            )}
          </section>
        </div>
      )}
    </div>
  );
}
