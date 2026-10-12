export const FRASBERG_PLATFORM = "frasberg";
export interface Owner {
  id: string;
  email: string;
  plan: string;
}
export interface Workspace {
  id: string;
  ownerId: string;
  name: string;
}
