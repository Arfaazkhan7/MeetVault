import concurrent.futures
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from server import SpeechCache, handler_for


class SpeechTests(unittest.TestCase):
    def test_concurrent_listeners_share_generation(self):
        calls = []
        cache = SpeechCache(lambda text, lang: calls.append((text, lang)) or b'RIFF-fixture')
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(lambda _: cache.render('segment:ta', 'வணக்கம்', 'ta'), range(5)))
        self.assertEqual(len(calls), 1)
        self.assertEqual(results, [b'RIFF-fixture'] * 5)
        cache.render('segment:ta', 'வேறு உரை', 'ta')
        self.assertEqual(len(calls), 2)

    def test_http_authentication_validation_and_audio(self):
        key = 'synthetic-test-only-private-key-123456'
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler_for(SpeechCache(lambda *_: b'RIFF-fixture'), key))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f'http://127.0.0.1:{server.server_port}/v1/speech'
        def send(data, secret=key):
            return urllib.request.urlopen(urllib.request.Request(url, json.dumps(data).encode(),
                headers={'Authorization': 'Bearer ' + secret, 'Idempotency-Key': 'fixture:hi', 'Content-Type': 'application/json'}))
        try:
            with self.assertRaises(urllib.error.HTTPError) as error:
                send({'text': 'नमस्ते', 'language': 'hi', 'voice': 'standard'}, 'wrong')
            self.assertEqual(error.exception.code, 401)
            with self.assertRaises(urllib.error.HTTPError) as error:
                send({'text': 'hello', 'language': 'fr', 'voice': 'standard'})
            self.assertEqual(error.exception.code, 422)
            with send({'text': 'नमस्ते', 'language': 'hi', 'voice': 'standard'}) as response:
                self.assertEqual(response.headers['Content-Type'], 'audio/wav')
                self.assertEqual(response.read(), b'RIFF-fixture')
        finally:
            server.shutdown()
            server.server_close()


if __name__ == '__main__':
    unittest.main()
