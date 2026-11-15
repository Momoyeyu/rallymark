import { useState } from 'react';
import { FilmStrip, ArrowClockwise } from '@phosphor-icons/react';
import Player from '../player/Player';
import { Brand } from '../ui/Brand';
import { Select } from '../ui/Select';
import { Notice } from '../ui/Notice';
import { ActionButton } from '../ui/controls';
import { time } from '../player/time';
import { useDemos } from './useDemos';

export default function Preview() {
  const [selected, setSelected] = useState(
    () => new URLSearchParams(location.search).get('clip') || 'nina',
  );
  const [revision, reload] = useState(0);
  const { items, error } = useDemos(revision);
  const entry = items.find((item) => item.video.id === selected) || items[0];
  function choose(id: string) {
    setSelected(id);
    const url = new URL(location.href);
    url.searchParams.set('clip', id);
    history.replaceState({}, '', url);
  }
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳到内容
      </a>
      <header className="app-header">
        <Brand href="/" />
        <span className="context-badge">比赛预览</span>
      </header>
      <main id="main-content">
        {error ? (
          <section className="status-page" role="alert">
            <FilmStrip size={44} />
            <h1>暂未载入</h1>
            <ActionButton icon={ArrowClockwise} label="重试" onClick={() => reload((n) => n + 1)} />
          </section>
        ) : entry ? (
          <>
            <div className="workspace-toolbar">
              <div className="workspace-title">
                <FilmStrip aria-hidden="true" />
                <h1>{entry.video.title}</h1>
              </div>
              <section className="workspace-actions" aria-label="选择比赛">
                <Select
                  label="当前视频"
                  value={entry.video.id}
                  options={items.map(({ video }) => ({
                    value: video.id,
                    label: video.title,
                    detail: `${video.latest_analysis?.rallies.length || 0} 回合 / ${time(video.duration_s)}`,
                  }))}
                  onChange={choose}
                />
              </section>
            </div>
            {entry.video.latest_analysis && (
              <Player
                key={entry.video.id}
                video={entry.video}
                analysis={entry.video.latest_analysis}
                mediaSrc={entry.media}
                posterSrc={entry.poster}
                local
              />
            )}
            <Notice messages={entry.video.latest_analysis?.warnings || []} />
          </>
        ) : (
          <section className="status-page" aria-live="polite">
            <p>读取比赛</p>
          </section>
        )}
      </main>
    </div>
  );
}
