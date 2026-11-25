# DMT WebApp production
The student management origin is https://jsaiclass.duckdns.org/dmtwebapp/.
The stable /dmtwebapp/<student>/<app>/ address redirects to a unique app HTTPS origin.
The app origin is deliberately different from the management origin. Versions of the same app share browser data. Rollback switches code, not database data.

## Services
- dmtapi: local PostgreSQL peer login, function-only privileges; no Docker access.
- dmtworker: trusted serial worker; Docker access only in this service, not in student-facing API. Build containers run non-root, offline, with resource limits, no credentials or Docker socket.
- common: root-owned verified dependency directories keyed by exact manifests and image digest. Mount node_modules read-only; Vite temp directory per job. Identical ZIPs and public config reuse verified artifacts within the same app.
- Unknown dependencies require administrator cache review. Never install packages from untrusted uploaded scripts. The reviewed AI Studio manifest uses the cached React/Vite/Tailwind/Lucide profile; projects importing extra libraries need a compatible cached profile.
- Uploads are limited to 50 MiB, 250 MiB expanded and 5000 files. Logical deletions remove access, not retained disk data; admin cleanup required to reclaim quota. 512 MiB total reserved per student (including retained versions).
- Phone-only sign-in is not strong identity verification. Classroom use only; avoid sensitive information. No public roster. Sessions are secure host-only cookies, rate-limited and scoped by student.
- Only first successful build auto-activates; later versions require explicit selection. Public app URLs are public; version links may be shared.

## DB modes
Browser localStorage/IndexedDB work on the unique app origin. Supabase/Firebase public VITE_ variables are supported if their dependencies are in an approved cache. The external provider must allow the assigned origin and enforce RLS/security rules. Private service keys never belong in the ZIP or public build.
Managed mode provides browser-scoped persistent JSON records in PostgreSQL, independent of app code versions. The app must explicitly integrate:
  fetch('/__dmt_data', {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({op:'put',key:'tasks',value:[{title:'Demo'}]})})
  // op=get returns {value: ...}; op=delete removes key.
This is not an automatic adapter for arbitrary SQL, MongoDB, backend runtime or migrations. Arbitrary server code and private DB credentials require a separately reviewed service.

## Operations
Apply numbered SQL migrations as dmtwebapp_owner, with separate dmtapi and dmtworker LOGIN roles, granting CONNECT to only the relevant database. Use an isolated staging DB with synthetic students first. Install systemd units from this directory after the exact commit is deployed. The Caddy candidate generator must be validated and reviewed before reload. Keep previous Caddy config for rollback; it contains unrelated secrets and must not be printed or committed.
