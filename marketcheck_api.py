import time
import requests_cache
from typing import Optional, Dict, Any
from utils import haversine
import pgeocode

# Load environment variables from .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass



# Set up requests_cache to cache API responses
requests_cache.install_cache('marketcheck_cache', expire_after=86400)  # 24 hour cache

def query_marketcheck_api(
    api_key: str,
    zip_code: str = '64735',
    ref_zip: str = None,
    radius: int = 50,
    make: str = 'Ford',
    model: str = 'Escape',
    year_range: str = '2023-2026',
    powertrain_type: str = "HEV",
    rows: int = 50,
    max_results: int = 500,
) -> Optional[Dict[str, Any]]:
    url = "https://api.marketcheck.com/v2/search/car/active"
    base_params = {
        "api_key": api_key,
        "zip": zip_code,
        "radius": radius,
        "make": make,
        "model": model,
        "year_range": year_range,
        "powertrain_type": powertrain_type,
        "rows": rows,
    }

    nomi = pgeocode.Nominatim('us')
    geo = nomi.query_postal_code(ref_zip or zip_code)
    ref_lat = geo.latitude
    ref_lon = geo.longitude

    def _add_distance(listing):
        dealer = listing.get("dealer", {}) or {}
        dlat = dealer.get("latitude")
        dlon = dealer.get("longitude")
        if ref_lat is not None and ref_lon is not None and dlat is not None and dlon is not None:
            try:
                listing["distance_miles"] = round(haversine(ref_lon, ref_lat, dlon, dlat), 1)
                return
            except Exception:
                pass
        listing["distance_miles"] = None

    session = requests_cache.CachedSession()
    all_listings = []
    num_found = None
    start = 0

    try:
        while True:
            response = session.get(url, params={**base_params, "start": start})
            response.raise_for_status()
            cached = getattr(response, "from_cache", False)
            if not cached:
                print(f"MarketCheck API call: make={make} model={model} start={start} rows={rows}")
                time.sleep(0.5)
            page = response.json()

            listings = page.get("listings") or []
            if num_found is None:
                num_found = page.get("num_found", 0)

            for listing in listings:
                _add_distance(listing)
            all_listings.extend(listings)

            print(f"  {make} {model}: fetched {len(all_listings)}/{num_found} (page start={start}, cached={cached})")

            if not listings or len(all_listings) >= min(num_found, max_results):
                break
            start += len(listings)

        return {"num_found": num_found, "listings": all_listings, "cached": False}
    except Exception as e:
        print(f"Error querying MarketCheck API: {e}")
        return None
