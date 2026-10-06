export interface CheckoutSession {
  id: string;
  ownerId: string;
  planId: string;
  status: "open" | "complete" | "expired";
  createdAt: number;
}
