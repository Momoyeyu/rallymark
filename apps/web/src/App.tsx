import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ClockCounterClockwise,
  UploadSimple,
  PingPong,
  ArrowClockwise,
  CheckCircle,
  FilmStrip,
} from '@phosphor-icons/react';
import Player from './player/Player';
import { time } from './player/time';
import { IconButton, ActionButton } from './ui/controls';
import { Brand } from './ui/Brand';
import { Notice } from './ui/Notice';
import { Dialog } from './ui/Dialog';
import { Progress } from './ui/Progress';
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
    queryFn: async () => {
      await request('/session', { method: 'POST' });
      return true;
    },
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
      <a className="skip-link" href="#main-content">
        跳到内容
      </a>
      <header className="app-header">
        <Brand />
        <nav>
          <IconButton
            label="历史视频"
            icon={ClockCounterClockwise}
            onClick={() => setHistory(true)}
          />
          <IconButton
            label="上传视频"
            icon={UploadSimple}
            disabled={!session.isSuccess || uploading !== null}
            onClick={() => input.current?.click()}
          />
        </nav>
      </header>
      <input
        ref={input}
        type="file"
        accept="video/mp4,.mp4"
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
            <h1>{uploading < 100 ? '视频上传' : '视频校验'}</h1>
            <p>{uploading < 100 ? uploading + '%' : '即将分析'}</p>
            <Progress label="上传进度" value={uploading} max={100} />
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
              保存至 {new Date(video.expires_at).toLocaleDateString('zh-CN')}
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
            <p>{video.title}</p>
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
            <p className="muted">可以离开页面，稍后从历史中查看结果</p>
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
              disabled={!session.isSuccess}
              onClick={() => input.current?.click()}
            />
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
        <ActionButton icon={ClockCounterClockwise} label="历史" onClick={() => setHistory(true)} />
        <ActionButton
          icon={UploadSimple}
          label="上传"
          tone="primary"
          disabled={!session.isSuccess || uploading !== null}
          onClick={() => input.current?.click()}
        />
      </footer>
      <Dialog open={history} onClose={() => setHistory(false)} title="历史视频" side>
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
                <CheckCircle aria-hidden="true" />
              ) : (
                <span className="history-status">
                  {v.latest_analysis?.status === 'failed'
                    ? '分析失败'
                    : stages[v.latest_analysis?.status || ''] || '正在处理'}
                </span>
              )}
            </button>
          ))
        )}
      </Dialog>
    </div>
  );
}
