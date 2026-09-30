from django.contrib import admin

from stations.models import DatasetImport, PriceObservation, Station

admin.site.register([DatasetImport, Station, PriceObservation])
