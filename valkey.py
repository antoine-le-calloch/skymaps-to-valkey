def clear_skymap_keys(r):
    """Delete all skymap:* keys (uses SCAN to avoid blocking)."""
    n = 0
    cursor = 0
    while True:
        cursor, keys = r.scan(cursor=cursor, match="skymap:*", count=1000)
        if keys:
            r.delete(*keys)
            n += len(keys)
        if cursor == 0:
            break
    return n