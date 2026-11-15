import { expect, test } from 'vitest';
import { screenFor } from './routes';
test('routes isolate public, preview, management and old video links', () => {
  expect(screenFor('/')).toBe('home');
  expect(screenFor('/app')).toBe('app');
  expect(screenFor('/preview', '?clip=nina')).toBe('preview');
  expect(screenFor('/admin/users')).toBe('admin');
  expect(screenFor('/', '?video=existing')).toBe('app');
  expect(screenFor('/administrator')).toBe('missing');
});
