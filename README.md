# HackTX ESP proximity backend

ESP 1 --ESP-NOW--> ESP 2 --phone hotspot / HTTPS--> this API --PostgreSQL--> Tiger Data.
This package is backend source, not a deployed server. It does not send phone popups.
Use it with HackTXProximity.ino; keep INCLUDE_NAMES_IN_POST=false. Python 3.11+ recommended.

## 1. Create the Tiger Data database

Open https://console.cloud.tigerdata.com/ and choose New service. Create a development
service, select compute/region suitable for the demo, and save the downloaded
credentials privately. Wait for Ready. Copy the full PostgreSQL service connection
URL from its connection information, including its nonstandard port if supplied.
It resembles postgresql://USER:PASSWORD@HOST:PORT/tsdb?sslmode=require.
Use the real supplied values; do not copy those placeholders. A password embedded
in a URL must be URL-encoded if it contains reserved characters. The provider's
ready-made URL is preferable. Do not place this URL in the ESP or GitHub repository.

Use SQL Editor to run SELECT CURRENT_DATE; as a first connection test.
The backend automatically creates proximity_events on startup using schema.sql.
It can also extend the earlier sample table by adding the payload column without
removing its records. This is a normal PostgreSQL table on Tiger Data; no hypertable
conversion is needed for this small event dataset. SQL Editor can show stored rows.

## 2. Generate an API token

Run locally:

    python3 -c "import secrets; print(secrets.token_hex(32))"

Keep the generated token. The SAME token goes into server INGEST_TOKEN and firmware
API_TOKEN. It is separate from the database password and any Tiger Data management
API key. Do not publish the populated firmware or real environment variables.

## 3. Deploy the API (Render example)

Create a GitHub repository and upload the CONTENTS of this folder to the repository
root: main.py, schema.sql, requirements.txt, README.md, test_event.json, .gitignore.
Do not upload database credentials. The three required runtime files must be in the
same directory. No frontend or additional database on Render is required.

In https://dashboard.render.com/ choose New -> Web Service, connect that repository,
and use:

- Language/runtime: Python 3
- Build command: pip install -r requirements.txt
- Start command: uvicorn main:app --host 0.0.0.0 --port $PORT
- Health check: /health
- Environment DATABASE_URL: the full Tiger Data PostgreSQL connection URL
- Environment INGEST_TOKEN: the generated token, at least 32 characters

Set the environment variables before deployment starts. Choose a service plan after
reviewing its current terms. Hosting that sleeps when idle can delay the first upload;
the firmware retries. Startup must be able to reach Tiger Data over the supplied port.
If you configured database IP restrictions, allow the backend hosting service's
outbound IP ranges. Never replace this with an incorrect port such as 5432 by guess.

Deploy. The public base URL will look like https://YOUR-SERVICE.onrender.com.
The API's receiving URL is that base URL plus /events. The hosting service handles
incoming HTTPS; Uvicorn binds the internal HTTP port provided by the host.

## 4. Test WITHOUT the ESP using your browser

1. Open https://YOUR-SERVICE.onrender.com/health. Expect {"status":"ok"}.
   This is process health; successful deployment checks DB initialization, but
   the /health route does not continuously query the DB.
2. Open https://YOUR-SERVICE.onrender.com/docs.
3. Click Authorize. Paste INGEST_TOKEN (the token alone, without the word Bearer).
4. Expand POST /events -> Try it out. Use the provided example or test_event.json.
   Leave Idempotency-Key blank, or set it to the body's event_id.
5. Click Execute. Expect HTTP 200 with ok=true and duplicate=false.
6. Execute the EXACT same event again. Expect duplicate=true; only one row exists.
7. Expand GET /events -> Try it out -> Execute to see stored records.

You can also run from this folder (replace placeholders; keep your token private):

    curl -X POST 'https://YOUR-SERVICE.onrender.com/events' \
      -H 'Content-Type: application/json' \
      -H 'Authorization: Bearer YOUR_INGEST_TOKEN' \
      --data-binary @test_event.json

Verify in Tiger Data SQL Editor:

    SELECT event_id, received_at, device_id, peer_id, event_type, rssi_dbm, payload
    FROM proximity_events
    ORDER BY received_at DESC
    LIMIT 20;

The firmware boot ID, sequence, uptime, and state are stored in dedicated columns and in payload JSONB. Names are joined from devices by proximity_history. Register device IDs 1 and 2 in devices before testing; this backend never overwrites the owner names.
received_at is server receipt time, not the time an offline event originally occurred.
The backend responds successfully only after PostgreSQL commits the transaction.
A duplicate ID with different content returns 409 rather than silently overwriting.

## 5. Configure ESP 2 and test the full path

In the hotspot firmware set NODE_ID=2 and fill HOTSPOT_SSID, HOTSPOT_PASSWORD,
SERVER_URL="https://YOUR-SERVICE.onrender.com/events", and API_TOKEN with the SAME
ingestion token. The hotspot must offer 2.4 GHz connectivity.

Also fill ROOT_CA with the PEM root CA that validates your deployed API's HTTPS
certificate. This is NOT the Tiger Data database certificate. Inspect the API host's
certificate chain in your browser, identify its root CA, and obtain that root's PEM
from the certificate authority's official site. Paste the complete public certificate,
including BEGIN CERTIFICATE and END CERTIFICATE lines, into the firmware's raw PEM
string. Do not substitute the leaf/site certificate or disable TLS verification.
If unsure, share only the public deployed API URL to identify its root CA.

Flash ESP 2; flash ESP 1 with NODE_ID=1 using the same GROUP_ID and hotspot firmware.
Open ESP 2 Serial Monitor at 115200. Wait for HOTSPOT connected. Firmware needs NTP
clock sync before TLS. Send t to queue a test event. Expect POST accepted: HTTP 200.
Refresh SQL Editor / GET /events; find the NEW firmware-generated event_id. Moving
the boards together/apart adds peer_near / peer_far events after threshold dwell.
Only gateway measurements are uploaded. The LED shows proximity, not upload success.

## Troubleshooting

- Server fails startup: missing/short INGEST_TOKEN, wrong DATABASE_URL, blocked DB
  network access, unavailable DB, or insufficient permission to create/alter table.
- HTTP 401: API_TOKEN does not match INGEST_TOKEN.
- HTTP 404: SERVER_URL must end exactly in /events, not /docs or /events/.
- HTTP 422: request fields or types do not match the schema shown in /docs.
- HTTP 409: same event_id was reused for different content; give a NEW manual test
  a new event_id. Do not change IDs when retrying an unchanged event.
- HTTP 503: database is unavailable; firmware retries with the same event ID.
- ESP upload paused: SERVER_URL or ROOT_CA not configured.
- ESP negative HTTP code: check internet, TLS root CA, clock sync, DNS, and host status.
- No POST yet: offline/failed events are processed oldest first; uploads may be queued.
- Browser test succeeds but no ESP rows: compare exact endpoint/token, certificate,
  Serial Monitor output, hotspot band, and that NODE_ID=2 was flashed on the gateway.

This bundle has received Python syntax checks. Real database transactions, hosting deployment, and ESP HTTPS traffic have not been tested here. Perform the browser test before the hardware test.

## References

https://www.tigerdata.com/docs/get-started/quickstart/create-service
https://www.tigerdata.com/docs/integrate/find-connection-details
https://render.com/docs/deploy-fastapi
https://render.com/docs/configure-environment-variables
https://www.psycopg.org/psycopg3/docs/basic/usage.html
