"""Bounded, ordered window decoding without re-encoding or changing frame indices."""

from collections import deque
from concurrent.futures import ThreadPoolExecutor


def ordered_prefetch(items, decode, workers=1, depth=2):
    if workers < 1 or depth < 1 or depth > 8:
        raise ValueError("workers must be positive and depth must be in [1, 8]")
    source = iter(items)
    pending = deque()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        try:
            for _ in range(depth):
                item = next(source, None)
                if item is None:
                    break
                pending.append((item, pool.submit(decode, item)))
            while pending:
                item, future = pending.popleft()
                value = future.result()
                yield item, value
                next_item = next(source, None)
                if next_item is not None:
                    pending.append((next_item, pool.submit(decode, next_item)))
        finally:
            for _, future in pending:
                future.cancel()
