import { UploadSimple, Play, Scan, CursorClick, Stack } from '@phosphor-icons/react';
import { Brand } from '../ui/Brand';
import { ActionLink } from '../ui/Fields';
import { useDemos } from '../preview/useDemos';
import Player from '../player/Player';
import './site.css';
export default function Home() {
  const { items } = useDemos();
  const demo = items.find((x) => x.video.id === 'nina') || items[0];
  return (
    <div className="app-shell landing">
      <a className="skip-link" href="#main-content">
        跳到内容
      </a>
      <header className="app-header">
        <Brand />
        <ActionLink href="/preview" icon={Play} label="比赛预览" />
      </header>
      <main id="main-content">
        <div className="landing-intro">
          <section className="landing-hero">
            <h1>比赛很长，回看很快。</h1>
            <p>标记每一回合，随时跳转，原片完整保留。</p>
            <div className="landing-actions">
              <ActionLink href="/app" icon={UploadSimple} label="上传视频" primary />
              <ActionLink href="/preview" icon={Play} label="体验预览" />
            </div>
          </section>
          <section className="landing-showcase" aria-label="体验回合播放">
            {demo?.video.latest_analysis ? (
              <Player
                video={demo.video}
                analysis={demo.video.latest_analysis}
                mediaSrc={demo.media}
                posterSrc={demo.poster}
                local
              />
            ) : (
              <a className="landing-fallback" href="/preview">
                <Play size={48} />
                <span>体验回合播放</span>
              </a>
            )}
          </section>
        </div>
        <section className="landing-benefits" aria-label="产品功能">
          <div>
            <Scan />
            <h2>自动标记</h2>
            <p>识别回合与比分</p>
          </div>
          <div>
            <CursorClick />
            <h2>点击跳转</h2>
            <p>直达每一次交锋</p>
          </div>
          <div>
            <Stack />
            <h2>连续回看</h2>
            <p>自由切换连播与原片</p>
          </div>
        </section>
      </main>
      <footer className="landing-footer">
        <span>RallyMark</span>
        <span>每一回合，直接回看。</span>
      </footer>
    </div>
  );
}
