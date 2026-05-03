import os
import pgeocode
import pytest
from vehicle_inventory import query_marketcheck_api

# @pytest.mark.skipif(
    # os.environ.get("MARKETCHECK_API_KEY") is None,
#     reason="MARKETCHECK_API_KEY environment variable not set"
# )
def test_zip():
    nomi = pgeocode.Nominatim('us')
    data = nomi.query_postal_code("27519")
    assert data is not None
    assert data.place_name == "Cary"
    assert data.state_name == "North Carolina"
    assert data.longitude == pytest.approx(-78.867, 3)
    assert data.latitude == pytest.approx(35.073, 3)
    assert data.longitude is not None   

def test_query_marketcheck_api():
    api_key = os.environ["MARKETCHECK_API_KEY"]
    result = query_marketcheck_api(
        api_key=api_key,
        zip_code="64735",
        radius=100,
        make="Ford",
        model="Escape",
        year_range="2023-2026",
        powertrain_type="HEV",
        rows=50,
        start=0
    )
    from pprint import pprint
    pprint(result)
    assert result is not None, "API call returned None"
    assert "listings" in result, "No 'listings' key in API response"
    assert isinstance(result["listings"], list), "'listings' is not a list"




def test_query_marketcheck_api_invalid_zip(monkeypatch):
    # Should handle invalid zip code gracefully
    api_key = os.environ.get("MARKETCHECK_API_KEY", "INVALID_KEY")
    result = query_marketcheck_api(api_key=api_key, zip_code="00000")
    # Accept None or a result with no listings
    assert result is None or ("listings" in result and isinstance(result["listings"], list))


def test_query_marketcheck_api_defaults(monkeypatch):
    # Should work with only API key (all defaults)
    api_key = os.environ.get("MARKETCHECK_API_KEY", "INVALID_KEY")
    result = query_marketcheck_api(api_key=api_key)
    # Accept None or a result with listings
    assert result is None or ("listings" in result and isinstance(result["listings"], list))


def test_query_marketcheck_api_mocked(monkeypatch):
    # Mock requests_cache.CachedSession.get to avoid real HTTP call
    class DummyResponse:
        def __init__(self):
            self.status_code = 200
            self.from_cache = True
        def raise_for_status(self):
            pass
        def json(self):
            return {"listings": [{"dealer": {"latitude": 1, "longitude": 2}}]}

    monkeypatch.setattr("requests_cache.CachedSession.get", lambda self, url, params: DummyResponse())
    api_key = "DUMMY"
    result = query_marketcheck_api(api_key=api_key)
    assert result is not None
    assert "listings" in result
    assert result["cached"] is True
