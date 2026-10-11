# ReMLA 0.4.1

## Fixes

- JSON WebSocket clients now generate message IDs when browsers do not support
  `crypto.randomUUID()`, preserving compatibility with older browsers.

## Upgrade notes

- Redeploy the lab website after upgrading so it receives the refreshed
  `remlaJsonSocket.js` client.
- Do not use `remla upgrade` to install this release: its staging install can
  leave console launchers pointing at a removed temporary path. Use `v0.4.2`.
