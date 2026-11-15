import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
let dir: string, mp4: Buffer, mov: Buffer, hevc: Buffer, fragmented: Buffer;
const policy = {
  max_upload_bytes: 500000000,
  max_duration_seconds: 900,
  max_pixels: 8847360,
  formats: ['mp4', 'mov'],
  video_codecs: ['avc', 'hevc'],
  audio_codecs: ['aac', 'pcm-s16', 'pcm-s24', 'pcm-s32', 'pcm-f32'],
};
test.beforeAll(() => {
  dir = mkdtempSync(join(tmpdir(), 'rallymark-upload-'));
  for (const [name, codec] of [
    ['clip.mp4', 'libx264'],
    ['clip.mov', 'libx264'],
    ['hevc.mov', 'libx265'],
  ]) {
    execFileSync(
      'ffmpeg',
      [
        '-v',
        'error',
        '-f',
        'lavfi',
        '-i',
        'testsrc2=s=320x180:r=24:d=1',
        '-c:v',
        codec,
        '-threads',
        '1',
        '-pix_fmt',
        'yuv420p',
        join(dir, name),
      ],
      { stdio: 'pipe' },
    );
  }
  execFileSync(
    'ffmpeg',
    [
      '-v',
      'error',
      '-i',
      join(dir, 'clip.mp4'),
      '-c',
      'copy',
      '-movflags',
      'frag_keyframe+empty_moov',
      join(dir, 'fragmented.mp4'),
    ],
    { stdio: 'pipe' },
  );
  fragmented = readFileSync(join(dir, 'fragmented.mp4'));
  mp4 = readFileSync(join(dir, 'clip.mp4'));
  mov = readFileSync(join(dir, 'clip.mov'));
  hevc = readFileSync(join(dir, 'hevc.mov'));
});
test.afterAll(() => rmSync(dir, { recursive: true, force: true }));

test('invalid content, oversized and overlong videos never send a video upload', async ({
  page,
}) => {
  let limits = policy,
    uploads = 0;
  await page.route('**/api/v1/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/session') || path.endsWith('/events'))
      return route.fulfill({ status: 204 });
    if (path.endsWith('/upload-policy')) return route.fulfill({ json: limits });
    if (path.endsWith('/videos') && route.request().method() === 'POST') uploads++;
    return route.fulfill({ json: { items: [] } });
  });
  await page.goto('/');
  await expect(page.getByRole('button', { name: '选择视频', exact: true })).toBeEnabled();
  await page
    .locator('input[type=file]')
    .setInputFiles({ name: 'bad.mp4', mimeType: 'video/mp4', buffer: Buffer.from('broken') });
  await expect(page.getByRole('alert')).toContainText('无法读取视频');
  limits = { ...policy, max_upload_bytes: 4 };
  await page
    .locator('input[type=file]')
    .setInputFiles({ name: 'large.MOV', mimeType: 'video/quicktime', buffer: mov });
  await expect(page.getByRole('alert')).toContainText('视频须小于');
  limits = { ...policy, max_duration_seconds: 0.5 };
  await page
    .locator('input[type=file]')
    .setInputFiles({ name: 'long.mp4', mimeType: 'video/mp4', buffer: mp4 });
  await expect(page.getByRole('alert')).toContainText('视频时长');
  expect(uploads).toBe(0);
});

for (const kind of ['mov', 'hevc', 'no-extension', 'fragmented']) {
  test(`accepts ${kind} metadata without decoding or relying on filename`, async ({ page }) => {
    let uploads = 0;
    const result = {
      id: 'sample',
      title: '15_raw',
      duration_s: 1,
      width: 320,
      height: 180,
      size_bytes: 10000,
      created_at: '',
      expires_at: '',
      latest_analysis: {
        id: 'analysis',
        video_id: 'sample',
        status: 'preparing',
        progress: null,
        rallies: [],
        warnings: [],
        error: null,
        created_at: '',
        config_hash: '',
        algorithm_version: 'test',
      },
    };
    await page.route('**/api/v1/**', (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith('/session') || path.endsWith('/events'))
        return route.fulfill({ status: 204 });
      if (path.endsWith('/upload-policy')) return route.fulfill({ json: policy });
      if (path.endsWith('/availability'))
        return route.fulfill({ json: { state: 'ready', queued: 0 } });
      if (path.endsWith('/videos') && route.request().method() === 'POST') {
        uploads++;
        return route.fulfill({ status: 201, json: result });
      }
      return route.fulfill({ json: path.endsWith('/videos') ? { items: [] } : result });
    });
    await page.goto('/');
    await expect(page.getByRole('button', { name: '选择视频', exact: true })).toBeEnabled();
    await page.locator('input[type=file]').setInputFiles({
      name: kind === 'no-extension' ? '15_raw' : '15_raw.MOV',
      mimeType: kind === 'no-extension' ? '' : 'video/quicktime',
      buffer:
        kind === 'hevc' ? hevc : kind === 'mov' ? mov : kind === 'fragmented' ? fragmented : mp4,
    });
    await expect(page.getByRole('heading', { name: '准备视频', exact: true })).toBeVisible();
    expect(uploads).toBe(1);
  });
}
