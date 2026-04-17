import { fetchApi, adminPath } from "./client";
import { ApiResponse, AdminDashboardResponse, PaginatedData } from "./types";
import { adaptAdminDashboard } from "./adapters";

export const adminService = {
  // Page: Landing / KPI
  getGlobalAnalytics: async (): Promise<ApiResponse<any>> => {
    const res = await fetchApi<AdminDashboardResponse>(adminPath("/admin/dashboard"), { method: "GET" });
    if (res.error || !res.data) return { data: null, error: res.error, status: res.status };
    return { data: adaptAdminDashboard(res.data), error: null, status: res.status };
  },
  getSystemAuditLogs: async (): Promise<ApiResponse<any[]>> => {
    const res = await fetchApi<{ logs: any[] }>(adminPath("/admin/audit-logs"), { method: "GET" });
    if (res.error || !res.data) return { data: null, error: res.error, status: res.status };
    return { data: res.data.logs || [], error: null, status: res.status };
  },
  
  // Page: Claims
  getClaimsDatabase: (page: number = 1): Promise<ApiResponse<PaginatedData<any>>> => fetchApi(adminPath(`/admin/claims?page=${page}`), { method: "GET" }),
  
  // Page: Actuarial
  getGlobalParameters: async (): Promise<ApiResponse<any>> => {
    const res = await fetchApi<any>(adminPath("/admin/actuarial/parameters"), { method: "GET" });
    if (res.status === 404 || res.status === 501) return { data: {}, error: null, status: res.status };
    return res;
  },
  updateGlobalParameters: (payload: any): Promise<ApiResponse<any>> => fetchApi(adminPath("/admin/actuarial/parameters"), { method: "PUT", body: JSON.stringify(payload) }),
  
  // Page: Simulation
  runSimulationModel: (seedData: any): Promise<ApiResponse<any>> => fetchApi(adminPath("/admin/stress-test/run"), { method: "POST", body: JSON.stringify(seedData) })
};
