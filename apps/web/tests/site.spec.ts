import { test, expect } from '@playwright/test';

test('homepage exposes upload and preview without an admin entry across mobile sizes', async ({
  page,
}) => {
  await page.route('**/demos/manifest.json', (route) => route.fulfill({ json: { items: [] } }));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '比赛很长，回看很快。' })).toBeVisible();
  await expect(page.getByRole('link', { name: '上传视频', exact: true })).toHaveAttribute(
    'href',
    '/app',
  );
  await expect(page.getByRole('link', { name: '体验预览', exact: true })).toHaveAttribute(
    'href',
    '/preview',
  );
  expect(await page.locator('a[href^="/admin"]').count()).toBe(0);
  for (const [width, height] of [
    [320, 740],
    [390, 844],
    [768, 1024],
    [1024, 768],
    [1440, 900],
    [1920, 1080],
    [2560, 1080],
  ]) {
    await page.setViewportSize({ width, height });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    ).toBeTruthy();
    for (const selector of [
      '.app-header',
      '.landing-hero',
      '.landing-showcase',
      '.landing-footer',
    ]) {
      const box = (await page.locator(selector).boundingBox())!;
      expect(Math.abs(box.x + box.width / 2 - width / 2)).toBeLessThanOrEqual(1);
    }
  }
  await page.getByRole('link', { name: '上传视频', exact: true }).click();
  await expect(page).toHaveURL(/\/app$/);
});

test('manager login, storage, custom user form and errors remain usable on mobile', async ({
  page,
}) => {
  let signedIn = false;
  const user = {
    id: 'admin-id',
    username: 'admin',
    role: 'admin',
    active: true,
    created_at: '2026-11-16T00:00:00Z',
  };
  await page.route('**/api/v1/admin/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/login')) {
      signedIn = true;
      return route.fulfill({ json: user });
    }
    if (!signedIn)
      return route.fulfill({ status: 401, json: { error: { message: '请登录管理面板。' } } });
    if (path.endsWith('/me')) return route.fulfill({ json: user });
    if (path.endsWith('/storage'))
      return route.fulfill({
        json: {
          disk_total_bytes: 16000000000000,
          disk_free_bytes: 15000000000000,
          disk_used_bytes: 1000000000000,
          video_count: 23,
          video_bytes: 4000000000,
          trashed_count: 0,
          expired_count: 0,
          retention_days: 7,
        },
      });
    if (path.endsWith('/users') && route.request().method() === 'POST')
      return route.fulfill({
        status: 409,
        json: { error: { message: '用户名已存在。', request_id: 'duplicate-test' } },
      });
    if (path.endsWith('/users')) return route.fulfill({ json: [user] });
    return route.fulfill({ status: 404 });
  });
  await page.goto('/admin');
  await page.getByLabel('用户名', { exact: true }).fill('admin');
  await page.getByLabel('密码', { exact: true }).fill('admin');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page.getByRole('heading', { name: '存储', exact: true })).toBeVisible();
  await page.getByRole('link', { name: '用户', exact: true }).click();
  await page.getByRole('button', { name: '新增用户', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('用户名', { exact: true }).fill('admin');
  await dialog.getByLabel('密码', { exact: true }).fill('password123');
  await dialog.getByRole('combobox', { name: '角色' }).click();
  await page.getByRole('option', { name: '管理员' }).click();
  await dialog.getByRole('button', { name: '保存', exact: true }).click();
  await expect(dialog.getByRole('alert')).toContainText('用户名已存在');
  await expect(dialog.getByRole('alert')).toContainText('duplicate-test');
  expect(
    await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
  ).toBeTruthy();
});

test('video batch selection shows ownership and recovers an emptied last page', async ({
  page,
}) => {
  const records = Array.from({ length: 21 }, (_, i) => ({
    id: `v${i}`,
    title: `clip-${i}`,
    duration_s: 10,
    width: 1920,
    height: 1080,
    size_bytes: 100,
    created_at: '2026-11-16T00:00:00Z',
    expires_at: '2026-11-23T00:00:00Z',
    latest_analysis: null,
    owner_label: i === 20 ? 'alice' : '访客 abc123',
    user_id: null,
    trashed_at: null as string | null,
  }));
  await page.route('**/api/v1/admin/**', (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/me'))
      return route.fulfill({
        json: { id: 'admin', username: 'admin', role: 'admin', active: true, created_at: '' },
      });
    if (url.pathname.endsWith('/storage')) return route.fulfill({ json: {} });
    if (url.pathname.endsWith('/videos/batch')) {
      const body = route.request().postDataJSON() as { ids: string[]; action: string };
      for (const r of records)
        if (body.ids.includes(r.id)) r.trashed_at = body.action === 'trash' ? 'now' : null;
      return route.fulfill({ status: 204 });
    }
    if (url.pathname.endsWith('/videos')) {
      const items = records.filter(
        (r) =>
          !!r.trashed_at === (url.searchParams.get('trashed') === 'true') &&
          r.title.includes(url.searchParams.get('q') || ''),
      );
      const p = Math.min(
        Number(url.searchParams.get('page') || 1),
        Math.max(1, Math.ceil(items.length / 20)),
      );
      return route.fulfill({
        json: { items: items.slice((p - 1) * 20, p * 20), total: items.length, page: p },
      });
    }
    return route.fulfill({ status: 404 });
  });
  await page.goto('/admin/videos');
  await page.getByRole('checkbox', { name: '选择本页', exact: true }).click();
  await expect(page.getByText('已选 20 项')).toBeVisible();
  await page.getByRole('button', { name: '下一页', exact: true }).click();
  await expect(page.getByText('alice', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '批量回收' })).toBeDisabled();
  await page.getByRole('checkbox', { name: '选择本页', exact: true }).click();
  await page.getByRole('button', { name: '批量回收' }).click();
  await page.getByRole('dialog').getByRole('button', { name: '移入回收站', exact: true }).click();
  await expect(page.getByText('1 / 1', { exact: true })).toBeVisible();
  await expect(page.getByRole('checkbox', { name: '选择clip-0', exact: true })).toBeVisible();
  await page.getByRole('checkbox', { name: '选择本页', exact: true }).click();
  await page.getByRole('checkbox', { name: '选择clip-0', exact: true }).click();
  await expect(page.getByRole('checkbox', { name: '选择本页', exact: true })).toHaveAttribute(
    'aria-checked',
    'mixed',
  );
  await page.getByLabel('搜索视频', { exact: true }).fill('clip-1');
  await expect(page.getByRole('button', { name: '批量回收' })).toBeDisabled();
  await page.getByRole('link', { name: '回收站', exact: true }).click();
  await page.getByRole('checkbox', { name: '选择本页', exact: true }).click();
  await page.getByRole('button', { name: '批量恢复' }).click();
  await expect(page.getByText('回收站为空')).toBeVisible();
  await expect(page.getByText('1 / 1', { exact: true })).toBeVisible();
  for (const width of [320, 390, 1440]) {
    await page.setViewportSize({ width, height: 844 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    ).toBeTruthy();
  }
});
