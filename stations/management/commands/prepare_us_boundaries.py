import hashlib
import io
import json
import zipfile
from pathlib import Path

import shapefile
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from pyproj import CRS, Transformer
from shapely.geometry import shape
from shapely.ops import transform, unary_union

from stations.ingestion import US_STATES


class Command(BaseCommand):
    help = "Prepare a versioned WGS84 USA polygon from a local Census TIGER state ZIP."

    def add_arguments(self, parser):
        parser.add_argument("archive")

    def handle(self, archive, **options):
        source = Path(archive)
        with zipfile.ZipFile(source) as zipped:
            base = "tl_2025_us_state"
            crs = CRS.from_wkt(zipped.read(base + ".prj").decode())
            project = Transformer.from_crs(crs, 4326, always_xy=True)
            reader = shapefile.Reader(
                shp=io.BytesIO(zipped.read(base + ".shp")),
                shx=io.BytesIO(zipped.read(base + ".shx")),
                dbf=io.BytesIO(zipped.read(base + ".dbf")),
            )
            supported, territories = [], []
            for record in reader.iterShapeRecords():
                polygon = shape(record.shape.__geo_interface__)
                (
                    supported if record.record.as_dict()["STUSPS"] in US_STATES else territories
                ).append(polygon)
            boundary = transform(project.transform, unary_union(supported))
            if not boundary.is_valid or len(supported) != 51:
                raise CommandError("Invalid 50 states + DC boundary")
            target = settings.US_BOUNDARY_PATH
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(boundary.wkb)
            target.with_name("territories.wkb").write_bytes(
                transform(project.transform, unary_union(territories)).wkb
            )
            metadata = {
                "source": "Census TIGER2025 STATE",
                "source_url": "https://www2.census.gov/geo/tiger/TIGER2025/STATE/tl_2025_us_state.zip",
                "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                "source_crs": crs.to_string(),
                "boundary_sha256": hashlib.sha256(boundary.wkb).hexdigest(),
            }
            target.with_suffix(".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            self.stdout.write(json.dumps(metadata))
