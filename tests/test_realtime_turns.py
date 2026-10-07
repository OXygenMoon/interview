"""Continuous silence, short pauses and early provider output ordering."""
import os
import struct

os.environ.setdefault('APP_ENV', 'testing')
os.environ.setdefault('SECRET_KEY', 'test-secret-key')
os.environ.setdefault('LLM_API_KEY', 'test-llm-key')

from app.services.realtime_turns import ReplySilenceGate

VOICE = struct.pack('<320h', *([4000] * 320))
QUIET = bytes(640)


def speak(gate, now):
    gate.audio(VOICE, now - .02)
    return gate.audio(VOICE, now)


def reply(response_id='r1'):
    return [
        {'type': 'response.output_text.delta', 'response_id': response_id, 'delta': '追问'},
        {'type': 'response.output_audio.delta', 'response_id': response_id, 'delta': 'AAAA'},
        {'type': 'response.output_text.done', 'response_id': response_id, 'text': '追问'},
        {'type': 'response.output_audio.done', 'response_id': response_id},
    ]


def test_silence_must_reach_three_seconds_before_text_audio_and_save_events_release():
    gate = ReplySilenceGate()
    assert gate.accept(reply('greeting')[0], 0)
    speak(gate, 1)
    for event in reply():
        assert not gate.accept(event, 1.5)
    gate.audio(QUIET, 3.99)
    assert gate.release(3.99) == []
    gate.audio(QUIET, 4)
    assert gate.release(4) == reply()
    assert gate.release(4.1) == []


def test_resuming_before_three_seconds_discards_old_reply_and_restarts_window():
    gate = ReplySilenceGate()
    speak(gate, 1)
    for event in reply():
        gate.accept(event, 1.5)
    gate.audio(QUIET, 2)
    assert speak(gate, 2.5)  # Ask the bridge to cancel the unheard reply.
    assert not gate.accept(reply()[0], 3)  # Late chunks of canceled response.
    for event in reply('r2'):
        gate.accept(event, 4)
    gate.audio(QUIET, 5.49)
    assert gate.release(5.49) == []
    gate.audio(QUIET, 5.5)
    assert gate.release(5.5) == reply('r2')


def test_stalled_microphone_does_not_count_as_silence_but_explicit_mute_does():
    gate = ReplySilenceGate()
    speak(gate, 1)
    gate.accept(reply()[0], 2)
    assert gate.release(10) == []
    gate.muted = True
    assert gate.release(10) == [reply()[0]]


def test_quiet_speech_asr_progress_resets_timer_without_repeated_snapshot_extending_it():
    gate = ReplySilenceGate()
    gate.speech_started(1)
    first = {'item_id': 'q1', 'delta': '我负责'}
    gate.speech_progress(first, 2)
    gate.accept(reply()[0], 2.5)
    assert gate.speech_progress({'item_id': 'q1', 'delta': '我负责数据库'}, 3)
    assert not gate.speech_progress({'item_id': 'q1', 'delta': '我负责数据库'}, 4)
    gate.accept(reply('r2')[0], 4)
    gate.audio(QUIET, 5.99)
    assert gate.release(5.99) == []
    gate.audio(QUIET, 6)
    assert gate.release(6) == [reply('r2')[0]]


def test_clicks_and_background_noise_do_not_restart_the_wait_and_cancel_drops_output():
    gate = ReplySilenceGate()
    speak(gate, 1)
    gate.accept(reply()[0], 1.5)
    gate.audio(QUIET, 2)
    gate.audio(VOICE, 2.02)  # A single 20 ms click.
    noise = struct.pack('<320h', *([60] * 320))
    gate.audio(noise, 2.04)
    gate.audio(QUIET, 4)
    assert gate.release(4) == [reply()[0]]
    speak(gate, 5)
    gate.accept(reply('r2')[0], 6)
    assert gate.accept({'type': 'response.canceled'}, 6)
    gate.audio(QUIET, 8)
    assert gate.release(8) == []
    assert not gate.accept(reply('r2')[-1], 8)


def test_delayed_asr_text_does_not_add_extra_wait_to_microphone_silence():
    gate = ReplySilenceGate()
    speak(gate, 1)
    gate.speech_started(1.1)
    speak(gate, 2)
    gate.audio(QUIET, 2.02)
    gate.speech_progress({'item_id': 'q1', 'delta': '延迟收到的识别结果'}, 3)
    gate.accept(reply()[0], 3.5)
    gate.audio(QUIET, 5)
    assert gate.release(5) == [reply()[0]]
