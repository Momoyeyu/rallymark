import { useMemo } from 'react';
import type { Rally } from '../api';
import { time } from '../player/time';
export function Timeline({
  position,
  duration,
  rallies,
  onSeek,
}: {
  position: number;
  duration: number;
  rallies: Rally[];
  onSeek: (value: number) => void;
}) {
  const percentage = duration ? Math.max(0, Math.min(100, (position / duration) * 100)) : 0;
  const marks = useMemo(
    () =>
      rallies
        .map((r) => {
          const x = (r.start_s / duration) * 1000;
          const width = Math.max(2, ((r.end_s - r.start_s) / duration) * 1000);
          return `M${x},0h${width}v4h-${width}z`;
        })
        .join(' '),
    [rallies, duration],
  );
  return (
    <div className="timeline">
      <div className="seek-wrap">
        <div className="timeline-rail" aria-hidden="true">
          <svg className="rally-marks" viewBox="0 0 1000 4" preserveAspectRatio="none">
            <path d={marks} />
          </svg>
          <div className="timeline-fill" style={{ width: `${percentage}%` }} />
          <span className="timeline-thumb" style={{ left: `${percentage}%` }} />
        </div>
        <input
          aria-label="视频进度"
          name="position"
          type="range"
          min={0}
          max={duration}
          step={0.05}
          value={position}
          aria-valuetext={`${time(position)} / ${time(duration)}`}
          onChange={(event) => onSeek(Number(event.target.value))}
          onKeyDown={(event) => {
            const offsets: Record<string, number> = {
              ArrowLeft: -5,
              ArrowRight: 5,
              ArrowDown: -1,
              ArrowUp: 1,
              PageDown: -10,
              PageUp: 10,
            };
            if (event.key in offsets || event.key === 'Home' || event.key === 'End') {
              event.preventDefault();
              onSeek(
                event.key === 'Home'
                  ? 0
                  : event.key === 'End'
                    ? duration
                    : Math.max(0, Math.min(duration, position + offsets[event.key])),
              );
            }
          }}
        />
      </div>
      <div className="seek-times">
        <span>{time(position)}</span>
        <span>{time(duration)}</span>
      </div>
    </div>
  );
}
