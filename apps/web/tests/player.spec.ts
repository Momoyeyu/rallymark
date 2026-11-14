import { test, expect, type Route } from '@playwright/test';
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
async function respondMedia(route: Route) {
  const requested = route.request().headers()['range'];
  if (!requested) return route.fulfill({ contentType: 'video/mp4', body: media });
  const [left, right] = requested.replace('bytes=', '').split('-');
  const start = Number(left) || 0,
    end = right ? Math.min(Number(right), media.length - 1) : media.length - 1;
  return route.fulfill({
    status: 206,
    contentType: 'video/mp4',
    headers: { 'accept-ranges': 'bytes', 'content-range': `bytes ${start}-${end}/${media.length}` },
    body: media.subarray(start, end + 1),
  });
}

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
    if (path.endsWith('/media')) return respondMedia(route);
    if (path.endsWith('/session')) await route.fulfill({ status: 204 });
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

test('local review uses six independent originals and metadata without API requests', async ({
  page,
}, testInfo) => {
  const apiRequests: string[] = [];
  await page.route('**/api/**', (route) => {
    apiRequests.push(route.request().url());
    return route.abort();
  });
  await page.goto('/?local=1');
  await page.getByLabel('原视频（可多选）', { exact: true }).setInputFiles(
    Array.from({ length: 6 }, (_, i) => ({
      name: `match-${i + 1}.mp4`,
      mimeType: 'video/mp4',
      buffer: media,
    })),
  );
  const select = page.getByRole('combobox', { name: '当前视频', exact: true });
  await page.getByRole('button', { name: '关闭本地文件', exact: true }).click();
  await select.click();
  await expect(page.getByRole('option')).toHaveCount(6);
  await page.keyboard.press('Escape');
  const options = [0, 1, 2, 3, 4, 5];
  async function choose(index: number) {
    await select.click();
    await page.getByRole('option').nth(index).click();
  }
  for (let i = 0; i < options.length; i++) {
    await choose(options[i]);
    await page.getByLabel('此视频的分析 JSON', { exact: true }).setInputFiles({
      name: `match-${i + 1}.json`,
      mimeType: 'application/json',
      buffer: Buffer.from(
        JSON.stringify({
          rallies: [
            { start_s: 1, end_s: 2, score: `${i}:0`, score_status: 'observed' },
            { start_s: 5, end_s: 7, score: `${i + 1}:0`, score_status: 'inferred' },
          ],
        }),
      ),
    });
    await expect(
      page.getByRole('button', { name: `跳转回合 1 比分 ${i}:0`, exact: true }),
    ).toBeVisible();
    await expect(page.getByRole('button', { name: '本地文件设置', exact: true })).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    await expect(page.getByLabel('原视频（可多选）', { exact: true })).toBeHidden();
    await expect(select).toBeVisible();
  }
  await choose(options[0]);
  await expect(
    page.getByRole('button', { name: '跳转回合 1 比分 0:0', exact: true }),
  ).toBeVisible();
  await expect
    .poll(() => page.locator('video').evaluate((v) => (v as HTMLVideoElement).readyState))
    .toBeGreaterThanOrEqual(2);
  const progressBounds = await page.getByLabel('视频进度', { exact: true }).boundingBox();
  expect(progressBounds!.y + progressBounds!.height).toBeLessThan(844);
  await page.screenshot({ path: testInfo.outputPath('local-review-compact.png') });
  await page.getByRole('button', { name: '播放', exact: true }).click();
  await expect
    .poll(() => page.locator('video').evaluate((v) => (v as HTMLVideoElement).currentTime), {
      timeout: 7000,
    })
    .toBeGreaterThanOrEqual(5);
  await page.getByLabel('视频进度', { exact: true }).fill('3');
  await expect(page.getByRole('switch', { name: '自动跳转' })).not.toBeChecked();
  await page.getByRole('button', { name: '下一回合' }).click();
  await expect
    .poll(() => page.locator('video').evaluate((v) => (v as HTMLVideoElement).currentTime))
    .toBeGreaterThanOrEqual(5);
  await page.getByRole('button', { name: '上一回合' }).click();
  await expect
    .poll(() => page.locator('video').evaluate((v) => (v as HTMLVideoElement).currentTime))
    .toBeLessThan(3);
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
  ).toBeTruthy();
  await page.getByRole('button', { name: '本地文件设置', exact: true }).click();
  await expect(page.getByRole('button', { name: /分析数据/ })).toBeVisible();
  await expect(page.getByLabel('此视频的分析 JSON', { exact: true })).toBeHidden();
  await page.getByLabel('此视频的分析 JSON', { exact: true }).setInputFiles({
    name: 'invalid.json',
    mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify({ rallies: [{ start_s: -1, end_s: 2 }] })),
  });
  await expect(page.getByRole('alert')).toContainText('时间无效');
  await expect(page.locator('video')).toHaveCount(0);
  await page.getByLabel('此视频的分析 JSON', { exact: true }).setInputFiles({
    name: 'wrong-video.json',
    mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify({ rallies: [{ start_s: 15, end_s: 20 }] })),
  });
  await expect(page.getByRole('alert')).toContainText('超过原视频时长');
  await expect(page.locator('video')).toHaveCount(0);
  await page.getByRole('button', { name: '本地文件设置', exact: true }).click();
  await page.getByLabel('此视频的分析 JSON', { exact: true }).setInputFiles({
    name: 'wrong-size.json',
    mimeType: 'application/json',
    buffer: Buffer.from(
      JSON.stringify({ source_size_bytes: media.length + 1, rallies: [{ start_s: 1, end_s: 2 }] }),
    ),
  });
  await expect(page.getByRole('alert')).toContainText('文件大小');
  await expect(page.locator('video')).toHaveCount(0);
  await page.getByRole('button', { name: '本地文件设置', exact: true }).click();
  await page.getByLabel('此视频的分析 JSON', { exact: true }).setInputFiles({
    name: 'wrong-duration.json',
    mimeType: 'application/json',
    buffer: Buffer.from(
      JSON.stringify({
        duration_s: 13,
        source_size_bytes: media.length,
        rallies: [{ start_s: 1, end_s: 2 }],
      }),
    ),
  });
  await expect(page.getByRole('alert')).toContainText('时长与分析 JSON 不一致');
  await expect(page.locator('video')).toHaveCount(0);
  expect(apiRequests).toEqual([]);
});

async function preloaded(page: import('@playwright/test').Page, count = 12) {
  await page.route('**/preview-clip.mp4', respondMedia);
  await page.route('**/__local-preview/manifest', (route) =>
    route.fulfill({
      json: {
        clips: Array.from({ length: count }, (_, i) => ({
          id: `clip-${i}`,
          name: `match-${i}.mp4`,
          size: media.length,
          url: '/preview-clip.mp4',
          metadata: {
            title:
              i === 0
                ? 'Alpha ' + '超长比赛标题'.repeat(30)
                : i === count - 1
                  ? 'Beta final'
                  : `Match ${i}`,
            duration_s: 12,
            source_size_bytes: media.length,
            warnings: [],
            rallies: Array.from({ length: 7 }, (_, r) => ({
              id: `r${r}`,
              start_s: 0.5 + r * 1.2,
              end_s: 0.9 + r * 1.2,
              score: r === 2 ? null : `${r}:0`,
              score_status: r === 2 ? 'unknown' : 'observed',
            })),
          },
        })),
      },
    }),
  );
  await page.goto('/?local=1&preview=1');
  await expect(page.getByRole('combobox', { name: '当前视频', exact: true })).toBeVisible();
}

test('custom picker keeps its bounds, keyboard selection and modal focus', async ({ page }) => {
  await preloaded(page);
  const picker = page.getByRole('combobox', { name: '当前视频', exact: true });
  for (const width of [320, 390, 1024, 1920]) {
    await page.setViewportSize({ width, height: 844 });
    await picker.click();
    await expect(page.getByRole('option')).toHaveCount(12);
    const bounds = await page.getByRole('listbox').boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(10);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width - 10);
    expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(834);
    const trigger = await picker.boundingBox(),
      gear = await page.getByRole('button', { name: '本地文件设置', exact: true }).boundingBox();
    expect(Math.abs(trigger!.y - gear!.y)).toBeLessThan(1);
    expect(trigger!.height).toBe(gear!.height);
    await page.keyboard.press('Escape');
    await expect(picker).toBeFocused();
    const layout = await page.evaluate(() => {
      const box = (selector: string) => document.querySelector(selector)!.getBoundingClientRect();
      const video = box('.video-stage'),
        panel = box('.playback-panel'),
        grid = box('.rally-grid');
      return {
        top: Math.abs(video.top - panel.top),
        bottom: Math.abs(video.bottom - panel.bottom),
        cards: [...document.querySelectorAll('.rally-card')].every((card) => {
          const b = card.getBoundingClientRect();
          return b.left >= grid.left - 1 && b.right <= grid.right + 1;
        }),
      };
    });
    if (width >= 960) {
      expect(layout.top).toBeLessThan(1);
      expect(layout.bottom).toBeLessThan(1);
    }
    expect(layout.cards).toBeTruthy();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    ).toBeTruthy();
    expect(
      await page.evaluate(() =>
        [...document.querySelectorAll('button:not([disabled])')]
          .filter((node) => node.getClientRects().length)
          .every((node) => {
            const box = node.getBoundingClientRect();
            return box.width >= 44 && box.height >= 44;
          }),
      ),
    ).toBeTruthy();
  }
  await page.setViewportSize({ width: 390, height: 320 });
  await picker.focus();
  await page.keyboard.press('ArrowDown');
  await expect(page.getByRole('option').first()).toBeFocused();
  await page.keyboard.press('End');
  await expect(page.getByRole('option').last()).toBeFocused();
  const short = await page.getByRole('listbox').boundingBox();
  expect(short!.y).toBeGreaterThanOrEqual(10);
  expect(short!.y + short!.height).toBeLessThanOrEqual(310);
  await page.keyboard.press('Escape');
  await expect(picker).toContainText('Alpha');
  await page.setViewportSize({ width: 390, height: 844 });
  await picker.press('b');
  await expect(picker).toContainText('Beta final');
  await expect(page).toHaveURL(/clip=clip-11/);
  await picker.click();
  await page.getByRole('heading', { level: 1 }).click();
  await expect(page.getByRole('listbox')).toHaveCount(0);
  const gear = page.getByRole('button', { name: '本地文件设置', exact: true });
  await gear.click();
  const dialog = page.getByRole('dialog', { name: '本地文件', exact: true });
  await expect(dialog).toBeVisible();
  for (let i = 0; i < 6; i++) {
    await page.keyboard.press('Tab');
    expect(await dialog.evaluate((node) => node.contains(document.activeElement))).toBeTruthy();
  }
  await expect(
    page.locator('input[type=file]:visible,select:visible,progress:visible'),
  ).toHaveCount(0);
  for (let i = 0; i < 6; i++) {
    await page.keyboard.press('Shift+Tab');
    expect(await dialog.evaluate((node) => node.contains(document.activeElement))).toBeTruthy();
  }
  await page.getByRole('button', { name: '移除此视频', exact: true }).click();
  await expect(page.getByRole('button', { name: '保留', exact: true })).toBeFocused();
  await page.getByRole('button', { name: '保留', exact: true }).click();
  await expect(page.getByRole('button', { name: '移除此视频', exact: true })).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(gear).toBeFocused();
  await picker.click();
  await expect(page.getByRole('option')).toHaveCount(12);
  await page.keyboard.press('Escape');
});

test('round pages remain complete and the custom timeline supports keyboard seeking', async ({
  page,
}) => {
  await preloaded(page, 1);
  const cards = page.locator('.rally-card');
  await expect(cards).toHaveCount(3);
  const firstWidth = (await cards.first().boundingBox())!.width;
  await page.getByRole('button', { name: '下一页回合', exact: true }).click();
  await expect(cards).toHaveCount(3);
  await page.getByRole('button', { name: '下一页回合', exact: true }).click();
  await expect(cards).toHaveCount(1);
  expect(Math.abs((await cards.first().boundingBox())!.width - firstWidth)).toBeLessThan(1);
  await expect(page.getByRole('button', { name: '下一页回合', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: '跳转回合 7 比分 6:0', exact: true }).click();
  await expect
    .poll(() => page.locator('video').evaluate((v) => (v as HTMLVideoElement).currentTime))
    .toBeGreaterThanOrEqual(7.7);
  const range = page.getByLabel('视频进度', { exact: true });
  await range.fill('3');
  await expect(range).toHaveValue('3');
  await range.press('ArrowRight');
  await expect(range).toHaveValue('8');
  await expect(page.getByRole('switch', { name: '自动跳转' })).not.toBeChecked();
  await range.press('Home');
  await expect(range).toHaveValue('0');
  await range.press('End');
  await expect(range).toHaveValue('12');
  await page.setViewportSize({ width: 844, height: 390 });
  await page.getByRole('button', { name: '全屏', exact: true }).click();
  await expect.poll(() => page.evaluate(() => !!document.fullscreenElement)).toBeTruthy();
  await expect(page.getByRole('button', { name: '退出全屏', exact: true })).toBeVisible();
  const fullscreen = await page.locator('.player').boundingBox();
  expect(fullscreen!.width).toBe(844);
  expect(fullscreen!.height).toBe(390);
  expect(
    await page.locator('.player').evaluate((node) => node.scrollHeight <= node.clientHeight + 1),
  ).toBeTruthy();
  await page.getByRole('button', { name: '退出全屏', exact: true }).click();

  expect(await page.locator('video').evaluate((v) => (v as HTMLVideoElement).paused)).toBeTruthy();
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
  ).toBeTruthy();
});

test('product empty, running, failed and disconnected states share accessible controls', async ({
  page,
}) => {
  let state = 'welcome';
  let releaseUpload = () => {};
  const uploadGate = new Promise<void>((resolve) => {
    releaseUpload = resolve;
  });
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (state === 'disconnected')
      return route.fulfill({
        status: 503,
        json: { error: { message: '连接失败，请重试', request_id: 'test-request' } },
      });
    if (
      path.endsWith('/session') ||
      path.endsWith('/events') ||
      path.endsWith('/poster') ||
      path.includes('/thumbnail')
    )
      return route.fulfill({ status: 204 });
    if (path.endsWith('/media')) return respondMedia(route);
    if (path.endsWith('/videos') && route.request().method() === 'POST') {
      await uploadGate;
      state = 'queued';
    }
    const item = {
      id: 'demo',
      title: '比赛 ' + '超长标题'.repeat(50),
      duration_s: 12,
      width: 320,
      height: 180,
      size_bytes: media.length,
      created_at: '2026-11-13T00:00:00Z',
      expires_at: '2026-11-20T00:00:00Z',
      latest_analysis: {
        id: 'analysis',
        video_id: 'demo',
        status: state,
        rallies: [],
        warnings: [],
        progress: null,
        error: { message: '分析中断，请重试' },
        created_at: '2026-11-13T00:00:00Z',
        config_hash: 'hash',
        algorithm_version: 'test',
      },
    };
    return route.fulfill({
      json:
        path.endsWith('/videos') && route.request().method() !== 'POST'
          ? { items: state === 'welcome' ? [] : [item] }
          : item,
    });
  });
  await page.goto('/');
  await expect(page.getByRole('button', { name: '选择视频', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '历史视频', exact: true }).click();
  await expect(page.getByRole('dialog', { name: '历史视频' })).toContainText('还没有视频');
  await page.keyboard.press('Escape');
  await page
    .locator('input[type=file]')
    .setInputFiles({ name: 'sample.mp4', mimeType: 'video/mp4', buffer: media });
  try {
    await expect(page.getByRole('progressbar', { name: '上传进度' })).toBeVisible();
  } finally {
    releaseUpload();
  }
  await expect(page.getByRole('heading', { name: '等待分析', exact: true })).toBeVisible();
  await expect(page.getByRole('progressbar', { name: '分析进行中' })).toBeVisible();
  state = 'failed';
  await page.reload();
  await expect(page.getByRole('button', { name: '重试', exact: true })).toBeEnabled();
  state = 'succeeded';
  await page.reload();
  await expect(page.getByText('暂无回合，可自由播放')).toBeVisible();
  await expect(page.getByRole('button', { name: '下一回合', exact: true })).toBeDisabled();
  await expect(
    page.locator('select:visible,progress:visible,input[type=file]:visible'),
  ).toHaveCount(0);
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
  ).toBeTruthy();
  state = 'disconnected';
  await page.reload();
  await expect(page.getByRole('alert')).toContainText('连接失败，请重试');
  await expect(page.getByRole('button', { name: '重新连接' })).toBeEnabled();
});

test('touch review uses custom controls and file actions without exposing native widgets', async ({
  browser,
}) => {
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    isMobile: true,
    hasTouch: true,
    reducedMotion: 'reduce',
  });
  const page = await context.newPage();
  try {
    await preloaded(page, 1);
    await page.getByRole('button', { name: '播放', exact: true }).tap();
    await expect
      .poll(() => page.locator('video').evaluate((v) => (v as HTMLVideoElement).currentTime))
      .toBeGreaterThanOrEqual(0.5);
    const track = await page.getByLabel('视频进度', { exact: true }).boundingBox();
    await page.touchscreen.tap(track!.x + track!.width / 2, track!.y + track!.height / 2);
    await expect(page.getByRole('switch', { name: '自动跳转' })).not.toBeChecked();
    await page.getByRole('button', { name: '本地文件设置', exact: true }).tap();
    const chooser = page.waitForEvent('filechooser');
    await page.getByRole('button', { name: /分析数据/ }).tap();
    await (
      await chooser
    ).setFiles({
      name: 'touch.json',
      mimeType: 'application/json',
      buffer: Buffer.from(
        JSON.stringify({
          duration_s: 12,
          source_size_bytes: media.length,
          rallies: [{ start_s: 1, end_s: 2, score: '9:9', score_status: 'observed' }],
        }),
      ),
    });
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(
      page.getByRole('button', { name: '跳转回合 1 比分 9:9', exact: true }),
    ).toBeVisible();
    await expect(
      page.locator('select:visible,input[type=file]:visible,progress:visible'),
    ).toHaveCount(0);
    expect(
      await page.locator('.switch i').evaluate((node) => getComputedStyle(node).transitionDuration),
    ).toBe('0s');
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    ).toBeTruthy();
  } finally {
    await context.close();
  }
});

test('unavailable analysis stops before video transfer and keeps a public request ID', async ({
  page,
}) => {
  let uploads = 0;
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/session') || path.endsWith('/events'))
      return route.fulfill({ status: 204 });
    if (path.endsWith('/availability'))
      return route.fulfill({
        status: 503,
        json: {
          error: {
            code: 'analysis_unavailable',
            message: '分析服务暂不可用，请稍后重试。',
            request_id: 'capacity-test',
          },
        },
      });
    if (route.request().method() === 'POST') uploads++;
    return route.fulfill({ json: { items: [] } });
  });
  await page.goto('/');
  await expect(page.getByRole('button', { name: '选择视频', exact: true })).toBeEnabled();
  await page
    .locator('input[type=file]')
    .setInputFiles({ name: 'match.mp4', mimeType: 'video/mp4', buffer: media });
  await expect(page.getByRole('alert')).toContainText('分析服务暂不可用');
  await expect(page.getByRole('alert')).toContainText('capacity-test');
  expect(uploads).toBe(0);
});

test('static preview offers six matches with the shared mobile player and no upload or API', async ({
  page,
}) => {
  let apiRequests = 0;
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.startsWith('/api/')) apiRequests++;
  });
  await page.route('**/demos/*.mp4', respondMedia);
  await page.route('**/demos/manifest.json', (route) =>
    route.fulfill({
      json: {
        items: Array.from({ length: 6 }, (_, i) => ({
          media: `/demos/match-${i}.mp4`,
          video: {
            id: `match-${i}`,
            title: `比赛 ${i + 1}`,
            duration_s: 12,
            width: 320,
            height: 180,
            size_bytes: media.length,
            created_at: '',
            expires_at: '',
            latest_analysis: {
              id: `result-${i}`,
              video_id: `match-${i}`,
              status: 'succeeded',
              progress: null,
              rallies: [
                { id: 'one', start_s: 1, end_s: 2, score: '0:0', score_status: 'observed' },
                { id: 'two', start_s: 5, end_s: 7, score: '1:0', score_status: 'inferred' },
              ],
              warnings: [],
              error: null,
              created_at: '',
              config_hash: '',
              algorithm_version: 'test',
            },
          },
        })),
      },
    }),
  );
  await page.goto('http://127.0.0.1:4188/');
  await expect(page.getByRole('button', { name: '播放', exact: true })).toBeVisible();
  expect(await page.locator('input[type=file]').count()).toBe(0);
  expect(await page.getByRole('button', { name: /上传|选择文件|本地文件/ }).count()).toBe(0);
  for (let i = 0; i < 6; i++) {
    await page.getByRole('combobox', { name: '当前视频' }).click();
    await page.getByRole('option').nth(i).click();
    await expect(page.locator('video')).toHaveAttribute('src', `/demos/match-${i}.mp4`);
    await expect
      .poll(() => page.locator('video').evaluate((video) => (video as HTMLVideoElement).readyState))
      .toBeGreaterThanOrEqual(1);
  }
  await page.getByRole('button', { name: '下一回合', exact: true }).click();
  await expect
    .poll(() => page.locator('video').evaluate((video) => !(video as HTMLVideoElement).paused))
    .toBeTruthy();
  for (const width of [320, 390, 844, 1920]) {
    await page.setViewportSize({ width, height: 844 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    ).toBeTruthy();
  }
  expect(apiRequests).toBe(0);
});
