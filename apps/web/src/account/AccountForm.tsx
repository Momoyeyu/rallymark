import { useState, type FormEvent } from 'react';
import { CaretRight, SignIn, UserCircle, UserPlus, WarningCircle } from '@phosphor-icons/react';
import { ActionButton } from '../ui/controls';
import { Field } from '../ui/Fields';

type Props = {
  mode: 'login' | 'register';
  onSubmit: (username: string, password: string) => Promise<void>;
  onSwitch: () => void;
  onBusy: (pending: boolean) => void;
};

type InputName = 'username' | 'password';

export function AccountForm({ mode, onSubmit, onSwitch, onBusy }: Props) {
  const register = mode === 'register';
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [invalid, setInvalid] = useState<{ name: InputName; message: string }>();
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    const username = String(fields.get('username')).trim();
    const password = String(fields.get('password'));
    function reject(name: InputName, message: string) {
      setInvalid({ name, message });
      (form.elements.namedItem(name) as HTMLInputElement).focus();
    }
    setError('');
    if (!/^[a-zA-Z0-9_.-]{3,64}$/.test(username)) {
      reject(
        'username',
        username ? '使用 3–64 个字母、数字、点、短横线或下划线。' : '请输入用户名。',
      );
      return;
    }
    if (!password || (register && Array.from(password).length < 8)) {
      reject('password', password ? '密码至少需要 8 个字符。' : '请输入密码。');
      return;
    }
    setPending(true);
    onBusy(true);
    try {
      await onSubmit(username, password);
    } catch (e) {
      setError(e instanceof Error ? e.message : '暂时无法提交，请重试。');
    } finally {
      setPending(false);
      onBusy(false);
    }
  }
  return (
    <form
      className="account-form"
      noValidate
      aria-busy={pending}
      onSubmit={(event) => void submit(event)}
      onChange={(event) => {
        if (error) setError('');
        if (event.target instanceof HTMLInputElement && event.target.name === invalid?.name) {
          setInvalid(undefined);
        }
      }}
    >
      <p className="account-intro">保存视频与分析结果，在其他设备继续回看。</p>
      <div className="account-fields">
        <Field
          name="username"
          label="用户名"
          icon={UserCircle}
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
          required
          maxLength={64}
          disabled={pending}
          error={invalid?.name === 'username' ? invalid.message : undefined}
        />
        <Field
          name="password"
          label="密码"
          hint={register ? '至少 8 个字符' : undefined}
          type="password"
          autoComplete={register ? 'new-password' : 'current-password'}
          required
          maxLength={128}
          disabled={pending}
          error={invalid?.name === 'password' ? invalid.message : undefined}
        />
      </div>
      {error && (
        <div className="account-form-error" role="alert">
          <WarningCircle aria-hidden="true" />
          <span>{error}</span>
        </div>
      )}
      <ActionButton
        className="account-submit"
        icon={register ? UserPlus : SignIn}
        label={pending ? '提交中' : register ? '注册并登录' : '登录'}
        tone="primary"
        type="submit"
        disabled={pending}
      />
      <div className="account-switch">
        <span>{register ? '已有账号？' : '首次使用？'}</span>
        <button type="button" disabled={pending} onClick={onSwitch}>
          {register ? '返回登录' : '创建账号'}
          <CaretRight aria-hidden="true" />
        </button>
      </div>
    </form>
  );
}
