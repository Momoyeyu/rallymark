import React, { lazy, Suspense } from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { screenFor } from './site/routes';
const App = lazy(() => import('./App'));
const Home = lazy(() => import('./site/Home'));
const Preview = lazy(() => import('./preview/Preview'));
const Admin = lazy(() => import('./admin/Admin'));
function Missing() {
  return (
    <main className="status-page">
      <h1>页面不存在</h1>
      <a href="/">返回首页</a>
    </main>
  );
}
import '@fontsource/dm-sans/latin-400.css';
import '@fontsource/dm-sans/latin-500.css';
import '@fontsource/dm-sans/latin-600.css';
import '@fontsource/dm-sans/latin-700.css';
import './styles.css';
const client = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true } },
});
const routes = { home: Home, app: App, preview: Preview, admin: Admin, missing: Missing };
const Screen =
  import.meta.env.DEV && new URLSearchParams(location.search).get('local') === '1'
    ? lazy(() => import('./LocalReview'))
    : routes[screenFor(location.pathname, location.search)];
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={client}>
      <Suspense fallback={null}>
        <Screen />
      </Suspense>
    </QueryClientProvider>
  </React.StrictMode>,
);
