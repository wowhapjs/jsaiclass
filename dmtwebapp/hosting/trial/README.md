# DMT WebApp — private trial

This is a standalone, local-only trial of the upload/build/version engine. It does not use the production roster, PostgreSQL, Caddy or the real jsaiclass site. It uses a separate SQLite database and a single trial student `0000`. The management port and preview port are distinct origins. It must not be exposed to the Internet or used as a multi-tenant production server.

## Start

On a computer with Python 3.10+ (Linux/macOS; the build lock uses `fcntl`), unpack the ZIP and run:

```sh
python3 server.py
```

Open `http://127.0.0.1:8765/`. Preview URLs use port 8766. Upload `samples/static-v1.zip`, `static-v2.zip` and `static-v3.zip` into the same app folder (e.g. `demo`). Select a service version, open its fixed URL, test another version without switching, restore an earlier version, and delete a non-live version. The example ZIPs have visible version numbers. Deletion is logical: the version stops being served, but its files are retained for administrative cleanup. New uploads are never automatically made live. The version counter never reuses a deleted number.

The local data is in `trial-data/`; do not use a production directory as `--data`. Use `python3 test_engine.py` to run the two automated tests. Browser interaction is not certified; the HTTP/API lifecycle tests are.

## FindOne / FinDone

`samples/findone.zip` is the original supplied archive, unchanged. Its manifest describes a Vite/React/TypeScript source project. It contains no prebuilt `dist` or package lock. The engine classifies it as browser storage; no backend DB dependency or backend entry was detected. To build, an operator needs a digest-pinned trusted Node Docker image with the necessary dependencies, or enables the optional isolated registry dependency acquisition mode.

```sh
# Operator only, NOT an Internet-facing worker. Use a verified image digest.
export DMT_TRIAL_ONLINE_DEPS=1
python3 server.py --image 'node@sha256:REPLACE_WITH_VERIFIED_64_HEX_DIGEST'
```

If an authorized operator uses sudo to access Docker, `DMT_TRIAL_DOCKER_SUDO=1` enables the fixed `sudo -n docker` command prefix. Do not grant general Docker access to students or run this service publicly. The engine restricts source manifests to ordinary registry semver ranges, performs dependency resolution without mounting student sources, disables lifecycle scripts, validates resolved registry locations/integrity, and executes the actual Vite build in a network-disabled, non-root container. The original ZIP is never served as web content. DB-bearing/unknown-backend projects are held for review. This does not provision external or per-app production databases.

## Production integration not included

Student identity/authorization, PostgreSQL migrations, credential storage, durable worker queue and recovery, cross-app origin isolation, DB adapter provisioning, backups and the existing site deployment runner must be integrated and tested before public student use. The trial has no login and is bound to loopback only. No real student phone numbers are included. Do not run student apps on the same origin as the student management API.
