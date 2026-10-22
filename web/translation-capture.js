/* AudioWorklet: microphone only, downsampled to 16 kHz PCM16. No AI runs here. */
class TranslationCapture extends AudioWorkletProcessor {
  constructor(){super();this.phase=0;this.sum=0;this.count=0;this.samples=new Int16Array(8000);this.offset=0;}
  process(inputs){
    const input=inputs[0]?.[0];if(!input)return true;
    for(const sample of input){
      this.sum+=sample;this.count++;this.phase+=16000;
      if(this.phase>=sampleRate){
        this.phase-=sampleRate;
        const value=Math.max(-1,Math.min(1,this.sum/this.count));this.sum=0;this.count=0;
        this.samples[this.offset++]=Math.round(value*(value<0?32768:32767));
        if(this.offset===8000){this.port.postMessage(this.samples.buffer,[this.samples.buffer]);this.samples=new Int16Array(8000);this.offset=0;}
      }
    }
    return true;
  }
}
registerProcessor('meetvault-translation-capture',TranslationCapture);
