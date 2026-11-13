import { PingPong } from '@phosphor-icons/react';
export function Brand({ href = '/' }: { href?: string }) {
  return (
    <a href={href} className="brand" aria-label="RallyMark 首页">
      <PingPong weight="fill" />
      <span>
        Rally<span>Mark</span>
      </span>
    </a>
  );
}
