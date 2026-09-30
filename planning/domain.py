from dataclasses import dataclass
from decimal import Decimal


class PlanError(Exception):
    def __init__(self, code, message, status=422, details=None):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status
        self.details = details or {}


@dataclass(frozen=True)
class StationOccurrence:
    occurrence_id: str
    station_id: str
    position_m: Decimal
    price: Decimal


@dataclass(frozen=True)
class FuelPurchase:
    occurrence_id: str
    station_id: str
    position_m: Decimal
    price: Decimal
    gallons: Decimal
    cost: Decimal
    arrival_gallons: Decimal
    departure_gallons: Decimal
