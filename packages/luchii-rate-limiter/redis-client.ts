import Redis from 'ioredis';

let client: Redis | undefined;

export function getRedisClient(): Redis {
	if (client) return client;
	const url = process.env.REDIS_URL;
	if (!url) throw new Error('REDIS_URL is required');
	client = new Redis(url, { lazyConnect: true, maxRetriesPerRequest: 1, enableOfflineQueue: false });
	return client;
}

export const redis = {
	incr: (key: string) => getRedisClient().incr(key),
	expire: (key: string, seconds: number) => getRedisClient().expire(key, seconds),
	eval: (script: string, numKeys: number, ...args: Array<string | number>) => getRedisClient().eval(script, numKeys, ...args),
};
