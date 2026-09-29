class RemlaJsonSocket {
    constructor(options = {}) {
        this.url = options.url || this.defaultUrl();
        this.version = "1.0.0";
        this.handlers = options.handlers || {};
        this.pending = new Map();
        this.revision = null;
        this.socket = null;
    }

    defaultUrl() {
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        return `${protocol}//${window.location.host}${window.location.pathname}ws`;
    }

    connect() {
        this.socket = new WebSocket(this.url, "remla-json-v1");
        this.socket.onopen = () => {
            if (this.socket.protocol !== "remla-json-v1") {
                this.socket.close();
                this.handlers.onError?.(new Error("ReMLA JSON protocol was not negotiated"));
                return;
            }
            this.handlers.onOpen?.();
        };
        this.socket.onmessage = (event) => this.receive(event.data);
        this.socket.onerror = () => this.handlers.onError?.(new Error("ReMLA WebSocket error"));
        this.socket.onclose = (event) => this.handlers.onClose?.(event);
    }

    command(deviceName, commandName, parameters = {}) {
        if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
            return Promise.reject(new Error("ReMLA WebSocket is not open"));
        }
        const messageId = crypto.randomUUID();
        const frame = {
            meta: { timestamp: new Date().toISOString(), version: this.version, messageId, replyId: null },
            type: "command",
            payload: { deviceName, commandName, parameters },
        };
        return new Promise((resolve, reject) => {
            this.pending.set(messageId, { resolve, reject });
            this.socket.send(JSON.stringify(frame));
        });
    }

    receive(rawFrame) {
        let frame;
        try {
            frame = JSON.parse(rawFrame);
        } catch {
            this.handlers.onError?.(new Error("ReMLA sent invalid JSON"));
            return;
        }
        if (frame.type === "result") {
            const pending = this.pending.get(frame.meta.replyId);
            if (pending) {
                this.pending.delete(frame.meta.replyId);
                frame.payload.ok ? pending.resolve(frame.payload) : pending.reject(frame.payload.error);
            }
            this.handlers.onResult?.(frame.payload, frame.meta);
            return;
        }
        if (frame.type !== "event") return;
        const { name, data } = frame.payload;
        if (name === "state.snapshot") {
            this.revision = data.revision;
            this.handlers.onSnapshot?.(data);
        } else if (name === "state.changed") {
            if (this.revision !== null && data.revision !== this.revision + 1) {
                this.handlers.onResyncRequired?.(this.revision, data.revision);
                return;
            }
            this.revision = data.revision;
            this.handlers.onStateChange?.(data);
        } else if (name === "ownership.queue") {
            this.handlers.onQueue?.(data);
        } else if (name === "fault") {
            this.handlers.onFault?.(data);
        }
        this.handlers.onEvent?.(name, data, frame.meta);
    }
}

window.RemlaJsonSocket = RemlaJsonSocket;
