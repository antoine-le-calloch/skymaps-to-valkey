"""Populate Valkey/Redis with a meta-MOC index of recent GCN skymaps.

Fetches GCN events from SkyPortal over a configurable lookback window (default
7 days), builds a MOC at the chosen cumulative probability for each event, and
stores an inverted pixel -> events index in Valkey at a configurable HEALPix
depth. This is the dataset used to benchmark sub-millisecond crossmatch lookups.

Storage layout:
- skymap:meta:{dateobs}        HASH   (alias, created_at, jd, tags, type,
                                       area_deg2, depth, n_pixels)
- skymap:idx:d{depth}:{ipix}   SET    (dateobs of every event covering that pixel)
- skymap:active:d{depth}       SET    (all dateobs currently indexed at this depth)

Lookup of an alert at (ra, dec):
    ipix = HEALPix(nside=2**depth, order="nested").lonlat_to_healpix(ra, dec)
    SMEMBERS skymap:idx:d{depth}:{ipix}      -> list of matching dateobs
    HGETALL  skymap:meta:{dateobs}           -> event metadata
"""

import argparse
import json
import os
import sys
import time
import redis
from datetime import datetime, timedelta, UTC

from astropy.time import Time
from dotenv import load_dotenv

from skyportal import SkyPortal, APIError
from skymap import get_moc_from_fits, moc_to_pixels_at_depth, moc_area_deg2
from valkey import clear_skymap_keys


def pick_localization(event):
    """Pick the first localization tagged '< 1000 sq. deg.' (same rule as the
    Python crossmatch pipeline)."""
    for loc in event.get("localizations", []):
        if any(t.get("text") == "< 1000 sq. deg." for t in loc.get("tags", [])):
            return loc
    return None


def pick_alias(event):
    """Pick the first alias containing '#' (e.g. 'LVC#S250506x')."""
    return next((a for a in event.get("aliases", []) if "#" in a), None)


def store_skymap(r, depth, dateobs, alias, created_at, tags, jd, moc):
    pixels = moc_to_pixels_at_depth(moc, depth)
    area = moc_area_deg2(moc)

    pipe = r.pipeline(transaction=False)
    pipe.hset(
        f"skymap:meta:{dateobs}",
        mapping={
            "alias": alias or "",
            "created_at": created_at or "",
            "jd": f"{jd:.6f}",
            "tags": json.dumps(tags or []),
            "area_deg2": f"{area:.4f}",
            "depth": str(depth),
            "n_pixels": str(len(pixels)),
        },
    )
    pipe.sadd(f"skymap:active:d{depth}", dateobs)
    # Batch SADD per pixel; pipelined so one round-trip overall.
    for ipix in pixels:
        pipe.sadd(f"skymap:idx:d{depth}:{ipix}", dateobs)
    pipe.execute()
    return len(pixels), area


def main(args):
    skyportal_url = os.getenv("SKYPORTAL_URL")
    skyportal_key = os.getenv("SKYPORTAL_API_KEY")
    if not skyportal_url or not skyportal_key:
        sys.exit("SKYPORTAL_URL and SKYPORTAL_API_KEY must be set in the environment.")

    r = redis.Redis(
        host=os.getenv("VALKEY_HOST", "localhost"),
        port=int(os.getenv("VALKEY_PORT", "6379")),
        db=int(os.getenv("VALKEY_DB", "0")),
        decode_responses=True,
    )
    r.ping()

    if args.clear:
        n = clear_skymap_keys(r)
        print(f"Cleared {n} existing skymap:* keys.")

    sp = SkyPortal(skyportal_url, skyportal_key)
    start_date = datetime.now(UTC) - timedelta(days=args.days)
    print(f"Fetching GCN events since {start_date.isoformat()} ...")
    events = sp.get_gcn_events(start_date)
    print(f"  {len(events)} events returned by SkyPortal.")

    seen_dateobs = set()
    indexed = 0
    skipped_no_alias = 0
    skipped_no_loc = 0
    skipped_dup = 0

    t0 = time.time()
    for event in events:
        dateobs = event.get("dateobs")
        if dateobs in seen_dateobs:
            skipped_dup += 1
            continue
        seen_dateobs.add(dateobs)

        alias = pick_alias(event)
        if not alias:
            skipped_no_alias += 1
            continue

        loc = pick_localization(event)
        if loc is None:
            skipped_no_loc += 1
            continue

        try:
            fits_io = sp.download_localization(dateobs, loc["localization_name"])
            moc = get_moc_from_fits(fits_io, args.cumprob)
            jd = Time(dateobs).jd
            n_pix, area = store_skymap(
                r,
                args.depth,
                dateobs,
                alias,
                loc.get("created_at"),
                event.get("tags", []),
                jd,
                moc,
            )
            indexed += 1
            print(f"  [{indexed:3d}] {alias:30s} dateobs={dateobs} "
                  f"area={area:8.2f} deg^2  n_pix(d{args.depth})={n_pix}")
        except APIError as e:
            print(f"  ! API error for {alias} ({dateobs}): {e}")
        except Exception as e:
            print(f"  ! Failed to index {alias} ({dateobs}): {e}")

    dt = time.time() - t0
    print(
        f"\nDone in {dt:.1f}s. indexed={indexed} "
        f"skipped(no_alias={skipped_no_alias}, no_loc={skipped_no_loc}, dup={skipped_dup})"
    )
    print(f"Active skymaps at depth {args.depth}: "
          f"{r.scard(f'skymap:active:d{args.depth}')}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Populate Valkey with recent GCN skymap MOC indices.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--depth", type=int, default=6,
                   help="HEALPix NESTED order for the inverted index (e.g. 6 -> NSIDE=64).")
    parser.add_argument("--days", type=float, default=7.0,
                   help="Lookback window in days for GCN events.")
    parser.add_argument("--cumprob", type=float, default=0.95,
                   help="Cumulative probability threshold used to build each MOC.")
    parser.add_argument("--clear", action="store_true",
                   help="Delete all existing skymap:* keys before populating.")
    parser.add_argument("--env", default=".env",
                   help="Path to the .env file.")

    args = parser.parse_args()
    load_dotenv(args.env)

    main(args)
