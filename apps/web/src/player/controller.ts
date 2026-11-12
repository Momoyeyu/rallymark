export type Interval = { id: string; start_s: number; end_s: number };
export type PlaybackCommand = { seekTo?: number; play?: boolean };

export function currentRally(rallies: Interval[], time: number): number {
  return rallies.findIndex((r) => time >= r.start_s && time < r.end_s);
}
export function navigationTarget(rallies: Interval[], time: number, direction: -1 | 1): number {
  const current = currentRally(rallies, time);
  if (current >= 0) {
    const target = current + direction;
    return target >= 0 && target < rallies.length ? target : -1;
  }
  if (direction === 1) return rallies.findIndex((r) => r.start_s > time);
  for (let i = rallies.length - 1; i >= 0; i--) if (rallies[i].start_s < time) return i;
  return -1;
}

export class PlaybackController {
  automatic = true;
  private armed: number | null = null;
  constructor(readonly rallies: Interval[]) {}

  play(time: number): PlaybackCommand {
    if (!this.automatic || !this.rallies.length) return { play: true };
    const active = currentRally(this.rallies, time);
    if (active >= 0) {
      this.armed = active;
      return { play: true };
    }
    const next = navigationTarget(this.rallies, time, 1);
    if (next < 0) return { play: false };
    return this.select(next);
  }
  select(index: number): PlaybackCommand {
    const rally = this.rallies[index];
    if (!rally) return {};
    this.armed = index;
    return { seekTo: rally.start_s, play: true };
  }
  navigate(time: number, direction: -1 | 1): PlaybackCommand {
    return this.select(navigationTarget(this.rallies, time, direction));
  }
  manualSeek(time: number, playing: boolean): PlaybackCommand {
    this.automatic = false;
    this.armed = null;
    return { seekTo: time, play: playing };
  }
  toggle(time: number): PlaybackCommand {
    this.automatic = !this.automatic;
    this.armed = null;
    if (this.automatic) {
      const active = currentRally(this.rallies, time);
      if (active >= 0) {
        this.armed = active;
        return {};
      }
      return this.play(time);
    }
    return {};
  }
  tick(time: number, paused: boolean): PlaybackCommand {
    if (!this.automatic || paused || this.armed === null) return {};
    const rally = this.rallies[this.armed];
    if (time < rally.end_s - 0.025) return {};
    const next = this.armed + 1;
    if (next < this.rallies.length) return this.select(next);
    this.armed = null;
    return { seekTo: rally.end_s, play: false };
  }
}
