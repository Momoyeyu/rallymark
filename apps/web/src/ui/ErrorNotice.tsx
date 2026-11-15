import { ApiError } from '../api';
export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div className="admin-error" role="alert">
      <p>{error instanceof Error ? error.message : '操作失败，请重试'}</p>
      {error instanceof ApiError && error.requestId && <small>问题编号 {error.requestId}</small>}
    </div>
  );
}
