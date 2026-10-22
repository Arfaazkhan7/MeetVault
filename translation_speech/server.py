"""Optional organization-owned standard-voice service. No model/API is paid
or downloaded automatically. Run behind HTTPS; keep the bearer key private.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import threading
import time
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class SpeechCache:
    def __init__(self, engine, ttl=120, max_bytes=50_000_000):
        self.engine, self.ttl, self.max_bytes = engine, ttl, max_bytes
        self.cache, self.lock = OrderedDict(), threading.Lock()
        self.waiting = threading.BoundedSemaphore(8)

    def render(self, key, text, language):
        # Scope the supplied segment key to its actual content. Two listeners
        # reuse one generation; a reused key cannot serve another text's audio.
        digest = hashlib.sha256((key + '\0' + language + '\0' + text).encode()).hexdigest()
        if not self.waiting.acquire(blocking=False):
            raise RuntimeError('Speech service is busy')
        try:
            with self.lock:
                now = time.monotonic()
                for old in list(self.cache):
                    if self.cache[old][0] <= now:
                        del self.cache[old]
                if digest in self.cache:
                    return self.cache[digest][1]
                audio = self.engine(text, language)
                if not isinstance(audio, bytes) or len(audio) > 2_000_000:
                    raise RuntimeError('Invalid speech output')
                self.cache[digest] = (now + self.ttl, audio)
                total = sum(len(item[1]) for item in self.cache.values())
                while total > self.max_bytes and self.cache:
                    _, (_, removed) = self.cache.popitem(last=False)
                    total -= len(removed)
                return audio
        finally:
            self.waiting.release()


def load_engine():
    import torch
    import soundfile as sf
    from parler_tts import ParlerTTSForConditionalGeneration
    from transformers import AutoTokenizer

    path = os.environ['TRANSLATION_MODEL_PATH']
    device = os.getenv('TRANSLATION_DEVICE', 'cuda' if torch.cuda.is_available() else 'cpu')
    model = ParlerTTSForConditionalGeneration.from_pretrained(path, local_files_only=True).to(device).eval()
    tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
    description_tokenizer = AutoTokenizer.from_pretrained(
        os.getenv('TRANSLATION_DESCRIPTION_TOKENIZER_PATH', model.config.text_encoder._name_or_path),
        local_files_only=True,
    )
    voices = {'en': 'Mary', 'hi': 'Divya', 'ta': 'Jaya'}

    def synthesize(text, language):
        description = (f"{voices[language]} speaks clearly at a moderate pace in a neutral tone. "
                       "The recording is close and clear with no background noise.")
        desc = description_tokenizer(description, return_tensors='pt').to(device)
        prompt = tokenizer(text, return_tensors='pt').to(device)
        with torch.inference_mode():
            torch.manual_seed(42)
            audio = model.generate(input_ids=desc.input_ids, attention_mask=desc.attention_mask,
                                   prompt_input_ids=prompt.input_ids, prompt_attention_mask=prompt.attention_mask,
                                   max_new_tokens=1000)
        output = io.BytesIO()
        sf.write(output, audio.cpu().numpy().squeeze(), model.config.sampling_rate, format='WAV', subtype='PCM_16')
        return output.getvalue()
    return synthesize


def handler_for(cache, secret):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # Never log speech, credentials or request bodies.

        def send(self, status, payload, content_type='application/json'):
            data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path != '/health':
                return self.send(404, {'detail': 'Not found'})
            self.send(200, {'ready': True, 'languages': ['en', 'ta', 'hi'], 'voice': 'standard'})

        def do_POST(self):
            if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + secret):
                return self.send(401, {'detail': 'Unauthorized'})
            if self.path != '/v1/speech':
                return self.send(404, {'detail': 'Not found'})
            try:
                self.connection.settimeout(10)
                size = int(self.headers.get('Content-Length', '0'))
                if size <= 0 or size > 12000:
                    return self.send(413, {'detail': 'Speech request is too large'})
                data = json.loads(self.rfile.read(size))
                text, language = data.get('text'), data.get('language')
                if (not isinstance(text, str) or not text.strip() or len(text) > 600
                        or language not in ('en', 'ta', 'hi') or data.get('voice') != 'standard'):
                    return self.send(422, {'detail': 'Invalid speech request'})
                key = self.headers.get('Idempotency-Key', '')
                if not key or len(key) > 150:
                    return self.send(422, {'detail': 'A segment idempotency key is required'})
                audio = cache.render(key, text, language)
                self.send(200, audio, 'audio/wav')
            except (ValueError, TypeError, AttributeError):
                self.send(422, {'detail': 'Invalid speech request'})
            except Exception:
                self.send(503, {'detail': 'Speech generation is unavailable; use captions'})
    return Handler


def main():
    key = os.environ.get('TRANSLATION_SPEECH_KEY', '')
    if len(key) < 32:
        raise SystemExit('Set a private TRANSLATION_SPEECH_KEY of at least 32 characters')
    cache = SpeechCache(load_engine())  # Readiness only after weights load.
    server = ThreadingHTTPServer((os.getenv('BIND_HOST', '127.0.0.1'), int(os.getenv('PORT', '8090'))), handler_for(cache, key))
    server.daemon_threads = True
    server.serve_forever()


if __name__ == '__main__':
    main()
