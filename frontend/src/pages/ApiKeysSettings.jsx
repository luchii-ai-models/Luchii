import { ApiKeyForge } from "../components/site/ApiKeyForge";
import { T } from "../lib/dashTheme";

export default function ApiKeysSettings() {
  return (
    <div className="mx-auto max-w-5xl px-4 py-10" style={{ color: T.text }} data-testid="api-keys-settings">
      <h1 className="mb-1 text-2xl font-semibold">API Keys</h1>
      <p className="mb-6 text-sm" style={{ color: T.muted }}>
        Create a key and choose what it can access: Luchii Chat, Vision, Music, GT6 Runtime, Agents, Memory and Checkout.
      </p>
      <ApiKeyForge />
    </div>
  );
}
