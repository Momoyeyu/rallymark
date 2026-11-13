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
  return (
    <button
      className={`rally-card ${selected ? 'selected' : ''} ${thumbnail ? '' : 'compact'}`}
      aria-label={`跳转回合 ${index + 1}${rally.score ? ' 比分 ' + rally.score : ''}`}
      aria-current={selected ? 'true' : undefined}
      onClick={onSelect}
    >
      {thumbnail && <img loading="lazy" alt="" src={thumbnail} />}
      <span className="rally-duration">{duration}</span>
      <Score rally={rally} index={index} hasScores={hasScores} />
    </button>
  );
}
