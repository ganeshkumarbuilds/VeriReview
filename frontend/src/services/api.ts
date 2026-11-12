const API_BASE_URL = "http://127.0.0.1:8000";

export interface BackendHealth {
  status: string;
  service: string;
}

export interface BackendRoot {
  message: string;
  status: string;
  platform: string;
}

export async function checkBackendHealth(): Promise<BackendHealth> {
  const response = await fetch(`${API_BASE_URL}/health`);

  if (!response.ok) {
    throw new Error("Backend health check failed");
  }

  return response.json();
}

export async function getBackendInfo(): Promise<BackendRoot> {
  const response = await fetch(`${API_BASE_URL}/`);

  if (!response.ok) {
    throw new Error("Unable to connect to VeriReview backend");
  }

  return response.json();
}