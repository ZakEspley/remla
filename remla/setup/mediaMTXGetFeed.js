const video = document.getElementById('video');

const message = document.getElementById('message');
let defaultControls = false;

const setMessage = (str) => {
  if (str !== '') {
    video.controls = false;
  } else {
    video.controls = defaultControls;
  }
  message.innerText = str;

};

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

const loadAttributesFromQuery = () => {

  const params = new URLSearchParams(window.location.search);
  video.controls = parseBoolString(params.get('controls'), false);
  video.muted = parseBoolString(params.get('muted'), true);
  video.autoplay = parseBoolString(params.get('autoplay'), true);
  video.playsInline = parseBoolString(params.get('playsinline'), true);

  defaultControls = video.controls;
};


window.addEventListener('DOMContentLoaded', () => {
  loadAttributesFromQuery();

  new MediaMTXWebRTCReader({
    url: new URL('whep', window.location.href) + window.location.search,
    onError: (err) => {
      setMessage(err);
    },
    onTrack: (evt) => {
      setMessage('');
      video.srcObject = evt.streams[0];
    },
  });
});
