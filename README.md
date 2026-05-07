# Skymaps to valkey

Populate a Valkey/Redis instance with a meta-MOC index of recent GCN skymaps,
to benchmark sub-millisecond crossmatch lookups against incoming alerts.

GCN events are fetched from SkyPortal (same selection as
[crossmatch-alert-to-skymaps](https://github.com/antoine-le-calloch/crossmatch-alert-to-skymaps)):
GW / BNS / NSBH / SVOM / Einstein Probe, plus Fermi notices with localization
< 1000 sq. deg. For each event, the FITS skymap is downloaded and reduced to a
MOC at a configurable cumulative probability (default 0.95). The MOC is then
flattened to HEALPix pixels at a configurable NESTED order, and an inverted
`pixel -> events` index is written to Valkey.

## Setup
```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.default .env  # fill SKYPORTAL_URL, SKYPORTAL_API_KEY, VALKEY_*
```

## Run
```bash
python populate_valkey.py --depth 6 --days 7 --clear
```

CLI options:
- `--depth N`  HEALPix NESTED order of the inverted index (default 6 -> NSIDE=64).
- `--days N`   Lookback window for GCN events (default 7).
- `--cumprob`  Cumulative probability threshold for each MOC (default 0.95).
- `--clear`    Delete all existing `skymap:*` keys before populating.
- `--env`      Path to the `.env` file (default `.env`).

## Valkey layout
- `skymap:meta:{dateobs}` &nbsp; HASH &nbsp; `{ alias, created_at, jd, tags, area_deg2, depth, n_pixels }`
- `skymap:idx:d{depth}:{ipix}` &nbsp; SET &nbsp; `dateobs` of every event covering that pixel
- `skymap:active:d{depth}` &nbsp; SET &nbsp; all `dateobs` currently indexed at this depth

## Lookup (alert -> skymaps)
```python
from astropy_healpix import HEALPix
import astropy.units as u

hp = HEALPix(nside=2**depth, order="nested")
ipix = int(hp.lonlat_to_healpix(ra * u.deg, dec * u.deg))
dateobs_list = r.smembers(f"skymap:idx:d{depth}:{ipix}")
```
One pixel hash + one `SMEMBERS` returns every skymap whose 95% region contains
the alert position.
