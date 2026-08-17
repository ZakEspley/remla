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
  window.addEventListener('remla:camera-feed-reload', startCameraFeed);

  startCameraFeed();
});
