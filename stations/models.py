import uuid

from django.db import models
from django.db.models import Q


class DatasetImport(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_label = models.CharField(max_length=200)
    source_sha256 = models.CharField(max_length=64)
    enrichment_sha256 = models.CharField(max_length=64)
    fingerprint = models.CharField(max_length=64, unique=True)
    price_policy = models.CharField(max_length=80)
    normalization_version = models.CharField(max_length=80)
    enrichment_version = models.CharField(max_length=80)
    status = models.CharField(max_length=10, default="loading")
    is_active = models.BooleanField(default=False)
    imported_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True)
    source_observed_at = models.DateTimeField(null=True)
    summary = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["is_active"], condition=Q(is_active=True), name="one_active_dataset"
            ),
            models.CheckConstraint(
                condition=Q(is_active=False) | Q(status="complete"), name="active_requires_complete"
            ),
        ]


class Station(models.Model):
    dataset = models.ForeignKey(DatasetImport, on_delete=models.CASCADE, related_name="stations")
    opis_id = models.CharField(max_length=40)
    name = models.CharField(max_length=250)
    aliases = models.JSONField(default=list)
    address = models.CharField(max_length=300)
    city = models.CharField(max_length=150)
    state = models.CharField(max_length=2)
    price = models.DecimalField(max_digits=18, decimal_places=10)
    min_price = models.DecimalField(max_digits=18, decimal_places=10)
    max_price = models.DecimalField(max_digits=18, decimal_places=10)
    observation_count = models.PositiveIntegerField()
    distinct_price_count = models.PositiveIntegerField()
    location_fingerprint = models.CharField(max_length=64)
    latitude = models.FloatField(null=True)
    longitude = models.FloatField(null=True)
    coordinate_status = models.CharField(max_length=20, default="unresolved")
    coordinate_source = models.CharField(max_length=100, blank=True)
    location_evidence = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["dataset", "opis_id"], name="unique_dataset_station"),
            models.CheckConstraint(condition=Q(price__gt=0), name="positive_station_price"),
            models.CheckConstraint(
                condition=(
                    Q(latitude__isnull=True, longitude__isnull=True)
                    | Q(
                        latitude__gte=-90, latitude__lte=90, longitude__gte=-180, longitude__lte=180
                    )
                ),
                name="paired_valid_coordinates",
            ),
            models.CheckConstraint(
                condition=~Q(coordinate_status="accepted")
                | Q(latitude__isnull=False, longitude__isnull=False),
                name="accepted_requires_coordinates",
            ),
        ]
        indexes = [
            models.Index(fields=["dataset", "coordinate_status"]),
            models.Index(fields=["dataset", "latitude", "longitude"]),
        ]


class PriceObservation(models.Model):
    dataset = models.ForeignKey(
        DatasetImport, on_delete=models.CASCADE, related_name="observations"
    )
    station = models.ForeignKey(
        Station, on_delete=models.CASCADE, null=True, related_name="observations"
    )
    source_row_number = models.PositiveIntegerField()
    opis_id = models.CharField(max_length=40)
    rack_id = models.CharField(max_length=40)
    price = models.DecimalField(max_digits=18, decimal_places=10)
    raw = models.JSONField()
    classification = models.CharField(max_length=20)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["dataset", "source_row_number"], name="unique_source_row"
            )
        ]
