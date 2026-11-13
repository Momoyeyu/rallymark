import { useState } from 'react';
import { Play } from '@phosphor-icons/react';
import type { Rally } from '../api';
import { Score } from './controls';
export function RallyCard({
  rally,
  index,
  hasScores,
  selected,
  duration,
  thumbnail,
  onSelect,
}: {
  rally: Rally;
  index: number;
  hasScores: boolean;
  selected: boolean;
  duration: string;
  thumbnail?: string;
  onSelect: () => void;
}) {
  const [imageFailed, setImageFailed] = useState(false);
  return (
    <button
      className={`rally-card ${selected ? 'selected' : ''} ${thumbnail ? '' : 'compact'}`}
      aria-label={`跳转回合 ${index + 1}${rally.score ? ' 比分 ' + rally.score : ''}`}
      aria-current={selected ? 'true' : undefined}
      onClick={onSelect}
    >
      {thumbnail && (
        <div className="rally-thumbnail">
          {!imageFailed ? (
            <img
              width={160}
              height={90}
              loading="lazy"
              alt=""
              src={thumbnail}
              onError={() => setImageFailed(true)}
            />
          ) : (
            <Play aria-hidden="true" />
          )}
        </div>
      )}
      <span className="rally-duration">{duration}</span>
      <Score rally={rally} index={index} hasScores={hasScores} />
    </button>
  );
}
