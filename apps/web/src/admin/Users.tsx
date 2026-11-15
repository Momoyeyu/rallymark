import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, PencilSimple, Check, UserCircle } from '@phosphor-icons/react';
import { adminRequest, jsonRequest, type User } from './api';
import { ErrorNotice } from '../ui/ErrorNotice';
import { Field } from '../ui/Fields';
import { Select } from '../ui/Select';
import { Dialog } from '../ui/Dialog';
import { ActionButton, IconButton } from '../ui/controls';

export default function Users({ current }: { current: User }) {
  const client = useQueryClient();
  const users = useQuery({
    queryKey: ['admin', 'users'],
    queryFn: () => adminRequest<User[]>('/users'),
  });
  const [editing, setEditing] = useState<User | 'new' | null>(null);
  const [name, setName] = useState(''),
    [password, setPassword] = useState('');
  const [role, setRole] = useState('member'),
    [active, setActive] = useState(true);
  const [formError, setFormError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  function open(user: User | 'new') {
    setFormError(null);
    setEditing(user);
    setName(user === 'new' ? '' : user.username);
    setPassword('');
    setRole(user === 'new' ? 'member' : user.role);
    setActive(user === 'new' ? true : user.active);
  }
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!editing) return;
    setSaving(true);
    try {
      await adminRequest(
        editing === 'new' ? '/users' : '/users/' + editing.id,
        jsonRequest(
          editing === 'new' ? 'POST' : 'PATCH',
          editing === 'new'
            ? { username: name, password, role }
            : { ...(password ? { password } : {}), role, active },
        ),
      );
      const self = editing !== 'new' && editing.id === current.id;
      setEditing(null);
      await client.invalidateQueries({ queryKey: ['admin', 'users'] });
      if (self) {
        client.removeQueries({ queryKey: ['admin'] });
        location.assign('/admin');
      }
    } catch (e) {
      setFormError(e);
    } finally {
      setSaving(false);
    }
  }
  return (
    <section aria-label="用户管理">
      <div className="admin-section-heading">
        <h1>用户</h1>
        <ActionButton icon={Plus} label="新增用户" onClick={() => open('new')} />
      </div>
      <p className="admin-hint">账户供管理与后续功能使用，上传分析仍免登录。</p>
      {users.isPending ? (
        <p role="status">读取用户</p>
      ) : users.isError ? (
        <p role="alert">用户暂未载入</p>
      ) : (
        <div className="admin-list">
          {users.data.map((u) => (
            <div className="admin-row user-row" key={u.id}>
              <div className="admin-row-title">
                <strong>{u.username}</strong>
                <span>
                  {u.role === 'admin' ? '管理员' : '普通用户'}
                  {u.id === current.id ? ' / 当前' : ''}
                </span>
              </div>
              <span className={`state-badge ${u.active ? 'good' : ''}`}>
                {u.active ? '启用' : '停用'}
              </span>
              <IconButton icon={PencilSimple} label={`编辑${u.username}`} onClick={() => open(u)} />
            </div>
          ))}
        </div>
      )}
      <Dialog
        open={editing !== null}
        title={editing === 'new' ? '新增用户' : '编辑用户'}
        onClose={() => !saving && setEditing(null)}
      >
        <ErrorNotice error={formError} />
        <form className="admin-form" onSubmit={(event) => void save(event)}>
          <Field
            label="用户名"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoComplete="off"
            required
            minLength={3}
            maxLength={64}
            pattern="[A-Za-z0-9_.-]+"
            disabled={editing !== 'new'}
          />
          <Field
            label={editing === 'new' ? '密码' : '新密码（留空保留）'}
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            required={editing === 'new'}
            minLength={8}
            maxLength={128}
          />
          <Select
            label="角色"
            icon={UserCircle}
            value={role}
            options={[
              { value: 'member', label: '普通用户' },
              { value: 'admin', label: '管理员' },
            ]}
            onChange={setRole}
          />
          {editing !== 'new' && (
            <button
              type="button"
              className="setting-toggle"
              role="switch"
              aria-checked={active}
              onClick={() => setActive(!active)}
            >
              <span>启用账户</span>
              <span className={`switch ${active ? 'on' : ''}`} aria-hidden="true">
                <i />
              </span>
            </button>
          )}
          <ActionButton
            icon={Check}
            label={saving ? '保存中' : '保存'}
            tone="primary"
            type="submit"
            disabled={saving}
          />
        </form>
      </Dialog>
    </section>
  );
}
