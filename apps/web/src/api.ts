import type { components } from './api.generated';
export type Video = components['schemas']['VideoResponse'];
export type Analysis = components['schemas']['AnalysisResponse'];
export type Rally = components['schemas']['Rally'];
export class ApiError extends Error {
  constructor(
    message: string,
    readonly requestId?: string,
    readonly status?: number,
    readonly code?: string,
  ) {
    super(message);
  }
}
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch('/api/v1' + path, { credentials: 'same-origin', ...init });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new ApiError(
      body.error?.message || '请求失败，请稍后重试',
      body.error?.request_id,
      response.status,
      body.error?.code,
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
export function upload(file: File, progress: (percent: number) => void): Promise<Video> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/v1/videos');
    xhr.withCredentials = true;
    xhr.setRequestHeader(
      'Idempotency-Key',
      crypto.randomUUID?.() || String(Date.now()) + Math.random(),
    );
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) progress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onerror = () => reject(new ApiError('网络中断，请重新上传'));
    xhr.onload = () => {
      let body;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        reject(new ApiError('服务响应异常'));
        return;
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else
        reject(
          new ApiError(
            body.error?.message || '上传失败',
            body.error?.request_id,
            xhr.status,
            body.error?.code,
          ),
        );
    };
    const form = new FormData();
    form.append('file', file);
    xhr.send(form);
  });
}
type Event = {
  name: string;
  video_id?: string;
  analysis_id?: string;
  properties?: Record<string, unknown>;
};
let events: Event[] = [];
let flushTimer: ReturnType<typeof setTimeout> | undefined;
export function track(event: Event) {
  events.push(event);
  if (!flushTimer) flushTimer = setTimeout(flushEvents, 1500);
}
function flushEvents() {
  const batch = events.splice(0, 30);
  flushTimer = undefined;
  if (batch.length)
    void request('/events', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ events: batch }),
    }).catch(() => {});
  if (events.length) flushTimer = setTimeout(flushEvents, 1500);
}
