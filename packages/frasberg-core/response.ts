export interface SuccessResponse<T> {
  success: true;
  requestId: string;
  data: T;
}

export function successResponse<T>(requestId: string, data: T): SuccessResponse<T> {
  return { success: true, requestId, data };
}
