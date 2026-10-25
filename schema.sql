CREATE TABLE IF NOT EXISTS proximity_events (
    event_id TEXT PRIMARY KEY,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    device_id INTEGER NOT NULL,
    peer_id INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    rssi_dbm INTEGER,
    payload JSONB
);
-- Compatible with the earlier six-column example table.
ALTER TABLE proximity_events ADD COLUMN IF NOT EXISTS payload JSONB;
CREATE INDEX IF NOT EXISTS proximity_events_received_idx
    ON proximity_events (received_at DESC);

-- Add columns used by the named-device history view, without deleting any data.
ALTER TABLE proximity_events
 ADD COLUMN IF NOT EXISTS state TEXT,
 ADD COLUMN IF NOT EXISTS boot_id BIGINT,
 ADD COLUMN IF NOT EXISTS sequence BIGINT,
 ADD COLUMN IF NOT EXISTS uptime_ms BIGINT;

CREATE TABLE IF NOT EXISTS devices (
 device_id INTEGER PRIMARY KEY,
 display_name TEXT NOT NULL CHECK (length(trim(display_name)) BETWEEN 1 AND 80),
 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE OR REPLACE VIEW proximity_history AS
SELECT e.event_id, e.received_at, e.device_id,
       d.display_name AS detected_by, e.peer_id,
       p.display_name AS other_person, e.event_type, e.state,
       e.rssi_dbm, e.boot_id, e.sequence, e.uptime_ms
FROM proximity_events e
LEFT JOIN devices d ON d.device_id=e.device_id
LEFT JOIN devices p ON p.device_id=e.peer_id;
