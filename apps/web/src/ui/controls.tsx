import type { ButtonHTMLAttributes } from 'react';
import type { Icon } from '@phosphor-icons/react';
import { ArrowsClockwise, Check, CircleDashed, Hash } from '@phosphor-icons/react';
import type { Rally } from '../api';

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  icon: Icon;
  label: string;
  tone?: 'plain' | 'primary' | 'surface';
  size?: 'normal' | 'large';
};
export function IconButton({
  icon: Glyph,
  label,
  tone = 'plain',
  size = 'normal',
  className = '',
  ...props
}: ButtonProps) {
  return (
    <button
      {...props}
      type={props.type ?? 'button'}
      className={`icon-button ${tone} ${size} ${className}`}
      aria-label={label}
      title={label}
    >
      <Glyph weight="bold" aria-hidden="true" />
    </button>
  );
}
export function AutoSwitch({ checked, onClick }: { checked: boolean; onClick: () => void }) {
  return (
    <button
      className="auto-toggle"
      role="switch"
      aria-label="自动跳转"
      aria-checked={checked}
      onClick={onClick}
      title={checked ? '自动跳转已开' : '自动跳转已关'}
    >
      <ArrowsClockwise aria-hidden="true" />
      <span className="switch-caption">自动</span>
      <span className={`switch ${checked ? 'on' : ''}`} aria-hidden="true">
        <i />
      </span>
    </button>
  );
}
function scoreLabel(rally: Rally, index: number, hasScores: boolean) {
  return hasScores ? rally.score || '—:—' : String(index + 1).padStart(2, '0');
}
export function Score({
  rally,
  index,
  hasScores,
}: {
  rally?: Rally;
  index: number;
  hasScores: boolean;
}) {
  const inferred = rally?.score_status === 'inferred';
  const observed = rally?.score_status === 'observed';
  const Glyph = rally?.score ? (observed ? Check : CircleDashed) : hasScores ? CircleDashed : Hash;
  const label = rally?.score
    ? inferred
      ? '推断比分'
      : observed
        ? '识别比分'
        : '待核比分'
    : hasScores
      ? '比分未知'
      : '回合序号';
  return (
    <span className="score-display" title={label} aria-label={label}>
      <b>{rally ? scoreLabel(rally, index, hasScores) : '—:—'}</b>
      <Glyph className={inferred ? 'score-inferred' : ''} aria-hidden="true" />
    </span>
  );
}

export function ActionButton({
  icon: Glyph,
  label,
  tone = 'surface',
  className = '',
  ...props
}: Omit<ButtonProps, 'size'>) {
  return (
    <button
      {...props}
      type={props.type ?? 'button'}
      className={`action-button ${tone} ${className}`}
    >
      <Glyph aria-hidden="true" />
      <span>{label}</span>
    </button>
  );
}
