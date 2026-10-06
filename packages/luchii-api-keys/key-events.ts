import { EventEmitter } from 'node:events';

export type KeyEventType = 'created' | 'rotated' | 'revoked';

export interface KeyEvent {
  type: KeyEventType;
  keyId: string;
  ownerId: string;
  at: number;
}

export const keyEvents = new EventEmitter();

export function emitKeyEvent(type: KeyEventType, keyId: string, ownerId: string): KeyEvent {
  const event: KeyEvent = { type, keyId, ownerId, at: Date.now() };
  keyEvents.emit(type, event);
  keyEvents.emit('*', event);
  return event;
}
