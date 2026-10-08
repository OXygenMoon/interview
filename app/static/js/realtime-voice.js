/* Credentials stay on the Flask server. No provider config comes from JS. */
class InterviewRealtimeVoice {
    constructor(options) {
        this.options = options;
        this.active = false;
        this.ready = false;
        this.disabled = false;
        this.muted = false;
        this.turnCommitted = false;
        this.manualReplyDone = false;
        this.generation = 0;
        this.sources = new Set();
        this.nextPlayback = 0;
        this.aiBubbles = new Map();
        this.userBubbles = new Map();
        this.completedUserBubbles = new Map();
        this.savedUsers = new Set();
        this.interruptedResponses = new Set();
        this.currentResponse = null;
    }

    status(text) { this.options.onStatus(text, this); }

    async start() {
        if (this.stopping) await this.stopping;
        if (this.active || this.disabled) return;
        if (!window.isSecureContext) {
            this.status(window.InterviewMediaAccess?.message || '当前为 HTTP 访问，请使用 HTTPS 地址，或输入文字继续面试。');
            return;
        }
        if (!navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
            this.status('当前浏览器不支持实时语音，请使用新版 Safari、Chrome 或 Edge，或输入文字继续面试。');
            return;
        }
        this.active = true;
        this.ready = false;
        this.muted = false;
        this.turnCommitted = false;
        this.manualReplyDone = false;
        this.interruptedResponses.clear();
        this.currentResponse = null;
        this.userBubbles.clear();
        this.completedUserBubbles.clear();
        const generation = ++this.generation;
        this.status('正在连接实时语音…');
        // Permission prompts and AudioContext/Worklet initialization may never resolve.
        this.connectTimer = setTimeout(() => {
            if (generation === this.generation && !this.ready) {
                this.fail('麦克风启动超时，请确认浏览器权限后重新连接，或输入文字继续面试。');
            }
        }, 30000);
        try {
            const Context = window.AudioContext || window.webkitAudioContext;
            this.context = new Context();
            await this.context.resume();
            if (generation !== this.generation) return;
            const mic = await navigator.mediaDevices.getUserMedia({audio: {
                channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true,
            }});
            if (generation !== this.generation) {
                mic.getTracks().forEach(track => track.stop());
                return;
            }
            this.mic = mic;
            mic.getAudioTracks()[0].addEventListener('ended', () => {
                if (this.active) this.fail('麦克风连接已断开，请重新连接。');
            });
            await this.context.audioWorklet.addModule(this.options.captureUrl);
            if (generation !== this.generation) return;
            this.input = this.context.createMediaStreamSource(mic);
            this.capture = new AudioWorkletNode(this.context, 'interview-capture');
            this.silence = this.context.createGain();
            this.silence.gain.value = 0;
            this.input.connect(this.capture).connect(this.silence).connect(this.context.destination);
            const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
            const socket = new WebSocket(`${protocol}//${location.host}/api/interview/${this.options.sessionId}/realtime`);
            this.socket = socket;
            socket.binaryType = 'arraybuffer';
            this.capture.port.onmessage = ({data}) => {
                if (this.ready && !this.muted && !this.turnCommitted && socket.readyState === WebSocket.OPEN) {
                    if (socket.bufferedAmount > 64000) {
                        this.fail('网络上传过慢，实时语音已暂停，请重新连接。');
                        return;
                    }
                    socket.send(data);
                }
            };
            socket.onopen = () => {
                if (generation !== this.generation || !this.active) {
                    socket.close();
                    return;
                }
                socket.send(JSON.stringify({type: 'connect',
                    csrf_token: document.querySelector('meta[name="csrf-token"]')?.content || ''}));
            };
            socket.onmessage = ({data}) => {
                if (generation !== this.generation) return;
                try { this.handle(JSON.parse(data)); }
                catch (error) { this.fail('语音数据处理失败，请重新连接。'); }
            };
            socket.onerror = () => {
                if (generation === this.generation) this.fail('实时语音连接失败，请检查网络或使用文字回答。');
            };
            socket.onclose = () => {
                if (this.socket === socket) this.resolveClose?.();
                if (generation === this.generation && this.active) {
                    this.fail('实时语音已断开，点击重新连接。');
                }
            };
            clearTimeout(this.connectTimer);
            this.connectTimer = setTimeout(() => {
                if (generation === this.generation && !this.ready) this.fail('语音连接超时，请重新连接。');
            }, 15000);
        } catch (error) {
            if (generation === this.generation) {
                await this.stop();
                this.status(error.name === 'NotAllowedError'
                    ? '麦克风权限未开启，请允许后重新连接。'
                    : '无法启动麦克风，请检查设备后重新连接。');
            }
        }
    }

    control(type) {
        if (this.socket?.readyState === WebSocket.OPEN && this.ready) {
            this.socket.send(JSON.stringify({type}));
        }
    }

    toggleMute() {
        if (!this.ready || this.turnCommitted) return;
        this.muted = !this.muted;
        this.control(this.muted ? 'input_audio_mute.commit' : 'input_audio_unmute.commit');
        this.mic?.getAudioTracks().forEach(track => { track.enabled = !this.muted; });
        this.status(this.muted ? '麦克风已静音，点击恢复' : '正在倾听，可直接说话打断面试官');
    }

    interrupt() {
        if (this.currentResponse) this.interruptedResponses.add(this.currentResponse);
        this.stopPlayback();
        this.control('response.cancel');
        this.resumeManualInput();
        this.status('已打断，正在倾听');
    }

    finishTurn() {
        if (!this.ready || this.turnCommitted || this.sources.size) return;
        this.turnCommitted = true;
        this.manualReplyDone = false;
        this.control('input_audio_buffer.commit');
        this.status('本次回答已结束，面试官正在接话…');
        this.replyTimer = setTimeout(() => {
            if (this.turnCommitted && this.active) {
                this.resumeManualInput();
                this.status('面试官暂未回应，可继续回答或再次点击“我说完了”。');
            }
        }, 30000);
    }

    resumeManualInput() {
        if (!this.turnCommitted) return;
        clearTimeout(this.replyTimer);
        this.turnCommitted = false;
        this.manualReplyDone = false;
        if (this.active && !this.muted) this.control('input_audio_unmute.commit');
    }

    completeManualReply() {
        if (!this.turnCommitted || !this.manualReplyDone || this.sources.size) return;
        this.resumeManualInput();
        this.status(this.muted ? '麦克风已静音，点击恢复' : '正在倾听，可以继续下一次回答');
    }

    stopPlayback() {
        for (const source of this.sources) {
            try { source.stop(); } catch (error) { /* Already ended. */ }
        }
        this.sources.clear();
        this.nextPlayback = 0;
    }

    play(delta) {
        if (!this.context || this.context.state === 'closed') return;
        const raw = atob(delta);
        const bytes = Uint8Array.from(raw, char => char.charCodeAt(0));
        if (bytes.length % 2) throw new Error('Invalid PCM16');
        const view = new DataView(bytes.buffer);
        const buffer = this.context.createBuffer(1, bytes.length / 2, 24000);
        const samples = buffer.getChannelData(0);
        for (let index = 0; index < samples.length; index++) samples[index] = view.getInt16(index * 2, true) / 32768;
        const source = this.context.createBufferSource();
        source.buffer = buffer;
        source.connect(this.context.destination);
        this.sources.add(source);
        source.onended = () => {
            this.sources.delete(source);
            this.completeManualReply();
            if (!this.turnCommitted && this.active && this.ready && !this.sources.size) {
                this.status(this.muted ? '麦克风已静音，点击恢复' : '正在倾听，可直接说话打断面试官');
            }
        };
        const start = Math.max(this.context.currentTime + 0.03, this.nextPlayback);
        source.start(start);
        this.nextPlayback = start + buffer.duration;
    }

    handle(event) {
        const kind = event.type;
        if (kind === 'ready') {
            clearTimeout(this.connectTimer);
            this.ready = true;
            this.status('正在倾听，可直接说话打断面试官');
        } else if (kind === 'feature.disabled') {
            this.disabled = true;
            this.fail(event.message || '管理员已关闭实时语音交互，请使用文字回答。');
        } else if (kind === 'error') {
            this.fail(event.message || '实时语音服务暂时不可用。');
        } else if (kind === 'conversation.item.input_audio_transcription.started') {
            if (this.turnCommitted) return;
            if (this.currentResponse) this.interruptedResponses.add(this.currentResponse);
            this.stopPlayback();
            this.status('正在倾听…');
        } else if (kind === 'conversation.item.input_audio_transcription.delta') {
            const id = event.item_id || 'current';
            if (this.completedUserBubbles.has(id)) return;
            let bubble = this.userBubbles.get(id);
            if (!bubble) {
                bubble = this.options.createUserBubble();
                this.userBubbles.set(id, bubble);
            }
            bubble.textContent = event.delta || '';
            this.options.scroll();
        } else if (kind === 'conversation.item.input_audio_transcription.completed') {
            const id = event.item_id || 'current';
            if (this.completedUserBubbles.has(id)) return;
            const bubble = this.userBubbles.get(id) || this.options.createUserBubble();
            bubble.textContent = event.transcript || event.text || bubble.textContent;
            this.completedUserBubbles.set(id, bubble);
            this.userBubbles.delete(id);
            this.options.scroll();
            this.status(this.turnCommitted ? '本次回答已结束，面试官正在接话…' : '等待连续安静 3 秒后，面试官开始回答…');
        } else if (kind === 'conversation.item.input_audio_transcription.failed') {
            const id = event.item_id || 'current';
            this.userBubbles.get(id)?.closest('.chat')?.remove();
            this.userBubbles.delete(id);
            this.resumeManualInput();
            this.status('这句话未听清，请再说一次');
        } else if (kind === 'response.output_text.delta' || kind === 'response.output_text.done') {
            const id = event.response_id || 'current';
            let bubble = this.aiBubbles.get(id);
            if (!bubble) {
                bubble = this.options.createAiBubble();
                this.aiBubbles.set(id, bubble);
            }
            if (kind.endsWith('.delta')) bubble.contentEl.textContent += event.delta || '';
            else if (event.text) bubble.contentEl.textContent = event.text;
            this.options.scroll();
        } else if (kind === 'response.output_audio.delta') {
            if (event.response_id && this.interruptedResponses.has(event.response_id)) return;
            this.currentResponse = event.response_id;
            if (this.turnCommitted) clearTimeout(this.replyTimer);
            this.play(event.delta);
            this.status(this.turnCommitted ? '面试官正在说话，播报结束后可继续回答' :
                (this.muted ? '麦克风已静音，面试官正在说话' : '面试官正在说话，可直接开口打断'));
        } else if (kind === 'response.canceled') {
            this.stopPlayback();
        } else if (kind === 'response.output_audio.done') {
            if (this.turnCommitted) {
                clearTimeout(this.replyTimer);
                this.manualReplyDone = true;
                this.completeManualReply();
                return;
            }
            this.status(this.muted ? '麦克风已静音，点击恢复' : '正在倾听，可直接说话打断面试官');
        } else if (kind === 'audio.saved') {
            const bubble = this.aiBubbles.get(event.response_id || 'current');
            if (bubble && event.audio_url) {
                bubble.bubbleEl.onclick = () => this.options.playReplay(event.audio_url);
                bubble.bubbleEl.title = '点击重播';
            }
        } else if (kind === 'transcript.saved' && event.sender === 'user') {
            const id = event.item_id || 'current';
            if (event.text) {
                const bubble = this.completedUserBubbles.get(id) || this.userBubbles.get(id)
                    || this.options.createUserBubble();
                bubble.textContent = event.text;
                this.completedUserBubbles.set(id, bubble);
                this.userBubbles.delete(id);
                this.options.scroll();
            }
            if (!this.savedUsers.has(event.message_id)) {
                this.savedUsers.add(event.message_id);
                this.options.onUserSaved?.(event.message_id);
            }
        } else if (kind === 'transcript.saved' && event.sender === 'ai' && event.audio_url) {
            const bubble = this.aiBubbles.get(event.response_id || 'current');
            if (bubble) {
                bubble.bubbleEl.onclick = () => this.options.playReplay(event.audio_url);
                bubble.bubbleEl.title = '点击重播';
            }
        } else if (kind === 'session.closed') {
            this.resolveClose?.();
        }
    }

    async fail(message) {
        // A failed provider/socket cannot acknowledge another session.close.
        // Release the mic immediately without sending into a closing socket.
        await this.stop({notifyServer: false});
        this.status(message);
    }

    stop(options = {}) {
        if (this.stopping) return this.stopping;
        this.stopping = this.closeSession(options).finally(() => { this.stopping = null; });
        return this.stopping;
    }

    async closeSession({notifyServer = true} = {}) {
        this.active = false;
        clearTimeout(this.replyTimer);
        this.turnCommitted = false;
        this.manualReplyDone = false;
        clearTimeout(this.connectTimer);
        this.capture?.disconnect();
        if (this.capture) this.capture.port.onmessage = null;
        this.input?.disconnect();
        this.silence?.disconnect();
        this.mic?.getTracks().forEach(track => track.stop());
        this.mic = null;
        this.stopPlayback();
        const socket = this.socket;
        if (notifyServer && socket?.readyState === WebSocket.OPEN && this.ready) {
            // The bridge persists final transcripts before acknowledging close.
            const closed = new Promise(resolve => { this.resolveClose = resolve; });
            socket.send(JSON.stringify({type: 'session.close'}));
            await Promise.race([closed, new Promise(resolve => setTimeout(resolve, 4000))]);
        }
        ++this.generation;
        this.ready = false;
        this.socket = null;
        socket?.close();
        if (this.context && this.context.state !== 'closed') await this.context.close();
        this.context = null;
        this.resolveClose = null;
        this.status('实时语音已停止');
    }
}
window.InterviewRealtimeVoice = InterviewRealtimeVoice;
