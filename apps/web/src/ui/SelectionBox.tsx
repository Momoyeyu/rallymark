import { CheckSquare, MinusSquare, Square } from '@phosphor-icons/react';
export function SelectionBox({
  checked,
  label,
  onClick,
  disabled = false,
}: {
  checked: boolean | 'mixed';
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  const Glyph = checked === 'mixed' ? MinusSquare : checked ? CheckSquare : Square;
  return (
    <button
      type="button"
      className="selection-box"
      role="checkbox"
      aria-checked={checked}
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
    >
      <Glyph aria-hidden="true" weight={checked ? 'fill' : 'regular'} />
    </button>
  );
}
