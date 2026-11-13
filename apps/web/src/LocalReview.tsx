import { useEffect, useRef, useState } from 'react';
import { GearSix, FilmStrip, Trash } from '@phosphor-icons/react';
import { IconButton, ActionButton } from './ui/controls';
import { Select } from './ui/Select';
import { Dialog } from './ui/Dialog';
import { FilePicker } from './ui/FilePicker';
import { time } from './player/time';
import { Brand } from './ui/Brand';
import { Notice } from './ui/Notice';
import Player from './player/Player';
import './LocalReview.css';
import { localVideoMismatch, parseLocalMetadata, type LocalMetadata } from './localMetadata';
import type { Analysis, Video } from './api';

type Clip = {
  id: string;
  file: Pick<File, 'name' | 'size'>;
  url: string;
  metadata?: LocalMetadata;
  metadataName?: string;
  revision?: number;
  duration?: number;
  error?: string;
};
const timestamp = '2000-01-01T00:00:00Z';

export default function LocalReview() {
  const [clips, setClips] = useState<Clip[]>([]);
  const [selected, setSelected] = useState('');
  const [configOpen, setConfigOpen] = useState(
    !new URLSearchParams(location.search).has('preview'),
  );
  const [confirmRemove, setConfirmRemove] = useState(false);
  const urls = useRef(new Set<string>());
  const removalActions = useRef<HTMLDivElement>(null);
  function showRemoveConfirmation(value: boolean) {
    setConfirmRemove(value);
    requestAnimationFrame(() => removalActions.current?.querySelector('button')?.focus());
  }
  const entry = clips.find((clip) => clip.id === selected);
  useEffect(() => {
    const owned = urls.current;
    return () => {
      owned.forEach((url) => URL.revokeObjectURL(url));
      owned.clear();
    };
  }, []);
  useEffect(() => {
    if (!new URLSearchParams(location.search).has('preview')) return;
    const abort = new AbortController();
    void fetch('/__local-preview/manifest', { signal: abort.signal })
      .then((response) => {
        if (!response.ok) throw new Error('预览未就绪');
        return response.json();
      })
      .then(({ clips: incoming }) => {
        const ready: Clip[] = incoming.map(
          (clip: { id: string; name: string; size: number; url: string; metadata: unknown }) => ({
            id: clip.id,
            file: { name: clip.name, size: clip.size },
            url: clip.url,
            metadata: parseLocalMetadata(clip.metadata),
            metadataName: `${clip.id}.json`,
            revision: 1,
          }),
        );
        setClips(ready);
        const saved = new URLSearchParams(location.search).get('clip');
        setSelected(
          ready.find((clip) => clip.id === saved)?.id ??
            ready.find((clip) => clip.id === 'nina')?.id ??
            ready[0]?.id ??
            '',
        );
        setConfigOpen(false);
      })
      .catch((error) => {
        if (error.name !== 'AbortError') setPreviewError(error.message);
      });
    return () => abort.abort();
  }, []);
  const [previewError, setPreviewError] = useState('');
  function addVideos(files: FileList | null) {
    const added = Array.from(files ?? []).map((file): Clip => {
      const url = URL.createObjectURL(file);
      urls.current.add(url);
      return { id: crypto.randomUUID(), file, url };
    });
    setClips((previous) => [...previous, ...added]);
    if (added.length) {
      setSelected(added[0].id);
      setConfigOpen(true);
    }
  }
  async function addMetadata(file: File | undefined) {
    if (!file || !entry) return;
    const id = entry.id;
    try {
      const metadata = parseLocalMetadata(JSON.parse(await file.text()));
      setClips((previous) =>
        previous.map((clip) =>
          clip.id === id
            ? {
                ...clip,
                metadata,
                metadataName: file.name,
                revision: (clip.revision ?? 0) + 1,
                error: undefined,
              }
            : clip,
        ),
      );
      setConfigOpen(false);
    } catch (error) {
      setConfigOpen(true);
      setClips((previous) =>
        previous.map((clip) =>
          clip.id === id
            ? {
                ...clip,
                metadata: undefined,
                metadataName: file.name,
                error: error instanceof Error ? error.message : 'JSON 读取失败',
              }
            : clip,
        ),
      );
    }
  }
  const metadata = entry?.metadata;
  const duration =
    entry?.duration ?? metadata?.duration_s ?? Math.max(1, metadata?.rallies.at(-1)?.end_s ?? 1);
  const outside = metadata && metadata.rallies.some((rally) => rally.end_s > duration);
  const mismatch =
    metadata && entry ? localVideoMismatch(metadata, entry.file.size, entry.duration) : undefined;
  const analysis: Analysis | undefined =
    metadata && entry
      ? {
          id: entry.id + ':' + entry.revision,
          video_id: entry.id,
          status: 'succeeded',
          progress: null,
          rallies: metadata.rallies,
          warnings: metadata.warnings,
          error: null,
          created_at: timestamp,
          config_hash: 'local',
          algorithm_version: 'local',
        }
      : undefined;
  const video: Video | undefined =
    analysis && entry
      ? {
          id: entry.id,
          title: metadata?.title || entry.file.name,
          duration_s: duration,
          width: 0,
          height: 0,
          size_bytes: entry.file.size,
          created_at: timestamp,
          expires_at: timestamp,
          latest_analysis: analysis,
        }
      : undefined;
  function chooseClip(id: string) {
    setSelected(id);
    setConfirmRemove(false);
    setConfigOpen(!clips.find((clip) => clip.id === id)?.metadata);
    const url = new URL(location.href);
    url.searchParams.set('clip', id);
    window.history.replaceState({}, '', url);
  }
  function removeClip() {
    if (!entry) return;
    URL.revokeObjectURL(entry.url);
    urls.current.delete(entry.url);
    const next = clips.find((clip) => clip.id !== entry.id);
    setClips((previous) => previous.filter((clip) => clip.id !== entry.id));
    setSelected(next?.id ?? '');
    const url = new URL(location.href);
    if (next) url.searchParams.set('clip', next.id);
    else url.searchParams.delete('clip');
    window.history.replaceState({}, '', url);
    setConfirmRemove(false);
    setConfigOpen(!next?.metadata);
  }
  return (
    <div className="app-shell local-review">
      <a className="skip-link" href="#main-content">
        跳到内容
      </a>
      <header className="app-header">
        <Brand href="?local=1&preview=1" />
        <span className="context-badge">本地复盘</span>
      </header>
      <main id="main-content">
        <div className="workspace-toolbar">
          <div className="workspace-title">
            <FilmStrip aria-hidden="true" />
            <h1>{metadata?.title || entry?.file.name || '本地复盘'}</h1>
          </div>
          <section className="workspace-actions" aria-label="本地文件">
            {clips.length > 0 && (
              <Select
                label="当前视频"
                value={selected}
                options={clips.map((clip) => ({
                  value: clip.id,
                  label: clip.metadata?.title || clip.file.name,
                  detail: clip.metadata
                    ? `${clip.metadata.rallies.length} 回合 / ${time(clip.metadata.duration_s || clip.duration || 0)}`
                    : '待载入',
                }))}
                onChange={chooseClip}
              />
            )}
            <IconButton
              tone="surface"
              label="本地文件设置"
              icon={GearSix}
              aria-expanded={configOpen}
              onClick={() => {
                setConfirmRemove(false);
                setConfigOpen(true);
              }}
            />
          </section>
        </div>
        {previewError && (
          <p role="alert" className="error-banner">
            {previewError}，请重启本地预览服务。
          </p>
        )}
        {entry?.error && !configOpen && (
          <p role="alert" className="error-banner">
            {entry.error}
          </p>
        )}
        {outside && (
          <p role="alert" className="error-banner">
            回合时间超过原视频时长，请选择与此视频匹配的 JSON。
          </p>
        )}
        {mismatch && (
          <p role="alert" className="error-banner">
            {mismatch}
          </p>
        )}
        {video && analysis && entry && !outside && !mismatch ? (
          <>
            <Player
              key={analysis.id}
              video={video}
              analysis={analysis}
              local
              mediaSrc={entry.url}
              onDuration={(actual) => {
                if (entry.duration !== actual)
                  setClips((previous) =>
                    previous.map((clip) =>
                      clip.id === entry.id ? { ...clip, duration: actual } : clip,
                    ),
                  );
              }}
            />
            <Notice messages={analysis.warnings} />
          </>
        ) : (
          !configOpen && (
            <section className="welcome">
              <FilmStrip className="empty-icon" aria-hidden="true" />
              <h2>
                {new URLSearchParams(location.search).has('preview') && !previewError
                  ? '读取视频…'
                  : '添加视频'}
              </h2>
              <p>选择原片与分析数据，直接复盘。</p>
              <ActionButton icon={GearSix} label="选择文件" onClick={() => setConfigOpen(true)} />
            </section>
          )
        )}
      </main>
      <Dialog open={configOpen} onClose={() => setConfigOpen(false)} title="本地文件">
        <p className="muted">文件仅在本机读取，不会上传。</p>
        <FilePicker
          label="原视频（可多选）"
          accept="video/*,.mp4,.mov,.m4v,.webm"
          multiple
          description={clips.length ? `${clips.length} 段已载入` : 'MP4 / MOV / WebM'}
          onChange={addVideos}
        />
        {entry && (
          <>
            <FilePicker
              key={selected}
              label="此视频的分析 JSON"
              accept="application/json,.json"
              description={entry.metadataName || entry.file.name}
              onChange={(files) => void addMetadata(files?.[0])}
            />
            {entry.error && (
              <p className="inline-error" role="alert">
                {entry.error}，请重新选择 JSON。
              </p>
            )}
            <div className="dialog-footer" ref={removalActions}>
              {confirmRemove ? (
                <>
                  <span className="muted">从复盘列表移除？原文件不会删除。</span>
                  <div className="button-row">
                    <ActionButton
                      icon={GearSix}
                      label="保留"
                      onClick={() => showRemoveConfirmation(false)}
                    />
                    <ActionButton icon={Trash} label="移除" tone="danger" onClick={removeClip} />
                  </div>
                </>
              ) : (
                <ActionButton
                  icon={Trash}
                  label="移除此视频"
                  tone="danger"
                  onClick={() => showRemoveConfirmation(true)}
                />
              )}
            </div>
          </>
        )}
      </Dialog>
    </div>
  );
}
