import { describe, expect, it } from 'vitest';
import { localVideoMismatch, parseLocalMetadata } from './localMetadata';

describe('local review metadata', () => {
  it('accepts optional source size and rejects invalid byte counts', () => {
    expect(parseLocalMetadata({ source_size_bytes: 1200, rallies: [] }).source_size_bytes).toBe(
      1200,
    );
    expect(parseLocalMetadata({ rallies: [] }).source_size_bytes).toBeUndefined();
    for (const size of [0, -1, 0.5, '1200', NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
      expect(() => parseLocalMetadata({ source_size_bytes: size, rallies: [] })).toThrow();
    }
  });
  it('checks size and observed duration without requiring either in old metadata', () => {
    const metadata = parseLocalMetadata({ source_size_bytes: 1200, duration_s: 12, rallies: [] });
    expect(localVideoMismatch(metadata, 1200)).toBeUndefined();
    expect(localVideoMismatch(metadata, 1200, 12.25)).toBeUndefined();
    expect(localVideoMismatch(metadata, 1200, 11.75)).toBeUndefined();
    expect(localVideoMismatch(metadata, 1201, 12)).toContain('文件大小');
    expect(localVideoMismatch(metadata, 1200, 12.251)).toContain('时长');
    expect(localVideoMismatch(metadata, 1200, 11.749)).toContain('时长');
    expect(localVideoMismatch(parseLocalMetadata({ rallies: [] }), 1200, 12)).toBeUndefined();
  });
  it('accepts compact metadata and preserves real score status', () => {
    const result = parseLocalMetadata({
      title: '比赛',
      rallies: [{ start_s: 1, end_s: 3, score: '2:1', score_status: 'inferred' }],
    });
    expect(result.title).toBe('比赛');
    expect(result.rallies[0]).toEqual({
      id: 'local-rally-1',
      start_s: 1,
      end_s: 3,
      score: '2:1',
      score_status: 'inferred',
    });
  });
  it('accepts an API video export and an analysis export', () => {
    const analysis = { rallies: [{ id: 'r1', start_s: 0, end_s: 2 }], warnings: ['提示'] };
    expect(
      parseLocalMetadata({ title: '原片', duration_s: 10, latest_analysis: analysis }),
    ).toMatchObject({ title: '原片', duration_s: 10, warnings: ['提示'], rallies: [{ id: 'r1' }] });
    expect(parseLocalMetadata(analysis).rallies[0].score_status).toBe('unknown');
    expect(parseLocalMetadata({ rallies: [] }).rallies).toEqual([]);
  });
  it.each([
    { start_s: -1, end_s: 2 },
    { start_s: 3, end_s: 2 },
    { start_s: 2, end_s: 2 },
    { start_s: NaN, end_s: 2 },
    { start_s: 0, end_s: Infinity },
    { start_s: '1', end_s: 2 },
  ])('rejects invalid times: %j', (rally) => {
    expect(() => parseLocalMetadata({ rallies: [rally] })).toThrow();
  });
  it('rejects overlapping or out-of-order intervals and duplicate ids', () => {
    expect(() =>
      parseLocalMetadata({
        rallies: [
          { start_s: 1, end_s: 3 },
          { start_s: 2, end_s: 4 },
        ],
      }),
    ).toThrow();
    expect(() =>
      parseLocalMetadata({
        rallies: [
          { id: 'r', start_s: 1, end_s: 2 },
          { id: 'r', start_s: 3, end_s: 4 },
        ],
      }),
    ).toThrow();
  });
  it('rejects times beyond declared duration and malformed structures', () => {
    for (const value of [
      null,
      [],
      {},
      { rallies: 'bad' },
      { duration_s: 0, rallies: [] },
      { duration_s: 1, rallies: [{ start_s: 0, end_s: 2 }] },
      { rallies: [{ start_s: 0, end_s: 1, score_status: 'invented' }] },
      { rallies: [{ start_s: 0, end_s: 1, score: [1, 2] }] },
    ]) {
      expect(() => parseLocalMetadata(value)).toThrow();
    }
  });
});
