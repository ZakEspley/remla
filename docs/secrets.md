# Runtime secrets

Do not store passwords or tokens in Git-managed lab YAML. Reference a named
ReMLA secret instead:

```yaml
ASDIpdu:
  type: PDUOutlet
  password: ${secret:asdipdu-password}
```

Use root-only commands to create or rotate a secret:

```bash
sudo remla secrets set asdipdu-password
```

ReMLA stores each value at `/etc/remla/secrets/<name>`, root-owned and readable
by the `remla` group. This works in both foreground and systemd service mode.
`sudo remla secrets list` shows names only; `sudo remla secrets remove NAME`
removes one. After rotation, use `remla restart`. A missing reference stops startup
with the secret name but never prints its value. Do not commit, copy into a
development checkout, or include secret files in support bundles.
