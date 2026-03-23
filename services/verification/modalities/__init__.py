"""
Cross-modal verification modalities.

Each modality provides an independent data source for verifying claims:
- trade: UN Comtrade import/export data
- financial: World Bank development indicators
- diplomatic: UN voting records
- satellite: Sentinel-2 Copernicus imagery
- shipping: MarineTraffic AIS vessel tracking
- flights: ADS-B Exchange aircraft tracking
- nightlights: NASA Black Marble nighttime light data
"""

from services.verification.modalities.trade import verify_trade_claim
from services.verification.modalities.financial import verify_financial_claim
from services.verification.modalities.diplomatic import verify_diplomatic_claim
from services.verification.modalities.satellite import verify_satellite_claim
from services.verification.modalities.shipping import verify_shipping_claim
from services.verification.modalities.flights import verify_flight_claim
from services.verification.modalities.nightlights import verify_nightlight_claim

# Registry of all available modalities.
MODALITY_REGISTRY = {
    "trade": verify_trade_claim,
    "financial": verify_financial_claim,
    "diplomatic": verify_diplomatic_claim,
    "satellite": verify_satellite_claim,
    "shipping": verify_shipping_claim,
    "flights": verify_flight_claim,
    "nightlights": verify_nightlight_claim,
}

# Modalities to try per domain (ordered by relevance)
DOMAIN_MODALITIES = {
    "geopolitical": ["satellite", "diplomatic", "shipping", "flights", "nightlights"],
    "economic": ["financial", "trade", "nightlights"],
    "market": ["financial", "trade", "shipping"],
    "political": ["diplomatic", "financial"],
    "sentiment": ["financial"],
}

DEFAULT_MODALITIES = ["financial", "trade", "diplomatic", "satellite"]


def get_modalities_for_domain(domain: str) -> list:
    """Get ordered list of modality names to try for a given domain."""
    return DOMAIN_MODALITIES.get(domain, DEFAULT_MODALITIES)
