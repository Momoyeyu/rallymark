import { createReadStream, readFileSync, statSync } from 'node:fs';
import { resolve } from 'node:path';
import type { Plugin } from 'vite';

export function previewData(): Plugin {
  return {
    name: 'local-review-data',
    apply: 'serve',
    configureServer(server) {
      const configured = process.env.RALLYMARK_PREVIEW_DATA;
      if (!configured) return;
      if (server.config.server.host !== '127.0.0.1')
        throw new Error('Local preview data requires --host 127.0.0.1');
      const root = resolve(configured);
      const manifest = JSON.parse(readFileSync(resolve(root, 'review/manifest.json'), 'utf8'));
      const clips = manifest.videos.map((item: { id: string; metadata: string }) => {
        if (!/^[a-z0-9_-]+$/.test(item.id) || item.metadata !== `${item.id}.json`)
          throw new Error('Invalid preview manifest');
        const metadata = JSON.parse(readFileSync(resolve(root, 'review', item.metadata), 'utf8'));
        const file = resolve(root, 'videos', `${item.id}.mp4`);
        if (statSync(file).size !== metadata.source_size_bytes)
          throw new Error(`Preview video mismatch: ${item.id}`);
        return {
          id: item.id,
          name: `${item.id}.mp4`,
          size: metadata.source_size_bytes,
          url: `/__local-preview/video/${item.id}`,
          metadata,
        };
      });
      server.middlewares.use((req, res, next) => {
        const path = new URL(req.url || '/', 'http://localhost').pathname;
        if (!path.startsWith('/__local-preview/')) return next();
        if (req.method !== 'GET' && req.method !== 'HEAD') {
          res.writeHead(405).end();
          return;
        }
        res.setHeader('Cache-Control', 'no-store');
        if (path === '/__local-preview/manifest') {
          res.setHeader('Content-Type', 'application/json');
          res.end(req.method === 'HEAD' ? undefined : JSON.stringify({ clips }));
          return;
        }
        const clip = clips.find((item: { url: string }) => item.url === path);
        if (!clip) {
          res.writeHead(404).end();
          return;
        }
        const file = resolve(root, 'videos', clip.name);
        let start = 0,
          end = clip.size - 1;
        if (req.headers.range) {
          const range = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range);
          if (!range || (!range[1] && !range[2])) {
            res.writeHead(416).end();
            return;
          }
          if (range[1]) {
            start = Number(range[1]);
            if (range[2]) end = Math.min(end, Number(range[2]));
          } else start = Math.max(0, clip.size - Number(range[2]));
          if (!Number.isSafeInteger(start) || start > end || start >= clip.size) {
            res.writeHead(416, { 'Content-Range': `bytes */${clip.size}` }).end();
            return;
          }
          res.statusCode = 206;
          res.setHeader('Content-Range', `bytes ${start}-${end}/${clip.size}`);
        }
        res.setHeader('Content-Type', 'video/mp4');
        res.setHeader('Accept-Ranges', 'bytes');
        res.setHeader('Content-Length', end - start + 1);
        if (req.method === 'HEAD') res.end();
        else
          createReadStream(file, { start, end })
            .on('error', () => res.destroy())
            .pipe(res);
      });
    },
  };
}
