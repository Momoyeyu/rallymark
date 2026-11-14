import { useNextPreload } from './useNextPreload';
import { time } from './time';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  CaretDoubleLeft,
  CaretDoubleRight,
  Pause,
  Play,
  SpeakerHigh,
  SpeakerSlash,
  CornersOut,
  CornersIn,
} from '@phosphor-icons/react';
import { IconButton, AutoSwitch, Score } from '../ui/controls';
import { RallyBrowser } from '../ui/RallyBrowser';
import { Timeline } from '../ui/Timeline';
import {
  PlaybackController,
  currentRally,
  navigationTarget,
  type PlaybackCommand,
} from './controller';
import { track, type Video, type Analysis, type Rally } from '../api';

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
  const [isFullscreen, setIsFullscreen] = useState(false);
  useEffect(() => {
    const change = () => setIsFullscreen(document.fullscreenElement === shell.current);
    document.addEventListener('fullscreenchange', change);
    return () => document.removeEventListener('fullscreenchange', change);
  }, []);
  const [error, setError] = useState(''),
    [buffering, setBuffering] = useState(false);
  const rallies = analysis.rallies;
  const controller = useMemo(() => new PlaybackController(rallies), [rallies]);
  const hasScores = rallies.some((r) => r.score);
  const active = currentRally(rallies, position);
  const next = navigationTarget(rallies, position, 1);
  useNextPreload(
    media,
    mediaSrc ?? '/api/v1/videos/' + video.id + '/media',
    next >= 0 ? rallies[next].start_s : undefined,
    playing && !buffering,
    (properties) => record({ name: 'playback_prefetch', video_id: video.id, properties }),
  );
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
          tabIndex={0}
          aria-label={`${video.title}，按空格播放或暂停`}
          onKeyDown={(event) => {
            if (event.key === ' ' || event.key === 'Enter') {
              event.preventDefault();
              togglePlay();
            }
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
          <span className="buffering" role="status" aria-label="加载视频">
            <span className="loading-ring" />
          </span>
        )}
        <div className="video-tools">
          <span>
            {time(position)} / {time(video.duration_s)}
          </span>
          <div>
            <IconButton
              label={muted ? '开启声音' : '静音'}
              icon={muted ? SpeakerSlash : SpeakerHigh}
              onClick={() => setMuted(!muted)}
            />
            <IconButton
              label={isFullscreen ? '退出全屏' : '全屏'}
              icon={isFullscreen ? CornersIn : CornersOut}
              onClick={fullscreen}
            />
          </div>
        </div>
      </div>
      <div className="playback-panel">
        <div className="rally-heading">
          <div className="rally-position">
            <Score
              rally={active >= 0 ? rallies[active] : undefined}
              index={active}
              hasScores={hasScores}
            />
            <small className="rally-counter">
              {String(Math.max(0, active + 1)).padStart(2, '0')} /{' '}
              {String(rallies.length).padStart(2, '0')}
            </small>
          </div>
          <AutoSwitch
            checked={automatic}
            onClick={() => {
              execute(controller.toggle(media.current?.currentTime || 0));
              record({
                name: 'auto_skip_changed',
                video_id: video.id,
                properties: { enabled: controller.automatic },
              });
            }}
          />
        </div>
        <div className="transport">
          <IconButton
            label="上一回合"
            icon={CaretDoubleLeft}
            tone="surface"
            disabled={navigationTarget(rallies, position, -1) < 0}
            onClick={() => navigate(-1)}
          />
          <IconButton
            label={playing ? '暂停' : '播放'}
            icon={playing ? Pause : Play}
            tone="primary"
            size="large"
            onClick={togglePlay}
          />
          <IconButton
            label="下一回合"
            icon={CaretDoubleRight}
            tone="surface"
            disabled={navigationTarget(rallies, position, 1) < 0}
            onClick={() => navigate(1)}
          />
        </div>
        <Timeline
          position={position}
          duration={video.duration_s}
          rallies={rallies}
          onSeek={(value) => {
            const element = media.current;
            if (!element) return;
            execute(controller.manualSeek(value, !element.paused && value < video.duration_s));
            record({ name: 'manual_seek', video_id: video.id });
          }}
        />
        <div className="player-feedback" aria-live="polite">
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {!error && rallies.length === 0 && <p className="muted">暂无回合，可自由播放</p>}
        </div>
        <RallyBrowser
          rallies={rallies}
          active={active}
          hasScores={hasScores}
          thumbnail={
            local
              ? undefined
              : (r) =>
                  `/api/v1/videos/${video.id}/rallies/${r.id}/thumbnail?analysis_id=${analysis.id}`
          }
          onSelect={(index) => {
            execute(controller.select(index));
            record({ name: 'rally_navigation', video_id: video.id, properties: { index } });
          }}
        />
      </div>
    </section>
  );
  function executeTick(command: PlaybackCommand) {
    if (command.seekTo !== undefined || command.play !== undefined) execute(command);
  }
}
