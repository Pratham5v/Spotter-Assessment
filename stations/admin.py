from django.contrib import admin

from stations.models import DatasetImport, PriceObservation, Station


class SnapshotAdmin(admin.ModelAdmin):
    """Inspect imported snapshots without editing their versioned contents."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register([DatasetImport, Station, PriceObservation], SnapshotAdmin)
