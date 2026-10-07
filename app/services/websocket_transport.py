"""Keep WebSocket writes complete and prevent HTTP output after an upgrade."""

import socket
import threading

from simple_websocket import ConnectionClosed


class WebSocketTransport:
    """Socket adapter shared by application, heartbeat and close-frame writers."""

    def __init__(self, sock):
        self.sock = sock
        self.write_lock = threading.Lock()

    def __getattr__(self, name):
        return getattr(self.sock, name)

    def send(self, data, *args):
        # simple-websocket uses send() and ignores partial writes. Audio frames
        # must finish before a ping, pong or close can write to the same socket.
        with self.write_lock:
            self.sock.sendall(data, *args)
        return len(data)

    def close(self):
        # Werkzeug retains a makefile reference to the underlying socket.
        # close() alone leaves it writable, allowing a trailing HTTP 200/500
        # response to corrupt an already-upgraded WebSocket connection.
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


def prepare_websocket_transport(environ):
    for key in ('werkzeug.socket', 'gunicorn.socket'):
        sock = environ.get(key)
        if sock is not None and not isinstance(sock, WebSocketTransport):
            environ[key] = WebSocketTransport(sock)


def close_websocket_transport(ws):
    try:
        ws.close()
    except (ConnectionClosed, OSError):
        pass
    if ws.mode == 'werkzeug':
        # Flush the protocol close first, then stop HTTP from writing to this
        # wire. Do not wait for a peer that has already gone away.
        ws.sock.close()
