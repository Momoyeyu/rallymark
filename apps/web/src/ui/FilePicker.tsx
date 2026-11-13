import { useRef, type ChangeEvent } from 'react';
import { FileArrowUp } from '@phosphor-icons/react';
export function FilePicker({
  label,
  accept,
  multiple = false,
  description,
  onChange,
}: {
  label: string;
  accept: string;
  multiple?: boolean;
  description?: string;
  onChange: (files: FileList | null) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <div className="file-picker">
      <input
        ref={input}
        type="file"
        name={label}
        aria-label={label}
        accept={accept}
        multiple={multiple}
        hidden
        onChange={(event: ChangeEvent<HTMLInputElement>) => {
          onChange(event.target.files);
          event.target.value = '';
        }}
      />
      <button type="button" className="file-picker-button" onClick={() => input.current?.click()}>
        <FileArrowUp aria-hidden="true" />
        <span>
          <strong>{label.includes('JSON') ? '分析数据' : '原始视频'}</strong>
          <small>{description ?? (multiple ? '可选多段' : '选择文件')}</small>
        </span>
        <span className="file-picker-action">选择</span>
      </button>
    </div>
  );
}
