from django.urls import path

from planning.tiles import map_tile
from planning.views import RoutePlanView, plan_map

urlpatterns = [
    path("api/v1/route-plan/", RoutePlanView.as_view(), name="route-plan"),
    path("map/<uuid:plan_id>/", plan_map, name="plan-map"),
]
urlpatterns += [
    path("map/<uuid:plan_id>/tiles/<int:z>/<int:x>/<int:y>.png", map_tile, name="map-tile")
]
