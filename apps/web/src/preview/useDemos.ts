import { useEffect, useState } from 'react';
import type { Video } from '../api';
export type Demo = { video: Video; media: string; poster?: string };
export function useDemos(revision = 0) {
  const [items, setItems] = useState<Demo[]>([]);
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setError(false);
    void fetch('/demos/manifest.json', { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error('manifest');
        const manifest = (await response.json()) as { items: Demo[] };
        if (!manifest.items?.length) throw new Error('empty');
        setItems(manifest.items);
      })
      .catch((e) => {
        if (e.name !== 'AbortError') setError(true);
      });
    return () => controller.abort();
  }, [revision]);
  return { items, error };
}
