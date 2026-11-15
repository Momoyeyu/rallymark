export function screenFor(path: string, search = '') {
  if (path === '/app' || path.startsWith('/app/')) return 'app';
  if (path === '/preview' || path.startsWith('/preview/')) return 'preview';
  if (path === '/admin' || path.startsWith('/admin/')) return 'admin';
  if (path === '/' && new URLSearchParams(search).has('video')) return 'app';
  return path === '/' ? 'home' : 'missing';
}
