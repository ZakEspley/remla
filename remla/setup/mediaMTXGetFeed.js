const parseBoolString = (str, defaultVal) => {
  str = (str || '');

  if (['1', 'yes', 'true'].includes(str.toLowerCase())) {
    return true;
  }
  if (['0', 'no', 'false'].includes(str.toLowerCase())) {
    return false;
  }
  return defaultVal;
};



window.addEventListener('DOMContentLoaded', () => {

  let defaultControls = false;
  let reader = null;
  const video = document.getElementById('video');
  const message = document.getElementById('message');
  const videoContainer = video.parentElement;
  const frozenFrame = document.createElement('canvas');
  const switchStatus = document.createElement('div');
  let activeSwitch = null;
  let switchTimeout = null;
  let statusTimeout = null;

  if (window.getComputedStyle(videoContainer).position === 'static') {
    videoContainer.style.position = 'relative';
  }
  Object.assign(frozenFrame.style, {
    display: 'none',
    position: 'absolute',
    pointerEvents: 'none',
    objectFit: window.getComputedStyle(video).objectFit || 'contain',
    borderRadius: window.getComputedStyle(video).borderRadius,
    zIndex: '20',
  });
  Object.assign(switchStatus.style, {
    display: 'none',
    position: 'absolute',
    left: '50%',
    bottom: '12px',
    transform: 'translateX(-50%)',
    padding: '6px 10px',
    borderRadius: '4px',
    background: 'rgba(0, 0, 0, 0.72)',
    color: '#fff',
    font: '12px system-ui, sans-serif',
    pointerEvents: 'none',
    zIndex: '21',
  });
  videoContainer.appendChild(frozenFrame);
  videoContainer.appendChild(switchStatus);

  const positionSwitchOverlay = () => {
    frozenFrame.style.left = `${video.offsetLeft}px`;
    frozenFrame.style.top = `${video.offsetTop}px`;
    frozenFrame.style.width = `${video.offsetWidth}px`;
    frozenFrame.style.height = `${video.offsetHeight}px`;
  };

  const hideSwitchOverlay = () => {
    frozenFrame.style.display = 'none';
    switchStatus.style.display = 'none';
  };

  const waitForPresentedFrames = (count, callback) => {
    if (typeof video.requestVideoFrameCallback !== 'function') {
      window.setTimeout(callback, 100);
      return;
    }
    const waitForNext = () => {
      video.requestVideoFrameCallback(() => {
        count -= 1;
        if (count > 0) {
          waitForNext();
        } else {
          callback();
        }
      });
    };
    waitForNext();
  };

  window.addEventListener('remla:camera-switch-started', (event) => {
    const startedAt = event.detail.receivedAt;
    activeSwitch = { switchId: event.detail.switchId, startedAt };
    positionSwitchOverlay();
    if (video.videoWidth > 0 && video.videoHeight > 0) {
      frozenFrame.width = video.videoWidth;
      frozenFrame.height = video.videoHeight;
      frozenFrame.getContext('2d').drawImage(video, 0, 0, frozenFrame.width, frozenFrame.height);
      frozenFrame.style.display = 'block';
    }
    switchStatus.textContent = 'Switching camera...';
    switchStatus.style.display = 'block';
    window.clearTimeout(switchTimeout);
    window.clearTimeout(statusTimeout);
    switchTimeout = window.setTimeout(() => {
      if (activeSwitch?.switchId === event.detail.switchId) {
        hideSwitchOverlay();
        activeSwitch = null;
      }
    }, 15000);
  });

  window.addEventListener('remla:camera-switch-ready', (event) => {
    if (!activeSwitch || activeSwitch.switchId !== event.detail.switchId) return;
    const readyAt = event.detail.receivedAt;
    activeSwitch.readyAt = readyAt;
    waitForPresentedFrames(2, () => {
      if (!activeSwitch || activeSwitch.switchId !== event.detail.switchId) return;
      const displayedAt = performance.now();
      const timing = {
        switchId: event.detail.switchId,
        mediaState: event.detail.state,
        serverPipelineMs: event.detail.pipelineMs,
        serverReadyMs: event.detail.readyMs,
        serverOnlineMs: event.detail.state === 'online' ? event.detail.onlineMs : null,
        onlineMs: Math.round(readyAt - activeSwitch.startedAt),
        displayedMs: Math.round(displayedAt - activeSwitch.startedAt),
        browserMs: Math.round(displayedAt - readyAt),
        estimated: typeof video.requestVideoFrameCallback !== 'function',
      };
      console.info('REMLA camera switch timing', timing);
      hideSwitchOverlay();
      switchStatus.textContent = `Camera switched in ${timing.displayedMs} ms`;
      switchStatus.style.display = 'block';
      statusTimeout = window.setTimeout(() => {
        switchStatus.style.display = 'none';
      }, 1500);
      window.clearTimeout(switchTimeout);
      activeSwitch = null;
      window.dispatchEvent(new CustomEvent('remla:camera-switch-displayed', { detail: timing }));
    });
  });

  window.addEventListener('remla:camera-switch-failed', (event) => {
    if (!activeSwitch || activeSwitch.switchId !== event.detail.switchId) return;
    switchStatus.textContent = event.detail.state === 'timeout'
      ? 'Camera switched, but the live feed is still offline'
      : 'Camera switch failed';
    switchStatus.style.display = 'block';
    window.clearTimeout(switchTimeout);
    switchTimeout = window.setTimeout(hideSwitchOverlay, 2000);
    activeSwitch = null;
  });

  window.addEventListener('resize', positionSwitchOverlay);
  const setMessage = (str) => {
    if (str !== '') {
      video.controls = false;
    } else {
      video.controls = defaultControls;
    }
    message.innerText = str;
  };

  const loadAttributesFromQuery = () => {
    const params = new URLSearchParams(window.location.search);
    video.controls = parseBoolString(params.get('controls'), false);
    video.muted = parseBoolString(params.get('muted'), true);
    video.autoplay = parseBoolString(params.get('autoplay'), true);
    video.playsInline = parseBoolString(params.get('playsinline'), true);

    defaultControls = video.controls;
  };

  const getWhepUrl = () => {
    const url = new URL('whep', window.location.href);
    const params = new URLSearchParams(window.location.search);
    params.set('remla_reload', Date.now().toString());
    url.search = params.toString();
    return url.toString();
  };

  loadAttributesFromQuery();

  const startCameraFeed = () => {
    if (reader !== null) {
      reader.close();
      reader = null;
    }

    video.srcObject = null;
    setMessage('Reconnecting camera feed...');

    reader = new MediaMTXWebRTCReader({
      url: getWhepUrl(),
      onError: (err) => {
        setMessage(err);
      },
      onTrack: (evt) => {
        setMessage('');
        video.srcObject = evt.streams[0];
      },
    });
  };

  window.restartCameraFeed = startCameraFeed;

  startCameraFeed();
});
