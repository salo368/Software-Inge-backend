// Default (dev). Each backend service exposes its own API Gateway HttpApi so
// each domain has its own base URL. Once we consolidate under a single custom
// domain (or a shared REST API), these collapse to one apiBaseUrl.
export const environment = {
  stage: 'dev' as const,
  authApiUrl: 'https://7sdsmzal74.execute-api.us-east-1.amazonaws.com',
  banksApiUrl: 'https://elrpxpxr10.execute-api.us-east-1.amazonaws.com',
};
