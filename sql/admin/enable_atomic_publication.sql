-- One additional data privilege for the existing restricted sync role.
-- DELETE/INSERT preserves old reader snapshots when replacing duplicate-ID lots.
-- No role creation, password reset, ownership, schema or data change.
GRANT DELETE ON epoleodomia.building_regs_lot TO epol_sync;
