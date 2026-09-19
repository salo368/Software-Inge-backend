// PROD. Rellenar banksApiUrl con el HttpApiUrl del stack cdts-pro-banks
// que aparece en las Outputs cuando Actions haga el primer Deploy PRO del bloque.
export const environment = {
  stage: 'pro' as const,
  authApiUrl: 'https://yaf407aj6h.execute-api.us-east-1.amazonaws.com',
  banksApiUrl: 'https://REPLACE-AT-FIRST-PRO-DEPLOY.execute-api.us-east-1.amazonaws.com',
};
