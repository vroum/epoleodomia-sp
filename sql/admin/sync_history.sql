-- Forward-only journal, independent of the frozen TEE migration ledger.
-- Executed transactionally by setup_sync_history.py; never replays JSON logs.
CREATE TABLE epol_meta.sync_history_config (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    version integer NOT NULL CHECK (version = 1),
    started_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO epol_meta.sync_history_config(version) VALUES (1);
CREATE TABLE epol_meta.sync_history_runs (
    id uuid PRIMARY KEY,
    started_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    completed_at timestamptz,
    mode text NOT NULL CHECK (mode IN ('tee','ktima','ydro','all')),
    status text NOT NULL CHECK (status IN ('collecting','committed','failed','commit_unknown')),
    audit_id integer,
    error_message text
);
CREATE INDEX sync_history_runs_time ON epol_meta.sync_history_runs(started_at DESC);
CREATE TABLE epol_meta.sync_history_layers (
    run_id uuid NOT NULL REFERENCES epol_meta.sync_history_runs(id),
    domain text NOT NULL CHECK (domain IN ('tee','ktima','ydro')),
    table_name text NOT NULL,
    source_records integer NOT NULL CHECK (source_records >= 0),
    new_count integer NOT NULL CHECK (new_count >= 0),
    updated_count integer NOT NULL CHECK (updated_count >= 0),
    removed_count integer NOT NULL CHECK (removed_count >= 0),
    unchanged_count integer NOT NULL CHECK (unchanged_count >= 0),
    geometry_count integer NOT NULL CHECK (geometry_count >= 0 AND geometry_count <= updated_count),
    source_id_count integer NOT NULL CHECK (source_id_count >= 0),
    PRIMARY KEY (run_id, domain, table_name)
);
CREATE TABLE epol_meta.sync_history_changes (
    id bigserial PRIMARY KEY,
    run_id uuid NOT NULL,
    domain text NOT NULL,
    table_name text NOT NULL,
    record_key jsonb NOT NULL,
    change_type text NOT NULL CHECK (change_type IN ('new','updated','removed','source_id')),
    changed_fields text[] NOT NULL,
    old_values jsonb,
    new_values jsonb,
    geometry_changed boolean NOT NULL,
    old_geom geometry(Geometry,2100),
    new_geom geometry(Geometry,2100),
    old_source_id text,
    new_source_id text,
    FOREIGN KEY (run_id, domain, table_name)
        REFERENCES epol_meta.sync_history_layers(run_id, domain, table_name)
        DEFERRABLE INITIALLY DEFERRED,
    UNIQUE (run_id, domain, table_name, record_key)
);
CREATE INDEX sync_history_changes_layer ON epol_meta.sync_history_changes(run_id,domain,table_name,id);
