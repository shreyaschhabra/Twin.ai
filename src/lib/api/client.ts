/**
 * Future API client configuration.
 *
 * TWIN_API_URL is not required in Phase 5. Feature services currently
 * return mock data. When the backend API is ready, set this env var
 * and update the service functions to use apiClient.
 *
 * No HTTP calls are made here. This module only provides the base URL
 * and a placeholder for future request configuration.
 */

const TWIN_API_URL = process.env.TWIN_API_URL ?? "";

/**
 * API configuration object.
 * Feature services import this to construct fetch calls when transitioning
 * from mock data to live API.
 */
export const apiConfig = {
  baseUrl: TWIN_API_URL,
  /**
   * Returns true when a real API URL has been configured.
   * Services can use this to conditionally use mock vs live data
   * if appConfig.useMockData is not sufficient.
   */
  isConfigured: TWIN_API_URL.length > 0,
} as const;

/**
 * Placeholder for future typed API client.
 *
 * Usage when API is live:
 * ```ts
 * const data = await apiClient<Station[]>("/stations");
 * ```
 *
 * Not implemented yet — services use mock data.
 */
export async function apiClient<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  if (!apiConfig.isConfigured) {
    throw new Error(
      `Twin AI API URL is not configured. Set TWIN_API_URL env var. Attempted: ${path}`,
    );
  }
  const response = await fetch(`${apiConfig.baseUrl}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    throw new Error(`API request failed: ${response.status} ${path}`);
  }
  return response.json() as Promise<T>;
}
