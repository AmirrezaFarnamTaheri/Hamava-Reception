import type { ConnectionState, Room, RoomEvent } from "livekit-client";

export type RtcStatus =
  | "idle"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "signalReconnecting"
  | "disconnected";

// Type-only imports keep the media SDK out of the initial application bundle.
export function observeRoomLifecycle(
  room: Room,
  events: typeof RoomEvent,
  isCurrent: () => boolean,
  onStatus: (status: RtcStatus) => void,
) {
  const report = (status: RtcStatus) => {
    if (isCurrent()) onStatus(status);
  };
  const changed = (status: ConnectionState) => report(status);
  const reconnecting = () => report("reconnecting");
  const signalReconnecting = () => report("signalReconnecting");
  const reconnected = () => report(room.state);
  const disconnected = () => report("disconnected");
  room.on(events.ConnectionStateChanged, changed);
  room.on(events.Reconnecting, reconnecting);
  room.on(events.SignalReconnecting, signalReconnecting);
  room.on(events.Reconnected, reconnected);
  room.on(events.Disconnected, disconnected);
  return () => {
    room.off(events.ConnectionStateChanged, changed);
    room.off(events.Reconnecting, reconnecting);
    room.off(events.SignalReconnecting, signalReconnecting);
    room.off(events.Reconnected, reconnected);
    room.off(events.Disconnected, disconnected);
  };
}

export const isRtcRecovering = (status: RtcStatus) =>
  status === "reconnecting" || status === "signalReconnecting";
export const isRtcActive = (status: RtcStatus) =>
  status === "connecting" || status === "connected" || isRtcRecovering(status);
