import { request } from '../api';
import type { components } from '../api.generated';
export type Storage = components['schemas']['StorageView'];
export type ManagedVideoList = components['schemas']['ManagedVideoList'];
export type User = components['schemas']['UserView'];
export const adminRequest = <T>(path: string, init?: RequestInit) =>
  request<T>('/admin' + path, init);
export function jsonRequest(method: string, body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}
export function bytes(n: number) {
  return Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 }).format(n / 1024 ** 3) + ' GiB';
}
