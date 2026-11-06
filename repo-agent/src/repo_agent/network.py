"""Use the OS certificate store; certificate and hostname verification remain enabled."""

import ssl
import sys

import certifi
import truststore


def tls_context():
    if sys.platform == "win32":
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # Preserve configured/system roots and add HTTPX's maintained Mozilla CA
    # bundle. Both certificate and hostname verification remain enabled.
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    return context
