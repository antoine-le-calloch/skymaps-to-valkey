import io
import time
import requests


class APIError(Exception):
    pass


class SkyPortal:
    """Minimal SkyPortal client used to fetch GCN events and download localizations."""

    def __init__(self, instance, token, validate=True):
        self.base_url = instance.rstrip("/")
        self.headers = {"Authorization": f"token {token}"}
        if validate:
            r = requests.get(f"{self.base_url}/api/sysinfo", timeout=40)
            if r.status_code != 200:
                raise APIError("SkyPortal API not available")
            r = requests.get(f"{self.base_url}/api/config", headers=self.headers, timeout=40)
            if r.status_code != 200:
                raise APIError("SkyPortal authentication failed (invalid token?)")

    def _request(self, method, endpoint, data=None, return_response=False):
        url = f"{self.base_url}/{endpoint.strip('/')}"
        if method == "GET":
            r = requests.request(method, url, params=data, headers=self.headers, timeout=40)
        else:
            r = requests.request(method, url, json=data, headers=self.headers, timeout=40)

        if return_response:
            return r

        try:
            body = r.json()
        except Exception:
            raise APIError(r.text)
        if r.status_code != 200:
            raise APIError(body.get("message", r.text))
        return body.get("data")

    def fetch_all_pages(self, endpoint, payload, item_key):
        items = []
        payload["pageNumber"] = 1
        payload["numPerPage"] = 1000
        while True:
            results = self._request("GET", endpoint, data=payload)
            items += results[item_key]
            if results["totalMatches"] <= len(items):
                break
            payload["pageNumber"] += 1
            time.sleep(0.3)
        return items

    def get_gcn_events(self, start_date):
        """Same selection as crossmatch-alert-to-skymaps:
        - GW / BNS / NSBH / SVOM / Einstein Probe (excluding BBH, MLy, Terrestrial)
        - + Fermi notices with localization < 1000 sq. deg.
        """
        base = {"startDate": start_date, "excludeNoticeContent": True}
        events = self.fetch_all_pages(
            "/api/gcn_event",
            {**base, "gcnTagKeep": "GW,BNS,NSBH,SVOM,Einstein Probe", "gcnTagRemove": "BBH,MLy,Terrestrial"},
            "events",
        )
        events += self.fetch_all_pages(
            "/api/gcn_event",
            {**base, "gcnTagKeep": "Fermi", "localizationTagKeep": "< 1000 sq. deg."},
            "events",
        )
        return events

    def download_localization(self, dateobs, localization_name):
        r = self._request(
            "GET",
            f"/api/localization/{dateobs}/name/{localization_name}/download",
            return_response=True,
        )
        if r.status_code != 200:
            raise APIError(f"Error fetching localization: {r.text}")
        return io.BytesIO(r.content)
