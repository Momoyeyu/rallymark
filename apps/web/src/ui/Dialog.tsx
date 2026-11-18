import { useEffect, useId, useRef, type ReactNode } from 'react';
import { X, type Icon } from '@phosphor-icons/react';
import { IconButton } from './controls';

export function Dialog({
  open,
  onClose,
  title,
  children,
  side = false,
  className = '',
  headingIcon: HeadingIcon,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  side?: boolean;
  className?: string;
  headingIcon?: Icon;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const label = useId();
  useEffect(() => {
    const element = dialog.current;
    if (open && !element?.open) element?.showModal();
    else if (!open && element?.open) element.close();
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = previous;
    };
  }, [open]);
  return (
    <dialog
      ref={dialog}
      className={`dialog ${side ? 'dialog-side' : ''} ${className}`}
      aria-labelledby={label}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClose={onClose}
      onKeyDown={(event) => {
        if (event.key !== 'Tab') return;
        const items = Array.from(
          event.currentTarget.querySelectorAll<HTMLElement>(
            'button:not([disabled]),a[href],input:not([hidden]),[tabindex]:not([tabindex="-1"])',
          ),
        ).filter(
          (item) =>
            item.getClientRects().length && !item.hasAttribute('data-floating-ui-focus-guard'),
        );
        const first = items[0],
          last = items.at(-1);
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="dialog-surface">
        <header className="dialog-heading">
          <div className="dialog-title">
            {HeadingIcon && <HeadingIcon aria-hidden="true" />}
            <h2 id={label}>{title}</h2>
          </div>
          <IconButton label={`关闭${title}`} icon={X} onClick={onClose} />
        </header>
        <div className="dialog-content">{children}</div>
      </div>
    </dialog>
  );
}
