# Remote Labs

### Install Information

- We put a folder called `{{ remoteLabsDirectory }}`. Here is where you will put your lab configuration files and your websites for interacting with equipment.
- We created a remla folder in `{{ settingsDirectory }}`. This is mostly for remla's use, and you won't need to interact with it much. You will be able to find logs for mediamtx and nginx there if you should need to look at those.
- We turned on i2c for you. This is necessary if you are using an Arducam hat. If you'd like to turn it off, run `sudo rasp-config` and turn it off through the interface options menu.
- We made sure you had the dependent programs installed. Namely: `{{ packagesToCheck }}`
- We then downloaded [MediaMTX](https://github.com/bluenviron/mediamtx) `{{ mediamtxVersion }}` and moved the binary file to `{{ mediamtxBinaryLocation }}` and the settings file to `{{ mediamtxSettingsLocation }}` which you shouldn't need to touch. This program allows us to share the Raspberry Pi Camera feed to the browser via WebRTC. (If you want to change the camera settings, you can do that by editing the camera.conf file in ~/remla and then run `remla camera update`)
- It's important to note we have currently made a patch to get MediaMTX to work by creating a system link between libcamera.so.x.x and libcamera.so.0.0 as well as between libcamera-base.so=0.x.x and libcamera-base.so.0.0. We followed the instruction from [here](https://github.com/bluenviron/mediamtx/issues/2581#issuecomment-1804108215). In the future (>April 2024) this might cause an issue.

### Note
If you can't seem to reach the website you might be having a networking issue.
You should try one of the following:
- VNC to or use an HDMI cable to see your Pi's desktop. Open a browser and then go to http://localhost:8080 or http://127.0.0.1:8080
  - If that works then you have a networking issue that prevents you from seeing your pi. Check firewalls or contact IT.
- Check the logs mentioned above to see if something is wrong with NGINX.
