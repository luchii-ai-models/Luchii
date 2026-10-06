// Frasberg API Keys authenticate users. x-owner-id is read-only context — never overridden.
export function resolveOwner(headers: Record<string, string | undefined>, keyOwnerId: string): string {
  const header = headers["x-owner-id"];
  if (header && header !== keyOwnerId) {
    throw Object.assign(new Error("x-owner-id does not match authenticated owner"), { status: 403 });
  }
  return keyOwnerId;
}
