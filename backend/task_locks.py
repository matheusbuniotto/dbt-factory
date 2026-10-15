"""Per-task locks: one warehouse job per task at a time (duckdb is single-writer)."""

import threading

TASK_LOCKS: dict = {}


def tlock(tid):
    return TASK_LOCKS.setdefault(tid, threading.Lock())
