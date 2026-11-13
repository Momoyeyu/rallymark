export function Progress({
  label,
  value,
  max = 100,
}: {
  label: string;
  value?: number;
  max?: number;
}) {
  const fraction = value === undefined ? undefined : Math.max(0, Math.min(1, value / max));
  return (
    <div
      className={`progress ${fraction === undefined ? 'progress-pending' : ''}`}
      role="progressbar"
      aria-label={label}
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={max}
    >
      <span style={fraction === undefined ? undefined : { transform: `scaleX(${fraction})` }} />
    </div>
  );
}
