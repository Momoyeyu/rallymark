import { useState, type FormEvent } from 'react';
import { SignIn, UserPlus } from '@phosphor-icons/react';
import { ActionButton } from '../ui/controls';
import { Field } from '../ui/Fields';

type Props = {
  mode: 'login' | 'register';
  onSubmit: (username: string, password: string) => Promise<void>;
  onSwitch: () => void;
  onBusy: (pending: boolean) => void;
};

export function AccountForm({ mode, onSubmit, onSwitch, onBusy }: Props) {
  const register = mode === 'register';
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const fields = new FormData(event.currentTarget);
    setPending(true);
    onBusy(true);
    setError('');
    try {
      await onSubmit(String(fields.get('username')).trim(), String(fields.get('password')));
    } catch (e) {
      setError(e instanceof Error ? e.message : '登录失败，请重试。');
    } finally {
      setPending(false);
      onBusy(false);
    }
  }
  return (
    <form className="product-dialog" onSubmit={(event) => void submit(event)}>
      <Field
        name="username"
        label="用户名"
        autoComplete="username"
        autoCapitalize="none"
        spellCheck={false}
        required
        minLength={3}
        maxLength={64}
        disabled={pending}
      />
      <Field
        name="password"
        label="密码"
        type="password"
        autoComplete={register ? 'new-password' : 'current-password'}
        required
        minLength={register ? 8 : 1}
        maxLength={128}
        disabled={pending}
      />
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="product-dialog-actions">
        <ActionButton
          icon={register ? UserPlus : SignIn}
          label={register ? '注册并登录' : '登录'}
          tone="primary"
          type="submit"
          disabled={pending}
        />
        <ActionButton
          icon={register ? SignIn : UserPlus}
          label={register ? '已有账号' : '创建账号'}
          disabled={pending}
          onClick={onSwitch}
        />
      </div>
    </form>
  );
}
