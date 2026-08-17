# Remla

Remla is a portmanteau of Remote Labs. It is used to control physics laboratory equipment over the internet.

## MediaMTX

`sudo remla init` installs the latest MediaMTX release for the current Linux architecture. To update an existing installation later, run:

```bash
sudo remla mediamtx update
```

REMLA verifies the release checksum, installs the matching MediaMTX configuration, and restarts the service. The previous configuration is retained at `/usr/local/etc/mediamtx.yml.previous`.

The `cam` path uses MediaMTX's always-available H.264 mode. Camera switches restart Picamera2 and its RTSP publisher without closing the browser's existing WHEP connection.

For internet viewing, forward both UDP and TCP port `8189` to the Raspberry Pi or configure an appropriate TURN server. After updating on a Pi, verify a camera switch while watching the browser's WebRTC internals: the peer connection must remain the same while the video briefly changes to MediaMTX's offline segment and then resumes.
