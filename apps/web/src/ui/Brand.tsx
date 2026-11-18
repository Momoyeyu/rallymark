import { Flask, PingPong } from '@phosphor-icons/react';
import { Tooltip } from './Tooltip';

export function Brand({ href = '/', beta = false }: { href?: string; beta?: boolean }) {
  const link = (
    <a href={href} className="brand" translate="no" aria-label="RallyMark 首页">
      <PingPong weight="fill" aria-hidden="true" />
      <span>
        Rally<span>Mark</span>
      </span>
    </a>
  );
  if (!beta) return link;
  return (
    <div className="brand-lockup">
      {link}
      <Tooltip label="当前为内测版本，线上可能随时更新。遇到问题时，可先刷新网页。" tap>
        <button type="button" className="beta-badge" aria-label="Beta 内测说明">
          <span className="beta-badge-mark" translate="no">
            <Flask aria-hidden="true" weight="bold" />
            Beta
          </span>
        </button>
      </Tooltip>
    </div>
  );
}
