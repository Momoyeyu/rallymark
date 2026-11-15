import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  HardDrives,
  FilmStrip,
  UsersThree,
  Trash,
  SignOut,
  SignIn,
  Broom,
  ArrowClockwise,
} from '@phosphor-icons/react';
import { ApiError } from '../api';
import { adminRequest, jsonRequest, bytes, type User, type Storage } from './api';
import { ErrorNotice } from '../ui/ErrorNotice';
import { Brand } from '../ui/Brand';
import { Field } from '../ui/Fields';
import { ActionButton, IconButton } from '../ui/controls';
import { Dialog } from '../ui/Dialog';
import { Progress } from '../ui/Progress';
import Users from './Users';
import Videos from './Videos';
import '../site/site.css';
import './admin.css';

export default function Admin() {
  const client = useQueryClient();
  const me = useQuery({
    queryKey: ['admin', 'me'],
    queryFn: () => adminRequest<User>('/me'),
    retry: false,
    refetchInterval: 60000,
  });
  const [username, setUsername] = useState(''),
    [password, setPassword] = useState('');
  const [error, setError] = useState<ApiError | null>(null),
    [busy, setBusy] = useState(false),
    [clean, setClean] = useState(false);
  const [message, setMessage] = useState('');
  const tab = location.pathname.split('/')[2] || 'storage';
  const storage = useQuery({
    queryKey: ['admin', 'storage'],
    queryFn: () => adminRequest<Storage>('/storage'),
    enabled: me.isSuccess && me.data?.role === 'admin',
    refetchInterval: 30000,
  });
  function fail(e: unknown) {
    setError(e instanceof ApiError ? e : new ApiError('操作失败，请重试'));
  }
  async function login(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const user = await adminRequest<User>('/login', jsonRequest('POST', { username, password }));
      setPassword('');
      client.setQueryData(['admin', 'me'], user);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  async function logout() {
    try {
      await adminRequest('/logout', { method: 'POST' });
      client.removeQueries({ queryKey: ['admin'] });
      location.assign('/admin');
    } catch (e) {
      fail(e);
    }
  }
  async function cleanup() {
    setBusy(true);
    try {
      const r = await adminRequest<{ removed: number }>('/cleanup', { method: 'POST' });
      setClean(false);
      setMessage(`已清理 ${r.removed} 项`);
      await client.invalidateQueries({ queryKey: ['admin'] });
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }
  const needLogin = me.isError && me.error instanceof ApiError && me.error.status === 401;
  return (
    <div className="app-shell admin-shell">
      <a className="skip-link" href="#main-content">
        跳到内容
      </a>
      <header className="app-header">
        <Brand />
        <div className="admin-account">
          <span>{(me.isSuccess && me.data?.username) || '管理面板'}</span>
          {me.data && <IconButton icon={SignOut} label="退出登录" onClick={() => void logout()} />}
        </div>
      </header>
      <main id="main-content">
        {error && (
          <div className="admin-error" role="alert">
            <p>{error.message}</p>
            {error.requestId && <small>问题编号 {error.requestId}</small>}
            <IconButton icon={ArrowClockwise} label="收起提示" onClick={() => setError(null)} />
          </div>
        )}
        {me.isPending ? (
          <div className="status-page" role="status">
            读取管理面板
          </div>
        ) : needLogin ? (
          <section className="admin-login">
            <HardDrives size={40} />
            <h1>管理面板</h1>
            <p>管理视频与存储空间</p>
            <form className="admin-form" onSubmit={(event) => void login(event)}>
              <Field
                label="用户名"
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                maxLength={64}
              />
              <Field
                label="密码"
                autoComplete="current-password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                maxLength={128}
              />
              <ActionButton
                icon={SignIn}
                label={busy ? '登录中' : '登录'}
                tone="primary"
                type="submit"
                disabled={busy}
              />
            </form>
          </section>
        ) : me.isError ? (
          <div className="status-page" role="alert">
            <p>暂时无法连接管理服务</p>
            <ActionButton icon={ArrowClockwise} label="重试" onClick={() => void me.refetch()} />
          </div>
        ) : me.data?.role !== 'admin' ? (
          <div className="status-page">
            <h1>暂无管理权限</h1>
            <p>请联系管理员</p>
          </div>
        ) : (
          <div className="admin-layout">
            <nav className="admin-nav" aria-label="管理导航">
              {[
                { id: 'storage', label: '存储', icon: HardDrives },
                { id: 'videos', label: '视频', icon: FilmStrip },
                { id: 'trash', label: '回收站', icon: Trash },
                { id: 'users', label: '用户', icon: UsersThree },
              ].map(({ id, label, icon: Glyph }) => (
                <a key={id} href={`/admin/${id}`} aria-current={tab === id ? 'page' : undefined}>
                  <Glyph aria-hidden="true" />
                  <span>{label}</span>
                </a>
              ))}
            </nav>
            <div className="admin-content">
              {tab === 'users' ? (
                <Users current={me.data!} />
              ) : tab === 'videos' || tab === 'trash' ? (
                <Videos key={tab} trashed={tab === 'trash'} onError={fail} />
              ) : (
                <section aria-label="存储概览">
                  <div className="admin-section-heading">
                    <h1>存储</h1>
                    <IconButton
                      icon={ArrowClockwise}
                      label="刷新存储"
                      onClick={() => void storage.refetch()}
                    />
                  </div>
                  {storage.isPending ? (
                    <p role="status">读取存储</p>
                  ) : storage.isError ? (
                    <p role="alert">存储信息暂不可用</p>
                  ) : (
                    <>
                      <div className="storage-capacity">
                        <HardDrives size={32} />
                        <div>
                          <h2>视频数据盘</h2>
                          <p>
                            剩余 <strong>{bytes(storage.data.disk_free_bytes)}</strong> /{' '}
                            {bytes(storage.data.disk_total_bytes)}
                          </p>
                        </div>
                        <Progress
                          label="数据盘已用空间"
                          value={storage.data.disk_used_bytes}
                          max={storage.data.disk_total_bytes}
                        />
                      </div>
                      <dl className="storage-facts">
                        <div>
                          <dt>视频数量</dt>
                          <dd>
                            {storage.data.video_count}
                            <small> 项</small>
                          </dd>
                        </div>
                        <div>
                          <dt>播放文件</dt>
                          <dd>{bytes(storage.data.video_bytes)}</dd>
                        </div>
                        <div>
                          <dt>回收站</dt>
                          <dd>
                            {storage.data.trashed_count}
                            <small> 项</small>
                          </dd>
                        </div>
                        <div>
                          <dt>保留期限</dt>
                          <dd>
                            {storage.data.retention_days}
                            <small> 天</small>
                          </dd>
                        </div>
                      </dl>
                      <div className="storage-cleanup">
                        <div>
                          <h2>到期清理</h2>
                          <p>{storage.data.expired_count} 项已过期，处理中数据自动跳过。</p>
                        </div>
                        <ActionButton
                          icon={Broom}
                          label="清理到期"
                          onClick={() => {
                            setError(null);
                            setClean(true);
                          }}
                        />
                      </div>
                      <p className="admin-hint">
                        后台每小时自动清理。播放文件大小不含原始备份、算法缓存与缩略图。
                      </p>
                      {message && <p role="status">{message}</p>}
                    </>
                  )}
                </section>
              )}
            </div>
          </div>
        )}
      </main>
      <Dialog open={clean} title="清理到期数据" onClose={() => !busy && setClean(false)}>
        <ErrorNotice error={error} />
        <p className="admin-hint">将永久删除已过期的视频及其分析结果，处理中的任务会跳过。</p>
        <ActionButton
          icon={Broom}
          label={busy ? '清理中' : '确认清理'}
          tone="danger"
          disabled={busy}
          onClick={() => void cleanup()}
        />
      </Dialog>
    </div>
  );
}
