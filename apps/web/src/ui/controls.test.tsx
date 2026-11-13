import { describe, it, expect } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { Score } from './controls';

describe('score presentation', () => {
  it('keeps unknown scores compact without inventing a score', () => {
    const html = renderToStaticMarkup(
      <Score
        rally={{ id: 'r', start_s: 1, end_s: 2, score_status: 'unknown' }}
        index={0}
        hasScores
      />,
    );
    expect(html).toContain('—:—');
    expect(html).toContain('aria-label="比分未知"');
    expect(html).not.toContain('比分待确认');
  });
  it('preserves the inferred evidence status as an accessible graphic', () => {
    const html = renderToStaticMarkup(
      <Score
        rally={{ id: 'r', start_s: 1, end_s: 2, score: '12:11', score_status: 'inferred' }}
        index={0}
        hasScores
      />,
    );
    expect(html).toContain('12:11');
    expect(html).toContain('aria-label="推断比分"');
  });
  it('uses a rally number only when the whole video has no score evidence', () => {
    const html = renderToStaticMarkup(
      <Score
        rally={{ id: 'r', start_s: 1, end_s: 2, score_status: 'unknown' }}
        index={2}
        hasScores={false}
      />,
    );
    expect(html).toContain('03');
    expect(html).toContain('aria-label="回合序号"');
  });
  it('does not present an unverified score as observed', () => {
    const html = renderToStaticMarkup(
      <Score
        rally={{ id: 'r', start_s: 1, end_s: 2, score: '3:2', score_status: 'unknown' }}
        index={0}
        hasScores
      />,
    );
    expect(html).toContain('aria-label="待核比分"');
    expect(html).not.toContain('aria-label="识别比分"');
  });
});
