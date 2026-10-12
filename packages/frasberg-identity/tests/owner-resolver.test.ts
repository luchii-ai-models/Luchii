import request from 'supertest';
import express from 'express';
import { ownerResolver } from '../owner-resolver';

describe('owner resolver', () => {
  const app = express();

  app.get('/owner', ownerResolver, (req, res) => {
    res.json({ ownerId: req.ownerId });
  });

  test('resolves owner', async () => {
    const response = await request(app).get('/owner').set('x-owner-id', 'owner_123');

    expect(response.body.ownerId).toBe('owner_123');
  });
});
