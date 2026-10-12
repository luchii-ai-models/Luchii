import { randomBytes } from 'node:crypto';
import { hashApiKey } from './api-key-hash';

// The raw key is shown to the user once; only the sha256 hash is stored.
export function generateApiKey() {
  const raw = 'luc_live_' + randomBytes(32).toString('hex');
  return { raw, hash: hashApiKey(raw), prefix: raw.slice(0, 12) };
}
