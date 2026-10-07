"""Keep early duplex replies behind a continuous microphone-silence window."""

from collections import deque
import math
import struct


REPLY_SILENCE_SECONDS = 3.0
OUTPUT_EVENTS = {
    'response.output_text.delta', 'response.output_text.done',
    'response.output_audio.started', 'response.output_audio.delta',
    'response.output_audio.done', 'response.done',
}


class ReplySilenceGate:
    def __init__(self):
        self.last_voice = None
        self.last_acoustic_voice = None
        self.asr_voice_only = True
        self.last_frame = None
        self.muted = False
        self.noise_floor = 0.001
        self.voiced_frames = 0
        self.pending = deque()
        self.pending_bytes = 0
        self.discarded = deque(maxlen=128)
        self.hypothesis = None

    def speech_started(self, now):
        # ASR also protects very quiet speech below the local energy threshold.
        self.asr_voice_only = self.last_acoustic_voice is None or now - self.last_acoustic_voice > 0.5
        self.last_voice = now if self.asr_voice_only else self.last_acoustic_voice
        self.hypothesis = None
        if self.pending:
            self.discard_pending()
            return True
        return False

    def speech_progress(self, event, now):
        hypothesis = (event.get('item_id'), event.get('delta', ''))
        if not hypothesis[1] or hypothesis == self.hypothesis:
            return False
        self.hypothesis = hypothesis
        if not self.asr_voice_only:
            # Delayed ASR text must not add its network/decoding latency to
            # the three seconds already measured from microphone samples.
            return False
        self.last_voice = now
        if self.pending:
            self.discard_pending()
            return True
        return False

    def audio(self, frame, now):
        self.last_frame = now
        samples = struct.unpack('<320h', frame)
        rms = math.sqrt(sum(value * value for value in samples) / 320) / 32768
        threshold = max(0.004, self.noise_floor * 3)
        if rms >= threshold:
            self.voiced_frames += 1
            # Reject isolated clicks; two PCM frames represent 40 ms of sound.
            if self.voiced_frames >= 2:
                self.last_acoustic_voice = now
                self.asr_voice_only = False
                self.last_voice = now
                if self.pending:
                    self.discard_pending()
                    return True
        else:
            self.voiced_frames = 0
            self.noise_floor = self.noise_floor * 0.98 + rms * 0.02
        return False

    def can_reply(self, now):
        if self.last_voice is None:
            return True  # The initial greeting has no candidate turn to wait for.
        if now - self.last_voice < REPLY_SILENCE_SECONDS:
            return False
        # A stalled upload is not evidence that the microphone became quiet.
        return self.muted or (self.last_frame is not None and now - self.last_frame < 0.25)

    @staticmethod
    def response_id(event):
        return event.get('response_id') or (event.get('response') or {}).get('id') or 'current'

    def accept(self, event, now):
        if event.get('type') == 'response.canceled':
            self.discard_pending()
            return True
        if event.get('type') not in OUTPUT_EVENTS:
            return True
        if self.response_id(event) in self.discarded:
            return False
        if not self.can_reply(now) or self.pending:
            # Hold text, audio and persistence together, preserving event order.
            size = len(event.get('delta', '')) + len(event.get('text', '')) + 256
            if self.pending_bytes + size > 24 * 1024 * 1024:
                raise ValueError('Pending realtime reply exceeds limit')
            self.pending.append(event)
            self.pending_bytes += size
            return False
        return True

    def release(self, now):
        if not self.can_reply(now):
            return []
        result = list(self.pending)
        self.pending.clear()
        self.pending_bytes = 0
        return result

    def discard_pending(self):
        for event in self.pending:
            response_id = self.response_id(event)
            if response_id not in self.discarded:
                self.discarded.append(response_id)
        self.pending.clear()
        self.pending_bytes = 0
