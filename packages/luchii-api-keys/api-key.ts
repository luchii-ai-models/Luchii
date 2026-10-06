export interface ApiKey {
  id: string;
  ownerId: string;
  workspaceId: string;
  name: string;
  hash: string;
  status:
    | "active"
    | "disabled"
    | "suspended";
  permissions: string[];
  requestsToday: number;
  createdAt: number;
}
