import request from 'supertest';
import express from 'express';
import { apiKeyMiddleware } from '../api-key-middleware';

describe('api key middleware', () => {
  const app = express();

  app.get('/test', apiKeyMiddleware, (_, res) => res.json({ success: true }));

  test('returns 401 when missing key', async () => {
    const response = await request(app).get('/test');

    expect(response.status).toBe(401);
    expect(response.body.error.code).toBe('KEY_NOT_PROVIDED');
  });
});
