import { test, expect } from '@playwright/test';

test('guest upload dialog dismisses outside, opens the picker and offers login when full', async ({
  page,
}) => {
  let used = 1;
  let username: string | null = null;
  const current = () => ({
    id: username ? 'user-id' : null,
    username,
    quota: { used, limit: username ? null : 5 },
  });
  await page.route('**/api/v1/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/session')) return route.fulfill({ status: 204 });
    if (path.endsWith('/account')) return route.fulfill({ json: current() });
    if (path.endsWith('/login')) {
      username = route.request().postDataJSON().username;
      return route.fulfill({ json: current() });
    }
    return route.fulfill({ json: { items: [] } });
  });
  await page.setViewportSize({ width: 320, height: 740 });
  await page.goto('/app');
  const upload = page.getByRole('button', { name: '选择视频', exact: true });
  const dialog = page.getByRole('dialog');
  await upload.press('Enter');
  await expect(dialog).toContainText('退出页面后');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(320);
  await page.mouse.click(8, 8);
  await expect(dialog).toBeHidden();
  await expect(upload).toBeFocused();
  await upload.click();
  const picker = page.waitForEvent('filechooser');
  await dialog.getByRole('button', { name: '继续上传' }).click();
  await picker;
  await expect(dialog).toBeHidden();
  await page.getByRole('button', { name: '历史', exact: true }).click();
  await expect(dialog).toContainText('存储空间 1/5');
  await dialog.getByRole('button', { name: '关闭历史视频' }).click();
  used = 5;
  await upload.click();
  await expect(dialog.getByRole('button', { name: '管理视频' })).toBeVisible();
  await expect(dialog.getByRole('button', { name: '继续上传' })).toHaveCount(0);
  await dialog.getByRole('button', { name: '现在登录' }).click();
  await dialog.getByLabel('用户名', { exact: true }).fill('viewer');
  const fields = dialog.locator('.form-field-control');
  await expect(fields).toHaveCount(2);
  const widths = await fields.evaluateAll((nodes) => nodes.map((node) => node.clientWidth));
  expect(widths[0]).toBe(widths[1]);
  const password = dialog.getByLabel('密码', { exact: true });
  await password.fill('test-password');
  await dialog.getByRole('button', { name: '显示密码' }).click();
  await expect(password).toHaveAttribute('type', 'text');
  await dialog.getByRole('button', { name: '隐藏密码' }).click();
  await expect(password).toHaveAttribute('type', 'password');
  await dialog.getByRole('button', { name: '登录', exact: true }).click();
  await expect(dialog).toBeHidden();
  await page.getByRole('button', { name: '账户 · viewer' }).click();
  await expect(dialog).toContainText('存储空间 5 个视频');
});
