import requests_cache
from typing import Optional, Dict, Any
import pgeocode
from utils import haversine

# Load environment variables from .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass



# Set up requests_cache to cache API responses
requests_cache.install_cache('/var/data/marketcheck_cache', expire_after=3600)  # 1 hour cache


def _add_distances(ref_lon, ref_lat, dealer_lon, dealer_lat):
    if None in (ref_lon, ref_lat, dealer_lon, dealer_lat):
        return None
    try:
        return round(haversine(ref_lon, ref_lat, dealer_lon, dealer_lat), 1)
    except Exception:
        return None


def query_marketcheck_api(
    api_key: str,
    zip_code: str = '64735',
    radius: int = 50,
    make: str = 'Ford',
    model: str = 'Escape',
    year_range: str = '2023-2026',
    powertrain_type: str = "BEV,HEV,MHEV,PHEV",
    rows: int = 50,
    start: int = 0
) -> Optional[Dict[str, Any]]:
    """
    Query the MarketCheck API for car listings with caching.

    Args:
        api_key (str): Your MarketCheck API key.
        zip_code (str): ZIP code for search.
        radius (int): Search radius in miles.
        make (str): Car make.
        model (str): Car model.
        year_range (str): Year range, e.g., '2023-2026'.
        fuel_type (str): Fuel type(s), separated by '|'.
        rows (int): Number of results per page.
        start (int): Pagination start index.

    Returns:
        dict or None: API response JSON or None on error.
    """
    # https://docs.marketcheck.com/docs/api/cars/inventory/inventory-search
    url = "https://api.marketcheck.com/v2/search/car/active"
    params = {
        "api_key": api_key,
        "zip": zip_code,
        "radius": radius,
        "make": make,
        "model": model,
        "year_range": year_range,
        "powertrain_type": powertrain_type,
        "rows": rows,
        "start": start
    }
    nomi = pgeocode.Nominatim('us')
    data = nomi.query_postal_code(zip_code)
    ref_lat = data.latitude
    ref_lon = data.longitude    

    try:
        response = requests_cache.CachedSession().get(url, params=params)
        response.raise_for_status()
        result = response.json()
        result["cached"] = getattr(response, "from_cache", False)  # Indicate if response was from cache

        for listing in result.get("listings") or []:
            dealer = listing.get("dealer", {}) or {}
            listing["distance_miles"] = _add_distances(ref_lon, ref_lat, dealer.get("longitude"), dealer.get("latitude"))
        return result
    except Exception as e:
        print(f"Error querying MarketCheck API: {e}")
        return None
