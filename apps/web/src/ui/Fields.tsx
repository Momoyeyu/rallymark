import { useId, type InputHTMLAttributes } from 'react';
import type { Icon } from '@phosphor-icons/react';
export function Field({
  label,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  const id = useId();
  return (
    <label className="form-field" htmlFor={id}>
      <span>{label}</span>
      <input {...props} id={id} />
    </label>
  );
}
export function ActionLink({
  href,
  icon: Glyph,
  label,
  primary = false,
}: {
  href: string;
  icon: Icon;
  label: string;
  primary?: boolean;
}) {
  return (
    <a className={`action-button ${primary ? 'primary' : 'surface'}`} href={href}>
      <Glyph aria-hidden="true" />
      <span>{label}</span>
    </a>
  );
}
