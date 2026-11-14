import { useEffect, useRef, type RefObject } from 'react';

type Device = {
  deviceMemory?: number;
  connection?: { saveData?: boolean; effectiveType?: string; downlink?: number };
};
export function canPreload(device: Device) {
  const network = device.connection;
  return !(
    network?.saveData ||
    /(^|-)2g$/.test(network?.effectiveType ?? '') ||
    (network?.downlink !== undefined && network.downlink < 2) ||
    (device.deviceMemory !== undefined && device.deviceMemory <= 2)
  );
}

type Outcome = { outcome: string; elapsed_ms: number; target_s: number };
export function useNextPreload(
  media: RefObject<HTMLVideoElement | null>,
  source: string,
  target: number | undefined,
  enabled: boolean,
  report: (event: Outcome) => void,
) {
  const callback = useRef(report);
  callback.current = report;
  const warmed = useRef(new Set<number>());
  useEffect(() => warmed.current.clear(), [source]);
  useEffect(() => {
    const current = media.current;
    if (
      !enabled ||
      !current ||
      target === undefined ||
      source.startsWith('blob:') ||
      !canPreload(navigator as Navigator & Device) ||
      warmed.current.has(target)
    )
      return;
    let next: HTMLVideoElement | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let started = 0,
      closed = false;
    const end = (outcome: string) => {
      if (closed) return;
      closed = true;
      clearTimeout(timer);
      if (next) {
        next.onloadedmetadata = next.onseeked = next.onerror = null;
        next.removeAttribute('src');
        next.load();
        callback.current({
          outcome,
          target_s: target,
          elapsed_ms: Math.round(performance.now() - started),
        });
      }
    };
    const start = () => {
      if (closed || next || document.hidden || current.seeking) return;
      let safe = false;
      for (let i = 0; i < current.buffered.length; i++) {
        const left = current.buffered.start(i),
          right = current.buffered.end(i);
        if (left <= target && right >= target + 1) {
          warmed.current.add(target);
          return;
        }
        if (left <= current.currentTime && right >= current.currentTime + 2) safe = true;
      }
      if (!safe) return;
      started = performance.now();
      next = document.createElement('video');
      next.muted = true;
      next.playsInline = true;
      next.preload = 'metadata';
      next.onloadedmetadata = () => {
        if (next && !closed) next.currentTime = target;
      };
      next.onseeked = () => {
        warmed.current.add(target);
        end('ready');
      };
      next.onerror = () => end('error');
      timer = setTimeout(() => end('timeout'), 6000);
      next.src = source;
    };
    const cancel = () => end('cancelled');
    const visibility = () => (document.hidden ? cancel() : start());
    current.addEventListener('progress', start);
    current.addEventListener('timeupdate', start);
    current.addEventListener('seeking', cancel);
    document.addEventListener('visibilitychange', visibility);
    start();
    return () => {
      current.removeEventListener('progress', start);
      current.removeEventListener('timeupdate', start);
      current.removeEventListener('seeking', cancel);
      document.removeEventListener('visibilitychange', visibility);
      cancel();
    };
  }, [media, source, target, enabled]);
}
