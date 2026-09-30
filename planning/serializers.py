import math

from rest_framework import serializers


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) != set(self.fields):
            raise serializers.ValidationError(
                {"non_field_errors": ["Supply exactly the documented fields."]}
            )
        return super().to_internal_value(data)


class CoordinateField(serializers.FloatField):
    def to_internal_value(self, data):
        if isinstance(data, bool) or not isinstance(data, (float, int)) or not math.isfinite(data):
            raise serializers.ValidationError("A finite JSON number is required.")
        return super().to_internal_value(data)


class CoordinateSerializer(StrictSerializer):
    latitude = CoordinateField(min_value=-90, max_value=90)
    longitude = CoordinateField(min_value=-180, max_value=180)


class RoutePlanSerializer(StrictSerializer):
    start = CoordinateSerializer()
    finish = CoordinateSerializer()
