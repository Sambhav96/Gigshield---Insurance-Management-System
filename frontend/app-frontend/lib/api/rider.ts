import { fetchApi } from "./client";
import { ApiResponse } from "./types";

export const riderService = {
  // Page: Home Dashboard
  getTelemetryMetrics: (): Promise<ApiResponse<any>> => fetchApi("/rider/me/telemetry"),
  getRiskOracles: (): Promise<ApiResponse<any[]>> => fetchApi("/rider/me/oracles"),
  
  // Page: Earnings
  getPayouts: (): Promise<ApiResponse<any[]>> => fetchApi("/rider/me/payouts"),
  requestWithdrawal: (amount: number): Promise<ApiResponse<any>> => fetchApi("/rider/me/payouts/withdraw", { method: "POST", body: JSON.stringify({ amount }) }),
  
  // Page: Shield
  getShieldStatus: (): Promise<ApiResponse<any>> => fetchApi("/rider/me/shield"),
  
  // Page: Activity
  getActivityLog: (): Promise<ApiResponse<any[]>> => fetchApi("/rider/me/activity")
};
