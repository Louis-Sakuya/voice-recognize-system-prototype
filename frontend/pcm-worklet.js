class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.carry = 0;
    this.pending = [];
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel || !channel.length) return true;
    let index = this.carry;
    while (index < channel.length) {
      const left = Math.floor(index);
      const right = Math.min(left + 1, channel.length - 1);
      const frac = index - left;
      const sample = channel[left] * (1 - frac) + channel[right] * frac;
      this.pending.push(Math.max(-1, Math.min(1, sample)));
      index += this.ratio;
    }
    this.carry = index - channel.length;
    const target = 3200;
    while (this.pending.length >= target) {
      const chunk = this.pending.splice(0, target);
      const pcm = new Int16Array(target);
      let sum = 0;
      for (let i = 0; i < target; i += 1) {
        const sample = chunk[i];
        sum += sample * sample;
        const scaled = sample < 0 ? sample * 32768 : sample * 32767;
        pcm[i] = Math.max(-32768, Math.min(32767, Math.round(scaled)));
      }
      this.port.postMessage({ pcm, rms: Math.sqrt(sum / target) }, [pcm.buffer]);
    }
    return true;
  }
}

registerProcessor("pcm-capture", PcmCaptureProcessor);
