import { useId, useState, type InputHTMLAttributes } from 'react';
import { Eye, EyeSlash, LockKey } from '@phosphor-icons/react';
import type { Icon } from '@phosphor-icons/react';
import { IconButton } from './controls';
import './fields.css';

export function Field({
  label,
  icon,
  hint,
  error,
  type,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & {
  label: string;
  icon?: Icon;
  hint?: string;
  error?: string;
}) {
  const id = useId();
  const [revealed, setRevealed] = useState(false);
  const password = type === 'password';
  const Glyph = icon ?? (password ? LockKey : undefined);
  const description = [props['aria-describedby'], hint && `${id}-hint`, error && `${id}-error`]
    .filter(Boolean)
    .join(' ');
  return (
    <div className="form-field" data-invalid={error ? '' : undefined}>
      <div className="form-field-label">
        <label htmlFor={id}>{label}</label>
        {hint && <span id={`${id}-hint`}>{hint}</span>}
      </div>
      <div className="form-field-control">
        {Glyph && <Glyph className="form-field-glyph" aria-hidden="true" />}
        <input
          {...props}
          id={id}
          type={password && revealed ? 'text' : type}
          aria-invalid={error ? true : props['aria-invalid']}
          aria-describedby={description || undefined}
        />
        {password && (
          <IconButton
            className="form-field-reveal"
            icon={revealed ? EyeSlash : Eye}
            label={revealed ? '隐藏密码' : '显示密码'}
            aria-controls={id}
            disabled={props.disabled}
            onClick={() => setRevealed(!revealed)}
          />
        )}
      </div>
      {error && (
        <p className="form-field-error" id={`${id}-error`} role="alert">
          {error}
        </p>
      )}
    </div>
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
