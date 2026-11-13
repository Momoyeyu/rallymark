import { useEffect, useState } from 'react';
import { CaretLeft, CaretRight } from '@phosphor-icons/react';
import type { Rally } from '../api';
import { time } from '../player/time';
import { IconButton } from './controls';
import { RallyCard } from './RallyCard';
const pageSize = 3;
export function RallyBrowser({
  rallies,
  active,
  hasScores,
  thumbnail,
  onSelect,
}: {
  rallies: Rally[];
  active: number;
  hasScores: boolean;
  thumbnail?: (rally: Rally) => string;
  onSelect: (index: number) => void;
}) {
  const [page, setPage] = useState(0);
  useEffect(() => {
    if (active >= 0) setPage(Math.floor(active / pageSize));
  }, [active]);
  if (!rallies.length) return null;
  const pageCount = Math.ceil(rallies.length / pageSize);
  const current = Math.min(page, pageCount - 1);
  const start = current * pageSize;
  return (
    <section className="rally-browser" aria-label="回合列表">
      <div className="rally-browser-heading">
        <h2>回合</h2>
        <span className="rally-page-count" role="status">
          {start + 1}–{Math.min(start + pageSize, rallies.length)} / {rallies.length}
        </span>
        <div className="rally-page-actions">
          <IconButton
            label="上一页回合"
            icon={CaretLeft}
            disabled={current === 0}
            onClick={() => setPage(current - 1)}
          />
          <IconButton
            label="下一页回合"
            icon={CaretRight}
            disabled={current + 1 === pageCount}
            onClick={() => setPage(current + 1)}
          />
        </div>
      </div>
      <div className="rally-grid">
        {rallies.slice(start, start + pageSize).map((r, index) => (
          <RallyCard
            key={r.id}
            rally={r}
            index={start + index}
            hasScores={hasScores}
            selected={start + index === active}
            duration={time(r.end_s - r.start_s)}
            thumbnail={thumbnail?.(r)}
            onSelect={() => onSelect(start + index)}
          />
        ))}
      </div>
    </section>
  );
}
