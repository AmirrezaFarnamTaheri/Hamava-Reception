// Browser-only contract double. Never imported by the product or its build.
// Event names and ordering follow installed livekit-client 2.23.x.
export const RoomEvent = {
  ConnectionStateChanged: "connectionStateChanged",
  Reconnecting: "reconnecting",
  SignalReconnecting: "signalReconnecting",
  Reconnected: "reconnected",
  Disconnected: "disconnected",
  TrackSubscribed: "trackSubscribed",
  TrackUnsubscribed: "trackUnsubscribed",
  DataReceived: "dataReceived",
};
const harness = window.__rtcHarness;
export class Room {
  constructor() {
    this.handlers = new Map();
    this.state = "disconnected";
    this.options = harness.next;
    harness.next = {};
    this.deferMic = !!this.options.deferMic;
    this.pendingMic = false;
    this.disconnects = 0;
    this.micChanges = [];
    this.localParticipant = {
      isMicrophoneEnabled: false,
      setMicrophoneEnabled: async (enabled) => {
        this.micChanges.push(enabled);
        if (this.deferMic) {
          this.deferMic = false;
          this.pendingMic = true;
          await new Promise((resolve) => {
            this.releaseMic = resolve;
          });
          this.pendingMic = false;
        }
        this.localParticipant.isMicrophoneEnabled = enabled;
      },
    };
    harness.rooms.push(this);
  }
  on(name, handler) {
    const list = this.handlers.get(name) || [];
    list.push(handler);
    this.handlers.set(name, list);
    return this;
  }
  off(name, handler) {
    this.handlers.set(
      name,
      (this.handlers.get(name) || []).filter((item) => item !== handler),
    );
    return this;
  }
  emit(name, ...args) {
    for (const handler of this.handlers.get(name) || []) handler(...args);
  }
  transition(state, mode = "both") {
    this.state = state;
    if (mode !== "named") this.emit(RoomEvent.ConnectionStateChanged, state);
    if (mode !== "state") {
      const name = {
        reconnecting: RoomEvent.Reconnecting,
        signalReconnecting: RoomEvent.SignalReconnecting,
        connected: RoomEvent.Reconnected,
        disconnected: RoomEvent.Disconnected,
      }[state];
      if (name) this.emit(name);
    }
  }
  async connect() {
    this.transition("connecting", "state");
    await Promise.resolve();
    if (this.options.failConnect) {
      this.transition("disconnected");
      throw new Error("Intentional SDK-ordering contract failure");
    }
    this.transition("connected", "state");
  }
  async disconnect() {
    this.disconnects++;
    this.localParticipant.isMicrophoneEnabled = false;
    this.transition("disconnected");
  }
  emitRetiredDataAndTrack() {
    const participant = { identity: "agent-rtc-event-session" };
    this.emit(
      RoomEvent.DataReceived,
      new TextEncoder().encode(
        JSON.stringify({
          turn_id: "retired-room-packet",
          reply: "پیام اتاق بازنشسته",
          transcript: "متن اتاق بازنشسته",
          state: "INTENT",
        }),
      ),
      participant,
      undefined,
      "reception.turn",
    );
    this.emit(
      RoomEvent.TrackSubscribed,
      {
        kind: "audio",
        attach() {
          const node = document.createElement("audio");
          node.dataset.retiredRoom = "true";
          return node;
        },
      },
      {},
      participant,
    );
  }
}
