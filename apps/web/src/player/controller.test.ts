import { describe, expect, it } from 'vitest';
import { PlaybackController, navigationTarget } from './controller';

const rallies = [
  { id: '1', start_s: 1, end_s: 3 },
  { id: '2', start_s: 6, end_s: 8 },
];
describe('rally playback', () => {
  it('starts on a user play action, automatically advances and pauses at the last end', () => {
    const c = new PlaybackController(rallies);
    expect(c.play(0)).toEqual({ seekTo: 1, play: true });
    expect(c.tick(3, false)).toEqual({ seekTo: 6, play: true });
    expect(c.tick(8, false)).toEqual({ seekTo: 8, play: false });
    expect(c.tick(8, false)).toEqual({});
  });
  it('manual dragging disables automatic playback, navigation does not', () => {
    const c = new PlaybackController(rallies);
    c.play(0);
    expect(c.navigate(2, 1)).toEqual({ seekTo: 6, play: true });
    expect(c.automatic).toBe(true);
    expect(c.manualSeek(4, true)).toEqual({ seekTo: 4, play: true });
    expect(c.tick(5, false)).toEqual({});
    expect(c.automatic).toBe(false);
    expect(c.toggle(4)).toEqual({ seekTo: 6, play: true });
  });
  it('uses surrounding rallies in gaps and disables missing endpoints', () => {
    expect(navigationTarget(rallies, 4, -1)).toBe(0);
    expect(navigationTarget(rallies, 4, 1)).toBe(1);
    expect(navigationTarget(rallies, 2, -1)).toBe(-1);
    expect(navigationTarget(rallies, 7, 1)).toBe(-1);
  });
  it('pauses in a gap after the final rally when auto is re-enabled', () => {
    const c = new PlaybackController(rallies);
    c.manualSeek(10, true);
    expect(c.toggle(10)).toEqual({ play: false });
  });
  it('lets an unmarked video play continuously and does not advance while paused', () => {
    expect(new PlaybackController([]).play(0)).toEqual({ play: true });
    const c = new PlaybackController(rallies);
    c.play(1);
    expect(c.tick(3, true)).toEqual({});
  });
});
