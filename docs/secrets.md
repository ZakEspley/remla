# Runtime secrets

Do not store passwords or tokens in Git-managed lab YAML. Reference an explicit
ReMLA environment variable instead:

```yaml
ASDIpdu:
  type: PDUOutlet
  password: ${REMLA_ASDIPDU_PASSWORD}
```

Installed services read `/etc/remla/remla.env` through systemd. Create it with
root ownership and `0640` permissions readable by the `remla` group, for
example:

```ini
REMLA_ASDIPDU_PASSWORD=replace-with-current-password
```

After changing the file, restart `remla.service`. A missing referenced variable
stops startup with the variable name but never prints its value. Do not commit,
copy into a development checkout, or include this file in support bundles.
