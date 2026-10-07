/* Stream microphone PCM16 in the provider's required 20 ms / 16 kHz frames. */
class InterviewCapture extends AudioWorkletProcessor {
    constructor() {
        super();
        this.ratio = sampleRate / 16000;
        this.weight = 0;
        this.sum = 0;
        this.offset = 0;
        this.frame = new ArrayBuffer(640);
        this.view = new DataView(this.frame);
    }

    process(inputs) {
        const samples = inputs[0]?.[0];
        if (!samples) return true;
        for (const sample of samples) {
            let remaining = 1;
            while (remaining > 0.000001) {
                const used = Math.min(remaining, this.ratio - this.weight);
                this.sum += sample * used;
                this.weight += used;
                remaining -= used;
                if (this.weight >= this.ratio - 0.000001) {
                    const value = Math.max(-1, Math.min(1, this.sum / this.ratio));
                    this.view.setInt16(this.offset, Math.round(value * (value < 0 ? 32768 : 32767)), true);
                    this.offset += 2;
                    this.sum = 0;
                    this.weight = 0;
                    if (this.offset === 640) {
                        this.port.postMessage(this.frame, [this.frame]);
                        this.frame = new ArrayBuffer(640);
                        this.view = new DataView(this.frame);
                        this.offset = 0;
                    }
                }
            }
        }
        return true;
    }
}
registerProcessor('interview-capture', InterviewCapture);
