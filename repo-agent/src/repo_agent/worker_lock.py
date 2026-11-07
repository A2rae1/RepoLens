"""One live writer per job on the shared local data volume.

All API workers must share DATA_DIR (including artifacts and these lock files).
This is a single-host coordination mechanism, not a cross-host distributed lock.
Never unlink a lock file: another process may still hold its inode/handle.
"""

import errno
import hashlib
import os
from contextlib import contextmanager
from functools import partial
from pathlib import Path


@contextmanager
def job_lock(data_dir: Path, job: str):
    root = data_dir / "worker-locks"
    root.mkdir(exist_ok=True)
    path = root / (hashlib.sha256(job.encode()).hexdigest() + ".lock")
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt

            if os.fstat(fd).st_size == 0:
                os.write(fd, b"0")
            os.lseek(fd, 0, os.SEEK_SET)
            acquire = partial(msvcrt.locking, fd, msvcrt.LK_NBLCK, 1)
            release = partial(msvcrt.locking, fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            acquire = partial(fcntl.flock, fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            release = partial(fcntl.flock, fd, fcntl.LOCK_UN)
        try:
            acquire()
            acquired = True
        except OSError as error:
            if error.errno not in {errno.EACCES, errno.EAGAIN}:
                raise
        yield acquired
    finally:
        if acquired:
            os.lseek(fd, 0, os.SEEK_SET)
            release()
        os.close(fd)
