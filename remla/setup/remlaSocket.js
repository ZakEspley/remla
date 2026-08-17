// Self-invoking function to encapsulate the WebSocket setup
(function() {
    function getWebSocketUrl() {
        const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
        const hostname = window.location.hostname;
        const pathname = window.location.pathname;
        const port = window.location.port ? `:${window.location.port}` : '';
        const wsPath = 'ws';
        return `${protocol}${hostname}${port}${pathname}${wsPath}`;
    }

    // Establish the WebSocket connection
    const url = getWebSocketUrl();
    const dataChannel = new WebSocket(url);

    function handleServerMessage(event) {
        const prefix = 'COMMAND: ';
        if (!event.data.startsWith(prefix)) return;
        const [command, switchId, state, pipelineMs, onlineMs] = event.data.slice(prefix.length).split('/');
        const eventNames = {
            cameraSwitchStarted: 'remla:camera-switch-started',
            cameraSwitchReady: 'remla:camera-switch-ready',
            cameraSwitchFailed: 'remla:camera-switch-failed',
        };
        if (eventNames[command]) {
            window.dispatchEvent(new CustomEvent(eventNames[command], {
                detail: {
                    switchId,
                    state,
                    pipelineMs: Number(pipelineMs),
                    onlineMs: Number(onlineMs),
                    readyMs: Number(onlineMs),
                    receivedAt: performance.now(),
                },
            }));
        }
    }

    // Make `dataChannel` accessible globally
    window.dataChannel = dataChannel;

    // Default handlers for WebSocket events
    dataChannel.onopen = function() {
        console.log('WebSocket connection established.');
    };
    dataChannel.onmessage = function(event) {
        handleServerMessage(event);
        console.log('Message from server:', event.data);
    };
    dataChannel.onerror = function(error) {
        console.error('WebSocket error:', error);
    };
    dataChannel.onclose = function(event) {
        console.log('WebSocket connection closed:', event.reason);
    };

    // Function to allow users to set custom event handlers
    window.setWebSocketHandlers = function(handlers) {
        if (handlers.onOpen) dataChannel.onopen = handlers.onOpen;
        if (handlers.onMessage) {
            dataChannel.onmessage = function(event) {
                handleServerMessage(event);
                handlers.onMessage(event);
            };
        }
        if (handlers.onError) dataChannel.onerror = handlers.onError;
        if (handlers.onClose) dataChannel.onclose = handlers.onClose;
    };
})();
