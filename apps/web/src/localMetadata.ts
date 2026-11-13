import type { Rally } from './api';

export type LocalMetadata = {
  title?: string;
  duration_s?: number;
  source_size_bytes?: number;
  rallies: Rally[];
  warnings: string[];
};
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value))
    throw new Error('元数据必须是 JSON 对象');
  return value as Record<string, unknown>;
}
const finite = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value);

export function parseLocalMetadata(value: unknown): LocalMetadata {
  const root = object(value);
  const source = root.latest_analysis === undefined ? root : object(root.latest_analysis);
  if (!Array.isArray(source.rallies)) throw new Error('元数据缺少 rallies 数组');
  if (root.duration_s !== undefined && (!finite(root.duration_s) || root.duration_s <= 0))
    throw new Error('duration_s 必须是大于零的秒数');
  if (
    root.source_size_bytes !== undefined &&
    (!finite(root.source_size_bytes) ||
      !Number.isSafeInteger(root.source_size_bytes) ||
      root.source_size_bytes <= 0)
  )
    throw new Error('source_size_bytes 必须是大于零的整数字节数');
  if (root.title !== undefined && typeof root.title !== 'string')
    throw new Error('title 必须是字符串');
  if (
    source.warnings !== undefined &&
    (!Array.isArray(source.warnings) || source.warnings.some((w) => typeof w !== 'string'))
  )
    throw new Error('warnings 必须是字符串数组');
  let previousEnd = 0;
  const ids = new Set<string>();
  const rallies = source.rallies.map((item, index): Rally => {
    const r = object(item);
    if (!finite(r.start_s) || !finite(r.end_s) || r.start_s < 0 || r.end_s <= r.start_s)
      throw new Error(`回合 ${index + 1} 时间无效：需要 0 ≤ start_s < end_s`);
    if (r.start_s < previousEnd) throw new Error(`回合 ${index + 1} 未按时间排序或发生重叠`);
    if (finite(root.duration_s) && r.end_s > root.duration_s)
      throw new Error(`回合 ${index + 1} 超过视频时长`);
    previousEnd = r.end_s;
    const id = r.id === undefined ? `local-rally-${index + 1}` : r.id;
    if (typeof id !== 'string' || !id || ids.has(id)) throw new Error('回合 id 必须是唯一字符串');
    ids.add(id);
    if (r.score !== undefined && r.score !== null && typeof r.score !== 'string')
      throw new Error(`回合 ${index + 1} score 必须是字符串或 null`);
    const status = r.score_status ?? 'unknown';
    if (status !== 'observed' && status !== 'inferred' && status !== 'unknown')
      throw new Error(`回合 ${index + 1} score_status 无效`);
    return {
      id,
      start_s: r.start_s,
      end_s: r.end_s,
      score: r.score as string | null | undefined,
      score_status: status,
    };
  });
  return {
    title: root.title as string | undefined,
    duration_s: root.duration_s as number | undefined,
    source_size_bytes: root.source_size_bytes as number | undefined,
    rallies,
    warnings: (source.warnings ?? []) as string[],
  };
}

export function localVideoMismatch(
  metadata: LocalMetadata,
  fileSize: number,
  actualDuration?: number,
): string | undefined {
  if (metadata.source_size_bytes !== undefined && metadata.source_size_bytes !== fileSize)
    return '原视频文件大小与分析 JSON 不一致，请选择对应的原视频。';
  if (
    metadata.duration_s !== undefined &&
    actualDuration !== undefined &&
    Math.abs(metadata.duration_s - actualDuration) > 0.25
  )
    return '原视频时长与分析 JSON 不一致，请选择对应的视频与 JSON。';
  return undefined;
}
