import { cloneElement, useState, type HTMLAttributes, type ReactElement } from 'react';
import {
  autoUpdate,
  flip,
  FloatingPortal,
  offset,
  shift,
  useClick,
  useDismiss,
  useFloating,
  useFocus,
  useHover,
  useInteractions,
  useRole,
} from '@floating-ui/react';

export function Tooltip({
  label,
  children,
  tap = false,
}: {
  label: string;
  children: ReactElement<HTMLAttributes<HTMLElement>>;
  tap?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const { refs, floatingStyles, context } = useFloating({
    open,
    onOpenChange: setOpen,
    placement: 'top',
    whileElementsMounted: autoUpdate,
    middleware: [offset(8), flip({ padding: 12 }), shift({ padding: 12 })],
  });
  const hover = useHover(context, { move: false, mouseOnly: tap, delay: { open: 400, close: 80 } });
  const click = useClick(context, { enabled: tap, ignoreMouse: true });
  const focus = useFocus(context);
  const dismiss = useDismiss(context);
  const role = useRole(context, { role: 'tooltip' });
  const { getReferenceProps, getFloatingProps } = useInteractions([
    hover,
    click,
    focus,
    dismiss,
    role,
  ]);
  return (
    <>
      {cloneElement(children, getReferenceProps({ ...children.props, ref: refs.setReference }))}
      {open && (
        <FloatingPortal
          root={
            refs.domReference.current?.closest('dialog') ??
            (document.fullscreenElement?.contains(refs.domReference.current ?? null)
              ? (document.fullscreenElement as HTMLElement)
              : undefined)
          }
        >
          <div
            ref={refs.setFloating}
            style={floatingStyles}
            {...getFloatingProps()}
            className="tooltip"
          >
            {label}
          </div>
        </FloatingPortal>
      )}
    </>
  );
}
