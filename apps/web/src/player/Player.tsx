import { useEffect, useMemo, useRef, useState } from 'react';
import {
  CaretDoubleLeft,
  CaretDoubleRight,
  Pause,
  Play,
  SpeakerHigh,
  SpeakerSlash,
  CornersOut,
} from '@phosphor-icons/react';
import {
  PlaybackController,
  currentRally,
  navigationTarget,
  type PlaybackCommand,
} from './controller';
import { track, type Video, type Analysis, type Rally } from '../api';

export const time = (seconds: number) =>
  Math.floor(seconds / 60)
    .toString()
    .padStart(2, '0') +
  ':' +
  Math.floor(seconds % 60)
    .toString()
    .padStart(2, '0');
export function scoreLabel(rally: Rally, index: number, hasScores: boolean) {
  return hasScores ? rally.score || '比分待确认' : String(index + 1).padStart(2, '0');
}
export default function Player({
  video,
  analysis,
  mediaSrc,
  posterSrc,
  local = false,
  onDuration,
}: {
  video: Video;
  analysis: Analysis;
  mediaSrc?: string;
  posterSrc?: string;
  local?: boolean;
  onDuration?: (duration: number) => void;
}) {
  const record: typeof track = local ? () => {} : track;
  const media = useRef<HTMLVideoElement>(null);
  const shell = useRef<HTMLDivElement>(null);
  const sequence = useRef(0);
  const programmaticSeek = useRef(false);
  const [playing, setPlaying] = useState(false),
    [position, setPosition] = useState(0);
  const [automatic, setAutomatic] = useState(true),
    [muted, setMuted] = useState(false);
  const [error, setError] = useState(''),
    [buffering, setBuffering] = useState(false);
  const rallies = analysis.rallies;
  const controller = useMemo(() => new PlaybackController(rallies), [rallies]);
  const hasScores = rallies.some((r) => r.score);
  const active = currentRally(rallies, position);
  const execute = (command: PlaybackCommand) => {
    const element = media.current;
    if (!element) return;
    const current = ++sequence.current;
    if (command.play === false) element.pause();
    if (command.seekTo !== undefined) {
      programmaticSeek.current = true;
      element.currentTime = command.seekTo;
      setPosition(command.seekTo);
    }
    if (command.play === true) {
      const play = () => {
        if (current !== sequence.current) return;
        void element.play().catch((e) => {
          if (current === sequence.current && e.name !== 'AbortError')
            setError('播放失败，请再点一次播放');
        });
      };
      if (element.seeking) element.addEventListener('seeked', play, { once: true });
      play();
    }
    setAutomatic(controller.automatic);
  };
  useEffect(() => {
    setAutomatic(true);
    setError('');
    setPosition(0);
    setPlaying(false);
    return () => {
      sequence.current++;
    };
  }, [controller]);
  const navigate = (direction: -1 | 1) => {
    execute(controller.navigate(media.current?.currentTime || 0, direction));
    record({ name: 'rally_navigation', video_id: video.id, properties: { direction } });
  };
  const togglePlay = () => {
    const element = media.current;
    if (!element) return;
    setError('');
    if (element.paused) execute(controller.play(element.currentTime));
    else execute({ play: false });
  };
  const fullscreen = () => {
    const element = shell.current;
    if (document.fullscreenElement) void document.exitFullscreen();
    else if (element?.requestFullscreen)
      void element.requestFullscreen().catch(() => setError('当前浏览器不支持全屏，可横屏观看'));
    else {
      const native = media.current as
        (HTMLVideoElement & { webkitEnterFullscreen?: () => void }) | null;
      if (native?.webkitEnterFullscreen) native.webkitEnterFullscreen();
      else setError('可旋转手机横屏观看');
    }
  };
  return (
    <section className="player" ref={shell} aria-label="视频复盘播放器">
      <div className="video-stage">
        <video
          ref={media}
          src={mediaSrc ?? '/api/v1/videos/' + video.id + '/media'}
          poster={local ? posterSrc : (posterSrc ?? '/api/v1/videos/' + video.id + '/poster')}
          onLoadedMetadata={() => {
            const duration = media.current?.duration;
            if (duration && Number.isFinite(duration)) onDuration?.(duration);
          }}
          playsInline
          preload="metadata"
          muted={muted}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onWaiting={() => setBuffering(true)}
          onPlaying={() => setBuffering(false)}
          onSeeking={() => {
            if (!programmaticSeek.current && media.current) {
              controller.manualSeek(media.current.currentTime, !media.current.paused);
              setAutomatic(false);
              record({ name: 'manual_seek', video_id: video.id });
            }
          }}
          onSeeked={() => {
            programmaticSeek.current = false;
          }}
          onCanPlay={() => setBuffering(false)}
          onError={() => {
            setError('视频加载失败，请刷新重试');
            record({ name: 'playback_error', video_id: video.id });
          }}
          onTimeUpdate={() => {
            const e = media.current;
            if (!e) return;
            setPosition(e.currentTime);
            executeTick(controller.tick(e.currentTime, e.paused));
          }}
          onClick={togglePlay}
        />
        {buffering && (
          <span className="buffering" role="status">
            加载视频…
          </span>
        )}
        <div className="video-tools">
          <span>
            {time(position)} / {time(video.duration_s)}
          </span>
          <div>
            <button aria-label={muted ? '开启声音' : '静音'} onClick={() => setMuted(!muted)}>
              {muted ? <SpeakerSlash /> : <SpeakerHigh />}
            </button>
            <button aria-label="全屏" onClick={fullscreen}>
              <CornersOut />
            </button>
          </div>
        </div>
      </div>
      <div className="playback-panel">
        <div className="rally-heading">
          <span className="rally-position">
            {active >= 0
              ? scoreLabel(rallies[active], active, hasScores)
              : hasScores
                ? '比分待确认'
                : '—'}
            <small>
              {active >= 0 && rallies[active].score_status === 'inferred'
                ? '推断'
                : active >= 0
                  ? ' / ' + rallies.length
                  : ' / ' + rallies.length}
            </small>
          </span>
          <button
            className="auto-toggle"
            role="switch"
            aria-checked={automatic}
            aria-label="自动跳转"
            onClick={() => {
              execute(controller.toggle(media.current?.currentTime || 0));
              record({
                name: 'auto_skip_changed',
                video_id: video.id,
                properties: { enabled: controller.automatic },
              });
            }}
          >
            自动跳转
            <span className={'switch ' + (automatic ? 'on' : '')}>
              <i />
            </span>
          </button>
        </div>
        <div className="transport">
          <button
            aria-label="上一回合"
            disabled={navigationTarget(rallies, position, -1) < 0}
            onClick={() => navigate(-1)}
          >
            <CaretDoubleLeft weight="bold" />
          </button>
          <button className="play" aria-label={playing ? '暂停' : '播放'} onClick={togglePlay}>
            {playing ? <Pause weight="fill" /> : <Play weight="fill" />}
          </button>
          <button
            aria-label="下一回合"
            disabled={navigationTarget(rallies, position, 1) < 0}
            onClick={() => navigate(1)}
          >
            <CaretDoubleRight weight="bold" />
          </button>
        </div>
        <div className="seek-wrap">
          <div className="rally-marks" aria-hidden="true">
            {rallies.map((r) => (
              <i
                key={r.id}
                style={{
                  left: (r.start_s / video.duration_s) * 100 + '%',
                  width: ((r.end_s - r.start_s) / video.duration_s) * 100 + '%',
                }}
              />
            ))}
          </div>
          <input
            aria-label="视频进度"
            type="range"
            min="0"
            max={video.duration_s}
            step=".05"
            value={position}
            onChange={(e) => {
              const element = media.current;
              if (!element) return;
              execute(controller.manualSeek(Number(e.target.value), !element.paused));
              record({ name: 'manual_seek', video_id: video.id });
            }}
          />
        </div>
        <div className="seek-times">
          <span>{time(position)}</span>
          <span>{time(video.duration_s)}</span>
        </div>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        {rallies.length === 0 && <p className="notice">未识别到回合，可拖动时间轴查看原视频。</p>}
        <div className={'rally-strip' + (local ? ' local-rallies' : '')} aria-label="回合列表">
          {rallies.map((r, i) => (
            <button
              key={r.id}
              className={i === active ? 'selected' : ''}
              aria-label={'跳转回合 ' + (i + 1) + (r.score ? ' 比分 ' + r.score : '')}
              onClick={() => {
                execute(controller.select(i));
                record({ name: 'rally_navigation', video_id: video.id, properties: { index: i } });
              }}
            >
              {!local && (
                <img
                  loading="lazy"
                  alt=""
                  src={
                    '/api/v1/videos/' +
                    video.id +
                    '/rallies/' +
                    r.id +
                    '/thumbnail?analysis_id=' +
                    analysis.id
                  }
                />
              )}
              <span>{time(r.end_s - r.start_s)}</span>
              <strong>{scoreLabel(r, i, hasScores)}</strong>
              {r.score_status === 'inferred' && <small>推断</small>}
            </button>
          ))}
        </div>
      </div>
    </section>
  );
  function executeTick(command: PlaybackCommand) {
    if (command.seekTo !== undefined || command.play !== undefined) execute(command);
  }
}
