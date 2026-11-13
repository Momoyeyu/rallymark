import { PingPong } from '@phosphor-icons/react';
export function Brand({ href = '/' }: { href?: string }) {
  return (
    <a href={href} className="brand" translate="no" aria-label="RallyMark 首页">
      <PingPong weight="fill" aria-hidden="true" />
      <span>
        Rally<span>Mark</span>
      </span>
    </a>
  );
}
