import { CaretDown, Info } from '@phosphor-icons/react';
export function Notice({ messages }: { messages: string[] }) {
  if (!messages.length) return null;
  return (
    <details className="notice">
      <summary>
        <Info aria-hidden="true" />
        <span>结果说明</span>
        <CaretDown className="notice-caret" aria-hidden="true" />
      </summary>
      <ul>
        {messages.map((message, index) => (
          <li key={index}>{message}</li>
        ))}
      </ul>
    </details>
  );
}
