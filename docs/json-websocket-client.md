# JSON WebSocket client example

Copy `remla/setup/remlaJsonSocket.js` into a custom lab website. It negotiates
`remla-json-v1`, correlates command results, and exposes state, queue, fault,
and reconnect-gap handlers without a framework.

```html
<script src="remlaJsonSocket.js"></script>
<script>
const remla = new RemlaJsonSocket({
  handlers: {
    onSnapshot: (state) => render(state.devices),
    onStateChange: (change) => updateDevices(change.devices),
    onQueue: (queue) => showQueue(queue),
    onFault: (fault) => showFault(fault),
    onResyncRequired: () => location.reload(),
  },
});
remla.connect();

function laserOn() {
  remla.command("Laser", "power_on").catch(showCommandError);
}
</script>
```

Use explicit `power_on` and `power_off` when the desired result is known.
`power_toggle` reads provider state and should only be used when an intentional
state reversal is desired. The client does not replace legacy `remlaSocket.js`;
use one protocol client per page during migration.
