import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Eye, Trash, ArrowCounterClockwise, CaretLeft, CaretRight } from '@phosphor-icons/react';
import { adminRequest, bytes, type ManagedVideoList } from './api';
import type { Video } from '../api';
import Player from '../player/Player';
import { ErrorNotice } from '../ui/ErrorNotice';
import { Field } from '../ui/Fields';
import { Dialog } from '../ui/Dialog';
import { ActionButton, IconButton } from '../ui/controls';
import { time } from '../player/time';
const statusNames: Record<string, string> = {
  succeeded: '完成',
  failed: '失败',
  queued: '排队',
  preparing: '准备',
  downloading: '准备',
  tad: '分析',
  ocr: '分析',
  postprocessing: '分析',
};
export default function Videos({
  trashed,
  onError,
}: {
  trashed: boolean;
  onError: (e: unknown) => void;
}) {
  const client = useQueryClient();
  const [dialogError, setDialogError] = useState<unknown>(null);
  const [input, setInput] = useState(''),
    [search, setSearch] = useState(''),
    [page, setPage] = useState(1);
  const [preview, setPreview] = useState<Video | null>(null),
    [confirm, setConfirm] = useState<Video | null>(null),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(input);
      setPage(1);
    }, 300);
    return () => clearTimeout(timer);
  }, [input]);
  const list = useQuery({
    queryKey: ['admin', 'videos', trashed, search, page],
    queryFn: () =>
      adminRequest<ManagedVideoList>(
        `/videos?trashed=${trashed}&q=${encodeURIComponent(search)}&page=${page}`,
      ),
    refetchInterval: 15000,
  });
  async function change(v: Video, action: 'trash' | 'restore') {
    setBusy(true);
    setDialogError(null);
    try {
      await adminRequest(`/videos/${v.id}/${action}`, { method: 'POST' });
      setConfirm(null);
      await client.invalidateQueries({ queryKey: ['admin'] });
    } catch (e) {
      if (confirm) setDialogError(e);
      else onError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section aria-label={trashed ? '回收站' : '视频管理'}>
      <div className="admin-section-heading">
        <h1>{trashed ? '回收站' : '视频'}</h1>
        <span className="admin-count">{list.data?.total ?? '—'} 项</span>
      </div>
      {trashed && (
        <p className="admin-hint">移入后对原上传者隐藏，保留期内可以恢复；到期后清理。</p>
      )}
      <div className="admin-search">
        <Field
          label="搜索视频"
          type="search"
          placeholder="视频名称"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          maxLength={100}
        />
      </div>
      {list.isPending ? (
        <p role="status">读取视频</p>
      ) : list.isError ? (
        <p role="alert">视频暂未载入</p>
      ) : !list.data.items.length ? (
        <div className="admin-empty">
          <Trash size={32} />
          <p>{trashed ? '回收站为空' : '没有匹配的视频'}</p>
        </div>
      ) : (
        <div className="admin-list">
          {list.data.items.map((v) => {
            const status = v.latest_analysis?.status || '';
            const active = !!status && !['succeeded', 'failed'].includes(status);
            return (
              <div className="admin-row video-row" key={v.id}>
                <div className="admin-row-title">
                  <strong title={v.title}>{v.title}</strong>
                  <span>
                    {time(v.duration_s)} / {bytes(v.size_bytes)} /{' '}
                    {new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit' }).format(
                      new Date(v.created_at),
                    )}
                  </span>
                </div>
                <span className={`state-badge ${status === 'succeeded' ? 'good' : ''}`}>
                  {statusNames[status] || '未分析'}
                </span>
                <div className="admin-row-actions">
                  <IconButton
                    icon={Eye}
                    label={`预览${v.title}`}
                    onClick={() => setPreview(v)}
                    disabled={status === 'preparing'}
                  />
                  {trashed ? (
                    <IconButton
                      icon={ArrowCounterClockwise}
                      label={`恢复${v.title}`}
                      onClick={() => void change(v, 'restore')}
                      disabled={busy || active}
                    />
                  ) : (
                    <IconButton
                      icon={Trash}
                      label={`移入回收站${v.title}`}
                      onClick={() => {
                        setDialogError(null);
                        setConfirm(v);
                      }}
                      disabled={active}
                    />
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
      <div className="admin-pagination">
        <IconButton
          icon={CaretLeft}
          label="上一页"
          disabled={page <= 1 || list.isFetching}
          onClick={() => setPage((p) => p - 1)}
        />
        <span>
          {page} / {Math.max(1, Math.ceil((list.data?.total || 0) / 20))}
        </span>
        <IconButton
          icon={CaretRight}
          label="下一页"
          disabled={page * 20 >= (list.data?.total || 0) || list.isFetching}
          onClick={() => setPage((p) => p + 1)}
        />
      </div>
      <Dialog open={!!confirm} title="移入回收站" onClose={() => !busy && setConfirm(null)}>
        <ErrorNotice error={dialogError} />
        <p className="admin-hint">视频将对上传者隐藏，保留期内可以恢复。</p>
        <ActionButton
          icon={Trash}
          label={busy ? '处理中' : '移入回收站'}
          tone="danger"
          disabled={busy}
          onClick={() => confirm && void change(confirm, 'trash')}
        />
      </Dialog>
      <Dialog open={!!preview} title="视频预览" onClose={() => setPreview(null)}>
        {preview && (
          <Player
            key={preview.id}
            video={preview}
            analysis={
              preview.latest_analysis ?? {
                id: 'none',
                video_id: preview.id,
                status: 'succeeded',
                rallies: [],
                warnings: [],
                error: null,
                progress: null,
                created_at: preview.created_at,
                config_hash: '',
                algorithm_version: '',
              }
            }
            mediaSrc={`/api/v1/admin/videos/${preview.id}/media`}
            local
          />
        )}
      </Dialog>
    </section>
  );
}
