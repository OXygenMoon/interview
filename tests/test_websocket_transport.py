"""Short writes and concurrent heartbeat writes must not corrupt frames."""

import os
import threading
import time

os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'test-secret-key')
os.environ.setdefault('LLM_API_KEY', 'test-llm-key')

from app.services.websocket_transport import WebSocketTransport


class ShortWriteSocket:
    def __init__(self):
        self.data = bytearray()

    def send(self, data):
        count = min(7, len(data))
        self.data.extend(data[:count])
        time.sleep(0.0001)
        return count

    def sendall(self, data):
        while data:
            data = data[self.send(data):]


def test_audio_and_heartbeat_writes_remain_complete_and_separate():
    raw = ShortWriteSocket()
    transport = WebSocketTransport(raw)
    frames = [b'a' * 640, b'p' * 32, b'c' * 60]
    threads = [threading.Thread(target=transport.send, args=(frame,)) for frame in frames]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()
    assert len(raw.data) == sum(len(frame) for frame in frames)
    assert all(frame in raw.data for frame in frames)
