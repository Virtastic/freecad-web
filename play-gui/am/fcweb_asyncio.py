# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""asyncio on the browser build: an event loop whose wake-up pipe is a pipe.

CPython's selector event loop wakes itself through ``socket.socketpair()``. Emscripten has
no socketpair -- it raises ``OSError: [Errno 138] Not supported`` -- so the loop's
constructor dies half-built, ``asyncio.run()`` fails, and ``__del__`` then complains that
``_ssock`` was never set. Measured 2026-09-12 when the CAM workbench activated: its asset
manager runs every store operation through ``asyncio.run``, logged "Failed to initialize
CAM assets ... [Errno 138] Not supported", and the tool library came up empty. The desktop
never sees any of it.

The loop only needs a pair of file descriptors it can select on: ``os.pipe()`` works here
(Emscripten's pipe filesystem answers ``poll``). So: a loop class whose self-pipe is a real
pipe behind a socket-shaped wrapper, installed as the default policy. Everything else in
asyncio is untouched.
"""
import asyncio
import os
import selectors
import socket


class _PipeEnd:
    """The four things the selector loop asks of its self-pipe sockets."""

    def __init__(self, fd, readable):
        self._fd = fd
        self._readable = readable

    def fileno(self):
        return self._fd

    def setblocking(self, flag):
        os.set_blocking(self._fd, bool(flag))

    def recv(self, n):
        return os.read(self._fd, n)

    def send(self, data):
        return os.write(self._fd, data)

    def close(self):
        if self._fd >= 0:
            try:
                os.close(self._fd)
            finally:
                self._fd = -1


class FcWebEventLoop(asyncio.SelectorEventLoop):
    """SelectorEventLoop with a pipe-backed self-pipe (no socketpair on Emscripten)."""

    def __init__(self):
        # SelectSelector: poll() on Emscripten's pipe fs is fine, but select() is the
        # most conservative choice and the loop never has more than a handful of fds.
        super().__init__(selectors.SelectSelector())

    def _make_self_pipe(self):
        rfd, wfd = os.pipe()
        self._ssock = _PipeEnd(rfd, True)
        self._csock = _PipeEnd(wfd, False)
        self._ssock.setblocking(False)
        self._csock.setblocking(False)
        self._internal_fds += 1
        self._add_reader(self._ssock.fileno(), self._read_from_self)

    def _close_self_pipe(self):
        self._remove_reader(self._ssock.fileno())
        self._ssock.close()
        self._ssock = None
        self._csock.close()
        self._csock = None
        self._internal_fds -= 1


class FcWebEventLoopPolicy(asyncio.DefaultEventLoopPolicy):
    _loop_factory = FcWebEventLoop


def needed():
    """True when socketpair is missing, i.e. on this build; False on a desktop Python."""
    try:
        a, b = socket.socketpair()
    except OSError:
        return True
    a.close()
    b.close()
    return False


def install():
    if not needed():
        return "asyncio: socketpair available, nothing to do"
    asyncio.set_event_loop_policy(FcWebEventLoopPolicy())

    async def _probe():
        await asyncio.sleep(0)
        return 42

    result = asyncio.run(_probe())
    return "asyncio: pipe-backed event loop installed (probe %s)" % result


if __name__ == "__main__":
    print(install())
