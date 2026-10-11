# ReMLA 0.4.2

## Fixes

- Fixes `remla upgrade`: virtual environments are created at their final release
  path so console-script launchers do not retain a deleted staging path.

## Upgrade notes

- `v0.4.1` has a broken `remla upgrade` path. Upgrade affected Pi installations
  directly with the `v0.4.2` release installer, then use normal upgrades again.
