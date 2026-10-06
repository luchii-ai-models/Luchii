import { GatewayError } from './api-key';

export const PERMISSIONS = [
  'chat.generate',
  'image.generate',
  'vision.generate',
  'music.generate',
  'gt6.run',
  'memory.read',
  'memory.write',
  'agents.execute',
  'checkout.access',
] as const;
export type Permission = (typeof PERMISSIONS)[number];

export function hasPermission(granted: string[], required: string): boolean {
  if (granted.includes('*') || granted.includes(required)) return true;
  const alias = required === 'vision.generate' ? 'image.generate' : undefined;
  return alias ? granted.includes(alias) : false;
}

export function assertPermission(granted: string[], required: string): void {
  if (!hasPermission(granted, required)) throw new GatewayError('PERMISSION_DENIED', { required });
}
