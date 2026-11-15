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
  for (const width of [320, 390, 768, 1440]) {
    await page.setViewportSize({ width, height: 844 });
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    ).toBeTruthy();
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
