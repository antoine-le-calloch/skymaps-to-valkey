import numpy as np
import astropy.units as u
from astropy.io import fits
from astropy_healpix import HEALPix
from mocpy import MOC


def get_moc_from_fits(bytes_io, cumulative_probability):
    """Extract a MOC from a FITS HEALPix skymap at the given cumulative probability.
    Identical logic to crossmatch-alert-to-skymaps/utils/skymap.py.
    """
    with fits.open(bytes_io) as hdul:
        data = hdul[1].data
        columns = [col.name for col in hdul[1].columns]
        header = hdul[1].header

    if "UNIQ" in columns:
        uniq = data["UNIQ"]
        probdensity = data["PROBDENSITY"]
        orders = (np.log2(uniq // 4)) // 2
        area = np.pi / (3 * 4 ** orders) * u.sr
        prob = probdensity * area
    else:
        prob_col = next(c for c in columns if c in ("PROB", "PROBABILITY", "PROBDENSITY"))
        prob = np.ravel(data[prob_col])
        npix = len(prob)
        nside = int(np.sqrt(npix / 12))
        order = int(np.log2(nside))

        ordering = header.get("ORDERING", "NESTED").upper()
        if ordering == "RING":
            ring_hp = HEALPix(nside=nside, order="ring")
            nested_hp = HEALPix(nside=nside, order="nested")
            lon, lat = ring_hp.healpix_to_lonlat(np.arange(npix))
            nested_indices = nested_hp.lonlat_to_healpix(lon, lat)
            reordered = np.empty(npix)
            reordered[nested_indices] = prob
            prob = reordered

        indices = np.arange(npix)
        uniq = 4 * (4 ** order) + indices

    return MOC.from_valued_healpix_cells(uniq, prob, 29, cumul_to=cumulative_probability)


def moc_to_pixels_at_depth(moc, depth):
    """Return the list of NESTED HEALPix pixel indices at the given depth that
    overlap the MOC. Used to build the inverted index (pixel -> events).
    """
    nside = 2 ** depth
    hp = HEALPix(nside=nside, order="nested")
    npix = hp.npix

    chunk = 1_000_000
    covered = []
    for start in range(0, npix, chunk):
        end = min(start + chunk, npix)
        idx = np.arange(start, end)
        lon, lat = hp.healpix_to_lonlat(idx)
        mask = moc.contains_lonlat(lon, lat)
        if np.any(mask):
            covered.extend(idx[mask].tolist())
    return covered


def moc_area_deg2(moc):
    """Total sky area covered by the MOC in square degrees."""
    return float(moc.sky_fraction * 4 * np.pi * (180.0 / np.pi) ** 2)
