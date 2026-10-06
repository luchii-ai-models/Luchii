import { defineConfig } from 'vitest/config';
import { fileURLToPath } from 'node:url';

const p = (rel: string) => fileURLToPath(new URL(rel, import.meta.url));

export default defineConfig({
  resolve: {
    alias: {
      '@frasberg-core': p('./packages/frasberg-core'),
      '@frasberg-identity': p('./packages/frasberg-identity'),
      '@frasberg-memory': p('./packages/frasberg-memory'),
      '@frasberg-agents': p('./packages/frasberg-agents'),
      '@luchii-core': p('./packages/luchii-core'),
      '@luchii-api-keys': p('./packages/luchii-api-keys'),
      '@luchii-rate-limiter': p('./packages/luchii-rate-limiter'),
    },
  },
  test: {
    globals: true,
    include: ['packages/*/tests/**/*.test.ts', 'apps/*/tests/**/*.test.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'json-summary'],
      reportsDirectory: './coverage',
      include: ['packages/frasberg-core/**', 'packages/frasberg-identity/**', 'packages/luchii-rate-limiter/**'],
      exclude: ['**/tests/**', '**/*.d.ts', '**/index.ts', '**/error-types.ts'],
      thresholds: {
        'packages/frasberg-core/**': { statements: 90, branches: 85, functions: 90, lines: 90 },
      },
    },
  },
});
