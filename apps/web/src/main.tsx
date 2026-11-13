import React, { lazy, Suspense } from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import './styles.css';
const client = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true } },
});
const Screen =
  import.meta.env.DEV && new URLSearchParams(location.search).get('local') === '1'
    ? lazy(() => import('./LocalReview'))
    : App;
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={client}>
      <Suspense fallback={null}>
        <Screen />
      </Suspense>
    </QueryClientProvider>
  </React.StrictMode>,
);
