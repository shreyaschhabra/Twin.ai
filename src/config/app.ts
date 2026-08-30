/**
 * Twin AI application configuration.
 *
 * useMockData — when true, all feature services return static mock data
 * instead of making API calls. Flip to false once the backend API is live.
 *
 * Can later be driven by NEXT_PUBLIC_USE_MOCK_DATA env var without
 * changing any service or component code.
 */
export const appConfig = {
  useMockData: process.env.NEXT_PUBLIC_USE_MOCK_DATA !== "false",
} as const;
