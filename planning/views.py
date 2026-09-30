import logging
import uuid

from django.http import HttpResponse
from django.shortcuts import render
from rest_framework.exceptions import ParseError, UnsupportedMediaType
from rest_framework.response import Response
from rest_framework.views import APIView

from planning.cache import get_json
from planning.domain import PlanError
from planning.planner import build_plan
from planning.serializers import RoutePlanSerializer

logger = logging.getLogger(__name__)


class RoutePlanView(APIView):
    def handle_exception(self, exc):
        if isinstance(exc, (ParseError, UnsupportedMediaType)):
            return Response(
                {
                    "error": {
                        "code": "INVALID_INPUT",
                        "message": "Send a valid JSON coordinate request.",
                    },
                    "request_id": str(uuid.uuid4()),
                },
                status=exc.status_code,
            )
        return super().handle_exception(exc)

    def post(self, request):
        request_id = str(uuid.uuid4())
        serializer = RoutePlanSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {
                    "error": {
                        "code": "INVALID_INPUT",
                        "message": "Invalid coordinate request.",
                        "details": serializer.errors,
                    },
                    "request_id": request_id,
                },
                status=400,
            )
        coordinates = serializer.validated_data
        try:
            result = build_plan(
                *[
                    [coordinates[k]["longitude"], coordinates[k]["latitude"]]
                    for k in ("start", "finish")
                ]
            )
            return Response(result)
        except PlanError as exc:
            return Response(
                {
                    "error": {"code": exc.code, "message": exc.message, "details": exc.details},
                    "request_id": request_id,
                },
                status=exc.status,
            )
        except Exception as exc:
            # Do not log provider exception text, headers or URLs.
            logger.error("Route planning failed request=%s type=%s", request_id, type(exc).__name__)
            return Response(
                {
                    "error": {"code": "INTERNAL_ERROR", "message": "Route planning failed."},
                    "request_id": request_id,
                },
                status=500,
            )


def plan_map(request, plan_id):
    plan = get_json("map:" + str(plan_id))
    if plan is None:
        return HttpResponse(
            "This map was not found or has expired. Request a new plan.",
            status=404,
            content_type="text/plain",
        )
    return render(request, "planning/map.html", {"plan": plan})
