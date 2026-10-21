"""Use the runtime's RSA verifier instead of loading OpenSSL into WASM.

Only Google's pinned HTTPS certificate endpoint supplies these public keys.
python-jose still enforces the allowed algorithm and all JWT claim checks.
"""
from jose.backends.base import Key


def certificate_spki(certificate: str) -> bytes:
    from asn1crypto import pem, x509

    label, _, der = pem.unarmor(certificate.encode("ascii"))
    if label == "CERTIFICATE":
        return x509.Certificate.load(der)["tbs_certificate"]["subject_public_key_info"].dump()
    if label == "PUBLIC KEY":
        return der
    raise ValueError("Expected a signing certificate or public key")


class WorkersRSAKey(Key):
    def __init__(self, certificate: str):
        self.spki = certificate_spki(certificate)

    def verify(self, message: bytes, signature: bytes) -> bool:
        from js import Object, crypto
        from pyodide.ffi import run_sync, to_js

        async def verify_signature():
            algorithm = to_js(
                {"name": "RSASSA-PKCS1-v1_5", "hash": "SHA-256"},
                dict_converter=Object.fromEntries,
            )
            key = await crypto.subtle.importKey(
                "spki", to_js(self.spki), algorithm, False, to_js(["verify"]),
            )
            return bool(await crypto.subtle.verify(
                "RSASSA-PKCS1-v1_5", key, to_js(signature), to_js(message),
            ))

        return run_sync(verify_signature())
