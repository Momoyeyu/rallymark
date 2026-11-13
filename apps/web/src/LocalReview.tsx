import { useEffect, useRef, useState } from 'react';
import { GearSix, X, Trash } from '@phosphor-icons/react';
import { IconButton } from './ui/controls';
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
  const [configOpen, setConfigOpen] = useState(true);
  const urls = useRef(new Set<string>());
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
        setSelected(ready.find((clip) => clip.id === 'nina')?.id ?? ready[0]?.id ?? '');
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
  return (
    <div className="app-shell local-review">
      <header className="app-header">
        <Brand href="?local=1&preview=1" />
        <span className="muted">本地复盘</span>
      </header>
      <main>
        <section className="local-files" aria-label="本地文件">
          {clips.length > 0 && (
            <div className="local-current">
              <label>
                当前视频
                <select
                  aria-label="当前视频"
                  value={selected}
                  onChange={(event) => {
                    const id = event.target.value;
                    setSelected(id);
                    setConfigOpen(!clips.find((clip) => clip.id === id)?.metadata);
                  }}
                >
                  {clips.map((clip, index) => (
                    <option key={clip.id} value={clip.id}>
                      {index + 1}. {clip.file.name}
                      {clip.metadata ? ' · 已载入回合' : ''}
                    </option>
                  ))}
                </select>
              </label>
              <IconButton
                label="本地文件设置"
                icon={configOpen ? X : GearSix}
                aria-expanded={configOpen}
                aria-controls="local-file-config"
                onClick={() => setConfigOpen(!configOpen)}
              />
            </div>
          )}
          <div id="local-file-config" className="local-config" hidden={!configOpen}>
            <h1>打开原视频与分析 JSON</h1>
            <p className="muted">
              文件仅在此浏览器读取，无需上传、API 或 GPU。可添加多段视频，分别选择对应
              JSON；刷新后需重新选择。
            </p>
            <label>
              原视频（可多选）
              <input
                type="file"
                accept="video/*,.mp4,.mov,.m4v,.webm"
                multiple
                onChange={(event) => {
                  addVideos(event.target.files);
                  event.target.value = '';
                }}
              />
            </label>
            {clips.length > 0 && (
              <>
                <label>
                  此视频的分析 JSON
                  <input
                    key={selected}
                    type="file"
                    accept="application/json,.json"
                    onChange={(event) => {
                      void addMetadata(event.target.files?.[0]);
                      event.target.value = '';
                    }}
                  />
                </label>
                {entry?.metadataName && (
                  <p className="muted">
                    {entry.metadataName} · {metadata?.rallies.length ?? 0} 个回合
                  </p>
                )}
                <IconButton
                  label="移除此视频"
                  icon={Trash}
                  onClick={() => {
                    if (!entry) return;
                    URL.revokeObjectURL(entry.url);
                    urls.current.delete(entry.url);
                    const next = clips.find((clip) => clip.id !== entry.id);
                    setClips((previous) => previous.filter((clip) => clip.id !== entry.id));
                    setSelected(next?.id ?? '');
                    setConfigOpen(!next?.metadata);
                  }}
                />
              </>
            )}
          </div>
        </section>
        {previewError && (
          <p role="alert" className="error-banner">
            {previewError}
          </p>
        )}
        {entry?.error && (
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
        {video && analysis && entry && !outside && !mismatch && (
          <>
            <div className="video-title">
              <h1>{video.title}</h1>
            </div>
            <Player
              key={analysis.id}
              video={video}
              analysis={analysis}
              local
              mediaSrc={entry.url}
              onDuration={(actual) => {
                if (entry.duration === actual) return;
                setClips((previous) =>
                  previous.map((clip) =>
                    clip.id === entry.id ? { ...clip, duration: actual } : clip,
                  ),
                );
              }}
            />
            <Notice messages={analysis.warnings} />
          </>
        )}
      </main>
    </div>
  );
}
