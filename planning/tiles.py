"""Fixed Geoapify raster endpoint; credentials stay on the server."""

import base64

import httpx
from django.conf import settings
from django.http import HttpResponse

from planning.cache import get_json, key, set_json


def map_tile(request, plan_id, z, x, y):
    if not 0 <= z <= 18 or not 0 <= x < 2**z or not 0 <= y < 2**z:
        return HttpResponse(status=404)
    if get_json("map:" + str(plan_id)) is None:
        return HttpResponse(status=404)
    if not settings.GEOAPIFY_API_KEY:
        return HttpResponse(status=503)
    cache_key = key("tile", ["osm-carto", z, x, y])
    saved = get_json(cache_key)
    if saved is None:
        try:
            with httpx.Client(timeout=5) as client:
                with client.stream(
                    "GET",
                    f"https://maps.geoapify.com/v1/tile/osm-carto/{z}/{x}/{y}.png",
                    params={"apiKey": settings.GEOAPIFY_API_KEY},
                ) as response:
                    if response.status_code != 200:
                        return HttpResponse(status=503)
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 512_000:
                            return HttpResponse(status=503)
            if not body.startswith(b"\x89PNG\r\n\x1a\n"):
                return HttpResponse(status=503)
            saved = {"png": base64.b64encode(body).decode("ascii")}
            set_json(cache_key, saved, timeout=86400)
        except httpx.HTTPError:
            return HttpResponse(status=503)
    result = HttpResponse(base64.b64decode(saved["png"]), content_type="image/png")
    result["Cache-Control"] = "private, max-age=3600"
    return result
