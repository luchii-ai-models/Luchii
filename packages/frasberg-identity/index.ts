export interface Owner {
  id: string;
  email?: string;
}

export interface Workspace {
  id: string;
  ownerId: string;
}

export interface IdentityResolver {
  getOwner(ownerId: string): Promise<Owner | null>;
  getWorkspace(workspaceId: string): Promise<Workspace | null>;
}

export * from './owner-resolver';
export * from './workspace-resolver';
