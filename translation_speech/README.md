# Organization-owned translated speech

This optional service adds **standard voices** for English, Tamil and Hindi.
It uses AI4Bharat Indic Parler-TTS (Apache-2.0), not voice cloning. It is not
hosted or activated automatically. Model inference has not been benchmarked on
your organization's hardware; the API tests use a synthetic engine.

The Cloudflare API sends already translated text to `POST /v1/speech` with a
private bearer key and a segment/language idempotency key. The service loads
weights once and caches generated audio for 120 seconds, so listeners choosing
the same language reuse one generation. One process serializes inference and
limits waiting requests to eight. Cache memory is bounded at 50 MB. Audio/text
are not logged or written to disk. Run **one replica/one process** for this pilot;
multiple replicas need a shared cache and inference queue before scaling.

## Prepare a host

Use an existing organization-owned GPU computer/server or explicitly budget a
GPU host. Ordinary Cloudflare Workers do not run this PyTorch service. CPU mode
is available for development and can be too slow for live meetings. No free
continuous GPU hosting is assumed.

1. Review and accept the model access conditions using your own Hugging Face
   account: https://huggingface.co/ai4bharat/indic-parler-tts . This is a gated
   download, even though the model card lists Apache-2.0.
2. Download a **specific reviewed revision** to a local directory and retain
   that revision in your deployment records. Cache the model's description
   tokenizer too (the identifier is in `config.json` under `text_encoder`).
   Downloads/access approval are intentionally separate from startup.
3. On Python 3.11 install `requirements.lock`, or build the Dockerfile. Mount
   model directories read-only. The server uses `local_files_only=True` and
   does not download models when serving requests.
4. Set these environment variables privately:

```text
TRANSLATION_MODEL_PATH=/models/indic-parler-tts
TRANSLATION_DESCRIPTION_TOKENIZER_PATH=/models/description-tokenizer
TRANSLATION_DEVICE=cuda
TRANSLATION_SPEECH_KEY=<a private random value of at least 32 characters>
```

Run `python server.py`. It binds `127.0.0.1:8090` by default. Put it behind your
organization's HTTPS reverse proxy, with request/body/connection limits; do not
expose the development HTTP listener directly. `/health` returns readiness only
after weights/tokenizers load successfully. In Docker the listener binds all
container interfaces; publish it only to loopback behind the proxy.

5. In the **existing API Worker**, add secret `TRANSLATION_SPEECH_KEY` and
   variable `TRANSLATION_SPEECH_URL=https://your-approved-host/v1/speech`.
   Never put the key in browser code or Git. This changes the caption UI's
   shared-voice option from unavailable to selectable. Verify real Tamil,
   Hindi and English output plus concurrent listeners before organization use.

Voice output accepts up to 600 characters per segment and returns WAV audio.
If generation exceeds the API timeout, captions continue and the UI reports
audio as unavailable. Low latency is not guaranteed until the host/model has
been measured. Generated speech must not be routed into microphone capture or
recorded as original participant speech. Headphones help avoid acoustic echo.

## Tests

```sh
python -m unittest -v test_server.py
```

These test authentication, validation and shared generation/cache behavior.
They do not download or execute model weights.
