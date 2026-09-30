import hashlib
import json

from django.core.cache import cache

TTL = 3600


def key(namespace, value):
    return (
        namespace
        + ":"
        + hashlib.sha256(
            json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
    )


def get_json(cache_key):
    value = cache.get(cache_key)
    return json.loads(value) if isinstance(value, str) else None


def set_json(cache_key, value, timeout=TTL):
    cache.set(cache_key, json.dumps(value, allow_nan=False, separators=(",", ":")), timeout)
