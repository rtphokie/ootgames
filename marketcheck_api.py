import requests_cache
from typing import Optional, Dict, Any
import math
import pgeocode

# Load environment variables from .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import subprocess
import sys


# Set up requests_cache to cache API responses
requests_cache.install_cache('marketcheck_cache', expire_after=3600)  # 1 hour cache

def query_marketcheck_api(
    api_key: str,
    zip_code: str = '64735',
    radius: int = 50,
    make: str = 'Ford',
    model: str = 'Escape',
    year_range: str = '2023-2026',
    powertrain_type: str = "HEV",
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
    # https://api.marketcheck.com/v2/search/car/active?api_key=m430eAZiW2S90NYize5sMhcLwg3BPXGR&zip=64735&radius=100&make=Ford&model=Escape&powertrain_type=HEV
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

    def _haversine(lon1, lat1, lon2, lat2):
        R = 3958.8  # Earth radius in miles
        lon1, lat1, lon2, lat2 = map(float, [lon1, lat1, lon2, lat2])
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c



    try:
        response = requests_cache.CachedSession().get(url, params=params)
        response.raise_for_status()
        result = response.json()
        result["cached"] = getattr(response, "from_cache", False)  # Indicate if response was from cache

        # Add distance to each listing if possible
        if ref_lat is not None and ref_lon is not None and "listings" in result:
            for car in result["listings"]:
                dealer = car.get("dealer", {}) or {}
                dealer_lat = dealer.get("latitude")
                dealer_lon = dealer.get("longitude")
                if dealer_lat is not None and dealer_lon is not None:
                    try:
                        car["distance_miles"] = round(_haversine(ref_lon, ref_lat, dealer_lon, dealer_lat), 1)
                    except Exception:
                        car["distance_miles"] = None
                else:
                    car["distance_miles"] = None
        return result
    except Exception as e:
        print(f"Error querying MarketCheck API: {e}")
        return None
