import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
let directory: string, media: Buffer;
test.beforeAll(() => {
  directory = mkdtempSync(join(tmpdir(), 'rallymark-video-'));
  const file = join(directory, 'clip.mp4');
  execFileSync('ffmpeg', [
    '-v',
    'error',
    '-f',
    'lavfi',
    '-i',
    'color=c=darkgreen:s=320x180:d=12:r=24',
    '-c:v',
    'libx264',
    '-pix_fmt',
    'yuv420p',
    '-movflags',
    '+faststart',
    file,
  ]);
  media = readFileSync(file);
});
test.afterAll(() => {
  if (directory && existsSync(directory)) rmSync(directory, { recursive: true });
});
test('a mobile user navigates original video and disables auto-skip by dragging', async ({
  page,
}) => {
  const analysis = {
    id: 'analysis',
    video_id: 'video',
    status: 'succeeded',
    progress: null,
    rallies: [
      { id: 'r1', start_s: 1, end_s: 2, score: '0:0', score_status: 'observed' },
      { id: 'r2', start_s: 5, end_s: 7, score: '1:0', score_status: 'inferred' },
    ],
    warnings: [],
    error: null,
    created_at: '2026-11-12T00:00:00Z',
    config_hash: 'hash',
    algorithm_version: 'fake',
  };
  const video = {
    id: 'video',
    title: '比赛.mp4',
    duration_s: 12,
    width: 320,
    height: 180,
    size_bytes: media.length,
    created_at: analysis.created_at,
    expires_at: '2026-11-19T00:00:00Z',
    latest_analysis: analysis,
  };
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/media')) {
      const range = route.request().headers()['range'];
      if (range) {
        const [startText, endText] = range.replace('bytes=', '').split('-');
        const start = Number(startText) || 0,
          end = endText ? Math.min(Number(endText), media.length - 1) : media.length - 1;
        await route.fulfill({
          status: 206,
          contentType: 'video/mp4',
          headers: {
            'accept-ranges': 'bytes',
            'content-range': `bytes ${start}-${end}/${media.length}`,
          },
          body: media.subarray(start, end + 1),
        });
      } else await route.fulfill({ contentType: 'video/mp4', body: media });
    } else if (path.endsWith('/session')) await route.fulfill({ status: 204 });
    else if (path.endsWith('/poster') || path.includes('/thumbnail'))
      await route.fulfill({ status: 204 });
    else if (path.endsWith('/events')) await route.fulfill({ status: 204 });
    else
      await route.fulfill({
        json: path.endsWith('/videos') ? { items: [video] } : video,
      });
  });
  await page.goto('/?video=video');
  await expect(page.getByRole('switch', { name: '自动跳转' })).toBeChecked();
  await page.getByRole('button', { name: '播放', exact: true }).click();
  await expect
    .poll(() => page.locator('video').evaluate((v) => (v as HTMLVideoElement).currentTime))
    .toBeGreaterThanOrEqual(1);
  await expect
    .poll(() => page.locator('video').evaluate((v) => (v as HTMLVideoElement).currentTime), {
      timeout: 7000,
    })
    .toBeGreaterThanOrEqual(5);
  await page.getByLabel('视频进度', { exact: true }).fill('3');
  await expect(page.getByRole('switch', { name: '自动跳转' })).not.toBeChecked();
  await expect(page.getByRole('button', { name: '下一回合' })).toBeEnabled();
  await page.getByRole('button', { name: '下一回合' }).click();
  await expect
    .poll(() => page.locator('video').evaluate((v) => (v as HTMLVideoElement).currentTime))
    .toBeGreaterThanOrEqual(5);
  await expect(page.getByRole('button', { name: '下一回合' })).toBeDisabled();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
  ).toBeTruthy();
  await page.getByRole('button', { name: '历史视频' }).click();
  await expect(page.getByRole('dialog', { name: '历史视频' })).toBeVisible();
});
