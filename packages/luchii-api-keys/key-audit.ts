import { keyEvents, type KeyEvent } from './key-events';

export interface KeyAuditSink {
  write(event: KeyEvent): void | Promise<void>;
}

// Subscribes the sink to every key lifecycle event; returns an unsubscribe function.
export function auditKeyEvents(sink: KeyAuditSink): () => void {
  const handler = (event: KeyEvent) => void sink.write(event);
  keyEvents.on('*', handler);
  return () => keyEvents.off('*', handler);
}
