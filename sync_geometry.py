"""Batched, full-precision spatial comparisons for tracked source records."""

from psycopg2.extras import execute_values


def geometry_changes(cur, pairs, srid=2100):
    """Return {objectid: changed} for (objectid, old_EWKB, new_WKT) pairs.

    ST_Equals compares the occupied 2D space without a distance tolerance.
    Ring direction, vertex order and redundant collinear vertices alone are
    unchanged. NULL transitions count as changes. Old geometry travels as EWKB
    so decimal formatting cannot discard stored coordinate precision.

    This is a VALUES-only SELECT: it does not read or modify database tables.
    Comparison failures propagate to the caller's load transaction.
    """
    if not pairs:
        return {}
    sql = f"""
        SELECT p.objectid,
               CASE
                   WHEN p.old_geom IS NULL AND p.new_wkt IS NULL THEN FALSE
                   WHEN p.old_geom IS NULL OR p.new_wkt IS NULL THEN TRUE
                   ELSE NOT ST_Equals(
                       ST_GeomFromEWKB(p.old_geom::bytea),
                       ST_GeomFromText(p.new_wkt::text, {int(srid)}))
               END AS changed
        FROM (VALUES %s) AS p(objectid, old_geom, new_wkt)
    """
    return dict(execute_values(cur, sql, pairs, page_size=500, fetch=True))
