import type { Collection, Document } from 'mongodb';
import { hashApiKey } from './api-key-hash';
import type { ApiKey, ApiKeyStatus } from './api-key';
import type { ApiKeyStore } from './api-key-store';

const LEGACY_PERMISSION_MAP: Record<string, string> = {
  music_generation: 'music.generate',
  frasberg_agents: 'agents.execute',
  image_generation: 'image.generate',
  vision_generation: 'vision.generate',
};

type KeyDocument = Document & {
  id?: string;
  user_id?: string;
  ownerId?: string;
  workspace_id?: string;
  workspaceId?: string;
  workspace_name?: string;
  key?: string;
  key_hash?: string;
  hash?: string;
  name?: string;
  status?: string;
  suspended?: boolean;
  expires_at?: string | number | Date | null;
  permissions?: string[] | Record<string, string>;
  requestsToday?: number;
  request_count?: number;
  createdAt?: number;
  created?: string | number | Date;
};

export interface MongoApiKeyStoreOptions {
  allowLegacyRawKeys?: boolean;
}

export class MongoApiKeyStore implements ApiKeyStore {
  constructor(
    private readonly collection: Collection<Document>,
    private readonly options: MongoApiKeyStoreOptions = {},
  ) {}

  async ensureIndexes(): Promise<void> {
    await this.collection.createIndex({ key_hash: 1 }, { unique: true, sparse: true, name: 'api_key_hash_unique' });
    await this.collection.createIndex({ id: 1 }, { unique: true, sparse: true, name: 'api_key_id_unique' });
  }

  async findByHash(hash: string, legacyRaw?: string): Promise<ApiKey | null> {
    const clauses: Document[] = [{ key_hash: hash }, { hash }];
    if (this.options.allowLegacyRawKeys && legacyRaw?.startsWith('frb_live_')) {
      clauses.push({ key: legacyRaw });
    }

    const document = (await this.collection.findOne({ $or: clauses })) as KeyDocument | null;
    return document ? this.toApiKey(document) : null;
  }

  async findById(id: string): Promise<ApiKey | null> {
    const document = (await this.collection.findOne({ id })) as KeyDocument | null;
    return document ? this.toApiKey(document) : null;
  }

  async save(key: ApiKey): Promise<void> {
    await this.collection.updateOne(
      { id: key.id },
      {
        $set: {
          id: key.id,
          ownerId: key.ownerId,
          workspace_id: key.workspaceId,
          name: key.name,
          key_hash: key.hash,
          status: key.status,
          permissions: key.permissions,
          requestsToday: key.requestsToday,
          createdAt: key.createdAt,
        },
      },
      { upsert: true },
    );
  }

  private toApiKey(document: KeyDocument): ApiKey {
    const id = String(document.id ?? '');
    const ownerId = String(document.ownerId ?? document.user_id ?? '');
    const workspaceId = String(
      document.workspace_id ?? document.workspaceId ?? `ws_${hashApiKey(id || ownerId).slice(0, 24)}`,
    );
    const expiry = document.expires_at ? new Date(document.expires_at).getTime() : undefined;
    let status: ApiKeyStatus = document.status === 'suspended' || document.suspended ? 'suspended' : 'active';
    if (document.status === 'disabled' || document.status === 'revoked' || (expiry !== undefined && expiry <= Date.now())) {
      status = 'disabled';
    }

    const isLegacyKey = typeof document.key === 'string' && !document.key_hash && !document.hash;
    const permissions = Array.isArray(document.permissions)
      ? document.permissions
      : Object.entries(document.permissions ?? {}).flatMap(([permission, level]) => {
          if (!level || level === 'no_access') return [];
          return [LEGACY_PERMISSION_MAP[permission] ?? permission];
        });
    if (isLegacyKey && !permissions.includes('chat.generate')) permissions.push('chat.generate');

    const createdAt = document.createdAt ?? (document.created ? new Date(document.created).getTime() : Date.now());
    return {
      id,
      ownerId,
      workspaceId,
      name: String(document.name ?? 'API key'),
      hash: String(document.key_hash ?? document.hash ?? (document.key ? hashApiKey(document.key) : '')),
      status,
      permissions,
      requestsToday: Number(document.requestsToday ?? document.request_count ?? 0),
      createdAt: Number.isFinite(createdAt) ? Number(createdAt) : Date.now(),
    };
  }
}
