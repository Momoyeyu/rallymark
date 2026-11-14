import { describe, expect, it } from 'vitest';
import { canPreload } from './useNextPreload';

describe('speculative video loading', () => {
  it('respects data saving, slow networks and constrained memory', () => {
    expect(canPreload({ connection: { saveData: true } })).toBe(false);
    expect(canPreload({ connection: { effectiveType: '2g' } })).toBe(false);
    expect(canPreload({ connection: { downlink: 1 } })).toBe(false);
    expect(canPreload({ deviceMemory: 2 })).toBe(false);
    expect(canPreload({})).toBe(true);
  });
});
