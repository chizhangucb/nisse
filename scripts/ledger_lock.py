#!/usr/bin/env python3
"""Cross-process lock for the hub session ledger.

records/sessions_index.md is one shared file that every session's Stop hook and
the session-close sweeper read-modify-write. With no lock, two writes that both
read the old table and both rewrite it drop whichever row the loser added: a
classic lost-update race.

This is the single serialization point. Both writers hold an flock on the
ledger's sibling `.sessions_index.lock` across their whole read-modify-write.
The sweeper (detached, no budget) blocks for it; the Stop hook (10s budget)
uses the non-blocking path and fails open so a stuck lock never hangs a session.

The Stop hook stays import-free by design, so it inlines the same flock pattern
rather than importing this module. Keep the two in sync.
"""
import contextlib
import fcntl
import os
import time

LOCKFILE = ".sessions_index.lock"


def lock_path_for(ledger_path):
    """The lockfile that guards a given ledger file (its sibling)."""
    return os.path.join(os.path.dirname(ledger_path), LOCKFILE)


@contextlib.contextmanager
def ledger_lock(ledger_path, blocking=True, retry_seconds=2.0, poll=0.05):
    """Hold an exclusive lock while mutating the ledger.

    blocking=True blocks until the lock is held (detached sweeper).
    blocking=False retries non-blocking for retry_seconds, then yields anyway
    (fail-open) so a hook on a tight budget never hangs on a stuck lock.
    Yields True if the lock is held, False if it gave up and the caller is
    proceeding unlocked.
    """
    path = lock_path_for(ledger_path)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o644)
    except OSError:
        # Cannot even open the lockfile: fail open, better a rare race than a
        # hook that cannot write the ledger at all.
        yield False
        return
    held = False
    try:
        if blocking:
            fcntl.flock(fd, fcntl.LOCK_EX)
            held = True
        else:
            deadline = time.monotonic() + retry_seconds
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    held = True
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        break
                    time.sleep(poll)
        yield held
    finally:
        if held:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)
