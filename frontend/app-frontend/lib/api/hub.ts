import { fetchApi } from "./client";
import { ApiResponse } from "./types";

export const hubService = {
  // Page: Dashboard
  getLiveTerminalMetrics: (): Promise<ApiResponse<any>> => fetchApi("/hub/metrics"),
  
  // Page: Fleet Coverage
  getFleetCoverageMatrix: (): Promise<ApiResponse<any[]>> => fetchApi("/hub/fleet"),
  
  // Page: Incidents
  getIncidentQueue: (): Promise<ApiResponse<any[]>> => fetchApi("/hub/incidents"),
  updateIncidentTriage: (incidentId: string, payload: any): Promise<ApiResponse<any>> => fetchApi(`/hub/incidents/${incidentId}`, { method: "PATCH", body: JSON.stringify(payload) })
};
