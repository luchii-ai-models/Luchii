import 'dotenv/config';
import { createServer, type Server } from 'node:http';
import express from 'express';
import helmet from 'helmet';
import { MongoClient, type Db } from 'mongodb';
import { applyGatewayStack } from './middleware-stack';
import { MongoApiKeyStore } from '../../../packages/luchii-api-keys/mongo-api-key-store';
import { setApiKeyStore } from '../../../packages/luchii-api-keys/api-key-store';
import { getRedisClient } from '../../../packages/luchii-rate-limiter/redis-client';

export interface GatewayConfig {
  port: number;
  host: string;
  mongoUrl: string;
  dbName: string;
  redisUrl: string;
  upstreamUrl: string;
  upstreamApiKey: string;
  allowLegacyRawKeys: boolean;
  trustProxy: boolean | number;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): GatewayConfig {
  const required = ['MONGO_URL', 'DB_NAME', 'REDIS_URL', 'LUCHII_UPSTREAM_URL', 'LUCHII_UPSTREAM_API_KEY'];
  const missing = required.filter((name) => !env[name]?.trim());
  if (missing.length) throw new Error(`Missing required gateway configuration: ${missing.join(', ')}`);

  const upstream = new URL(env.LUCHII_UPSTREAM_URL!);
  if (upstream.protocol !== 'https:' && upstream.hostname !== 'localhost' && upstream.hostname !== '127.0.0.1') {
    throw new Error('LUCHII_UPSTREAM_URL must use HTTPS outside localhost');
  }
  if (!['true', 'false'].includes(env.ALLOW_LEGACY_RAW_API_KEYS ?? '')) {
    throw new Error('Set ALLOW_LEGACY_RAW_API_KEYS explicitly to true or false');
  }

  const port = Number(env.PORT ?? 4100);
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('PORT must be between 1 and 65535');

  const trustProxyValue = env.TRUST_PROXY ?? 'false';
  const trustProxy = trustProxyValue === 'true'
    ? true
    : trustProxyValue === 'false'
      ? false
      : Number(trustProxyValue);
  if (typeof trustProxy === 'number' && (!Number.isInteger(trustProxy) || trustProxy < 0)) {
    throw new Error('TRUST_PROXY must be true, false, or a non-negative hop count');
  }

  return {
    port,
    host: env.HOST ?? '0.0.0.0',
    mongoUrl: env.MONGO_URL!,
    dbName: env.DB_NAME!,
    redisUrl: env.REDIS_URL!,
    upstreamUrl: upstream.toString().replace(/\/$/, ''),
    upstreamApiKey: env.LUCHII_UPSTREAM_API_KEY!,
    allowLegacyRawKeys: env.ALLOW_LEGACY_RAW_API_KEYS === 'true',
    trustProxy,
  };
}

export async function startGateway(config = loadConfig()) {
  const mongo = new MongoClient(config.mongoUrl, {
    serverSelectionTimeoutMS: 5000,
    connectTimeoutMS: 5000,
    maxPoolSize: 50,
    appName: 'frasberg-luchii-gateway',
  });
  await mongo.connect();
  const db = mongo.db(config.dbName);
  await db.command({ ping: 1 });

  const keyStore = new MongoApiKeyStore(db.collection('api_keys'), {
    allowLegacyRawKeys: config.allowLegacyRawKeys,
  });
  await keyStore.ensureIndexes();
  setApiKeyStore(keyStore);

  process.env.REDIS_URL = config.redisUrl;
  const redis = getRedisClient();
  try {
    if (redis.status === 'wait') await redis.connect();
    await redis.ping();
  } catch {
    console.error('Redis unavailable at startup; public rate limiting is fail-open');
  }

  const app = express();
  app.disable('x-powered-by');
  app.set('trust proxy', config.trustProxy);
  app.use(helmet());
  app.get('/health/live', (_req, res) => res.status(200).json({ status: 'live' }));
  app.get('/health/ready', async (_req, res) => {
    let mongoReady = false;
    let redisReady = false;
    try {
      await db.command({ ping: 1 });
      mongoReady = true;
    } catch {}
    try {
      await redis.ping();
      redisReady = true;
    } catch {}
    const status = mongoReady ? 200 : 503;
    res.status(status).json({
      status: mongoReady && redisReady ? 'ready' : 'degraded',
      dependencies: { mongo: mongoReady, redis: redisReady },
    });
  });
  applyGatewayStack(app);

  const server = createServer(app);
  server.keepAliveTimeout = 65_000;
  server.headersTimeout = 66_000;
  await listen(server, config.port, config.host);
  console.info(`Luchii gateway listening on ${config.host}:${config.port}`);

  let closing: Promise<void> | undefined;
  const close = () => {
    if (!closing) {
      closing = (async () => {
        await closeServer(server);
        await mongo.close();
        if (redis.status === 'ready') await redis.quit();
        else redis.disconnect();
      })();
    }
    return closing;
  };
  process.once('SIGTERM', close);
  process.once('SIGINT', close);

  return { app, server, mongo, db, redis, close };
}

function listen(server: Server, port: number, host: string): Promise<void> {
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, host, () => {
      server.off('error', reject);
      resolve();
    });
  });
}

function closeServer(server: Server): Promise<void> {
  return new Promise((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
  });
}

if (process.env.RUN_GATEWAY === '1') {
  startGateway().catch((error: unknown) => {
    console.error('Gateway startup failed:', error instanceof Error ? error.message : 'unknown error');
    process.exitCode = 1;
  });
}
