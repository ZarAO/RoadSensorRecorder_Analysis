"""
In-process job queue: one analysis at a time (spec §5 — no Celery/Redis).
"""

import os
from concurrent.futures import ThreadPoolExecutor


class JobQueue:
    def __init__(self, inline: bool = False):
        # inline=True (tests): run the job synchronously in the caller thread
        self._inline = inline
        self._executor = None if inline else ThreadPoolExecutor(max_workers=1)

    def submit(self, fn, *args):
        if self._inline:
            fn(*args)
            return None
        return self._executor.submit(fn, *args)

    def shutdown(self):
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)


def make_queue() -> JobQueue:
    return JobQueue(inline=os.environ.get('RQA_QUEUE_INLINE') == '1')
