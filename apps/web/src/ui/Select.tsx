import { useRef, useState } from 'react';
import { CaretDown, Check, FilmStrip, type Icon } from '@phosphor-icons/react';
import {
  autoUpdate,
  flip,
  FloatingFocusManager,
  FloatingPortal,
  offset,
  shift,
  size,
  useClick,
  useDismiss,
  useFloating,
  useInteractions,
  useListNavigation,
  useRole,
  useTypeahead,
} from '@floating-ui/react';

export type SelectOption = { value: string; label: string; detail?: string };
export function Select({
  label,
  value,
  options,
  onChange,
  icon: Glyph = FilmStrip,
}: {
  label: string;
  icon?: Icon;
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const selectedIndex = options.findIndex((option) => option.value === value);
  const elements = useRef<(HTMLElement | null)[]>([]);
  const labels = useRef<(string | null)[]>([]);
  labels.current = options.map((option) => option.label);
  const { refs, floatingStyles, context } = useFloating({
    open,
    onOpenChange: setOpen,
    placement: 'bottom-start',
    whileElementsMounted: autoUpdate,
    middleware: [
      offset(8),
      flip({ padding: 12 }),
      shift({ padding: 12 }),
      size({
        padding: 12,
        apply({ availableHeight, rects, elements }) {
          const available = Math.max(0, Math.min(384, availableHeight));
          const rows = Math.floor((available - 14) / 60);
          Object.assign(elements.floating.style, {
            width: `${rects.reference.width}px`,
            maxHeight: `${rows > 0 ? rows * 60 + 14 : available}px`,
          });
        },
      }),
    ],
  });
  const click = useClick(context);
  const dismiss = useDismiss(context);
  const role = useRole(context, { role: 'select' });
  const navigation = useListNavigation(context, {
    listRef: elements,
    activeIndex,
    selectedIndex,
    onNavigate: setActiveIndex,
    loop: true,
  });
  const typeahead = useTypeahead(context, {
    listRef: labels,
    activeIndex,
    onMatch(index) {
      if (open) setActiveIndex(index);
      else onChange(options[index].value);
    },
  });
  const { getReferenceProps, getFloatingProps, getItemProps } = useInteractions([
    click,
    dismiss,
    role,
    navigation,
    typeahead,
  ]);
  return (
    <>
      <button
        ref={refs.setReference}
        {...getReferenceProps()}
        type="button"
        className="select-trigger"
        aria-label={label}
        disabled={!options.length}
      >
        <Glyph className="select-icon" aria-hidden="true" />
        <span className="select-value">{options[selectedIndex]?.label ?? '选择视频'}</span>
        <CaretDown className={`select-caret ${open ? 'is-open' : ''}`} aria-hidden="true" />
      </button>
      {open && (
        <FloatingPortal root={refs.domReference.current?.closest('dialog') || undefined}>
          <FloatingFocusManager context={context} modal={false} initialFocus={-1}>
            <div
              ref={refs.setFloating}
              style={floatingStyles}
              {...getFloatingProps()}
              className="select-menu"
              aria-label={label}
            >
              {options.map((option, index) => (
                <button
                  type="button"
                  key={option.value}
                  ref={(node) => {
                    elements.current[index] = node;
                  }}
                  tabIndex={activeIndex === index ? 0 : -1}
                  {...getItemProps({
                    active: activeIndex === index,
                    selected: selectedIndex === index,
                    onClick() {
                      onChange(option.value);
                      setOpen(false);
                    },
                  })}
                  className="select-option"
                  data-value={option.value}
                >
                  <span className="select-option-copy">
                    <span>{option.label}</span>
                    {option.detail && <small>{option.detail}</small>}
                  </span>
                  <Check
                    aria-hidden="true"
                    className={selectedIndex === index ? 'is-selected' : 'is-unselected'}
                  />
                </button>
              ))}
            </div>
          </FloatingFocusManager>
        </FloatingPortal>
      )}
    </>
  );
}
