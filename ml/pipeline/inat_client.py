"""Minimal, polite iNaturalist API v1 client for sound observations.

API etiquette (https://www.inaturalist.org/pages/api+recommended+practices):
~1 request/second, a descriptive User-Agent, and modest media download volume.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import requests

API = "https://api.inaturalist.org/v1"
USER_AGENT = "Thicket-dataset-builder/0.1 (+https://github.com/shourya0mehta/thicket)"


class RateLimiter:
    def __init__(self, min_interval: float) -> None:
        self.min_interval = min_interval
        self._last = 0.0

    def wait(self) -> None:
        dt = time.monotonic() - self._last
        if dt < self.min_interval:
            time.sleep(self.min_interval - dt)
        self._last = time.monotonic()


@dataclass
class SoundRecord:
    observation_id: int
    sound_id: int
    file_url: str
    license_code: str
    attribution: str
    taxon_id: int
    taxon_name: str
    common_name: str
    user_id: int
    observed_on: str | None
    latitude: float | None
    longitude: float | None
    obscured: bool
    place_guess_country: str | None

    def as_row(self) -> dict[str, Any]:
        return dict(self.__dict__)


class INatClient:
    def __init__(self, min_interval: float = 1.1, session: requests.Session | None = None) -> None:
        self.s = session or requests.Session()
        self.s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        self.limiter = RateLimiter(min_interval)

    def get(self, path: str, params: dict[str, Any], retries: int = 5) -> dict[str, Any]:
        for attempt in range(retries):
            self.limiter.wait()
            try:
                r = self.s.get(f"{API}{path}", params=params, timeout=60)
                if r.status_code == 429 or r.status_code >= 500:
                    time.sleep(5 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json()
            except requests.RequestException:
                if attempt == retries - 1:
                    raise
                time.sleep(3 * (attempt + 1))
        raise RuntimeError(f"iNat request failed after {retries} attempts: {path} {params}")

    def resolve_taxon(self, name: str, rank: str | None = None) -> dict[str, Any] | None:
        params: dict[str, Any] = {"q": name, "per_page": 30, "is_active": "true"}
        if rank:
            params["rank"] = rank
        res = self.get("/taxa", params).get("results", [])
        exact = [t for t in res if t.get("name", "").lower() == name.lower()]
        if exact:
            return exact[0]
        syn = [t for t in res if (t.get("matched_term") or "").lower() == name.lower()]
        return syn[0] if syn else None

    def sound_observations(
        self,
        taxon_id: int,
        licenses: list[str],
        quality_grade: str = "research",
        place_id: int | None = None,
        without_taxon_ids: list[int] | None = None,
        max_pages: int = 10,
    ) -> Iterator[dict[str, Any]]:
        params: dict[str, Any] = {
            "taxon_id": taxon_id,
            "sounds": "true",
            "quality_grade": quality_grade,
            "sound_license": ",".join(licenses),
            "per_page": 200,
            "order_by": "id",
            "order": "desc",
            "locale": "en",
        }
        if place_id:
            params["place_id"] = place_id
        if without_taxon_ids:
            params["without_taxon_id"] = ",".join(str(t) for t in without_taxon_ids)
        id_below: int | None = None
        for _ in range(max_pages):
            if id_below:
                params["id_below"] = id_below
            data = self.get("/observations", params)
            results = data.get("results", [])
            if not results:
                return
            yield from results
            id_below = min(o["id"] for o in results)
            if len(results) < 200:
                return


def to_sound_record(obs: dict[str, Any], allowed_licenses: set[str]) -> SoundRecord | None:
    taxon = obs.get("taxon") or {}
    user = obs.get("user") or {}
    for snd in obs.get("sounds") or []:
        url = snd.get("file_url")
        lic = (snd.get("license_code") or "").lower()
        if not url or lic not in allowed_licenses:
            continue
        lat = lon = None
        loc = obs.get("location")
        if loc and "," in loc:
            try:
                lat_s, lon_s = loc.split(",")
                # Round to 0.1 deg (~11 km). Enough for range checks, avoids
                # redistributing precise observer locations.
                lat, lon = round(float(lat_s), 1), round(float(lon_s), 1)
            except ValueError:
                pass
        return SoundRecord(
            observation_id=int(obs["id"]),
            sound_id=int(snd.get("id") or 0),
            file_url=url,
            license_code=lic,
            attribution=snd.get("attribution") or "",
            taxon_id=int(taxon.get("id") or 0),
            taxon_name=taxon.get("name") or "",
            common_name=taxon.get("preferred_common_name") or "",
            user_id=int(user.get("id") or 0),
            observed_on=obs.get("observed_on"),
            latitude=lat,
            longitude=lon,
            obscured=bool(obs.get("obscured")),
            place_guess_country=None,
        )
    return None


def download(session: requests.Session, url: str, dest, max_bytes: int, retries: int = 4) -> int:
    for attempt in range(retries):
        try:
            with session.get(
                url, stream=True, timeout=120, headers={"User-Agent": USER_AGENT}
            ) as r:
                if r.status_code == 404:
                    return 0
                r.raise_for_status()
                n = 0
                with open(dest, "wb") as f:
                    for block in r.iter_content(1 << 16):
                        n += len(block)
                        if n > max_bytes:
                            return -1
                        f.write(block)
                return n
        except requests.RequestException:
            if attempt == retries - 1:
                return 0
            time.sleep(2 * (attempt + 1))
    return 0
