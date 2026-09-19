// Default (dev). Cada servicio backend expone su propio HttpApi en API Gateway,
// asi que hay una URL base distinta por dominio. Cuando se consolide todo bajo
// un unico dominio custom (o REST API compartida) se colapsa a un solo apiBaseUrl.
export const environment = {
  stage: 'dev' as const,
  authApiUrl: 'https://7sdsmzal74.execute-api.us-east-1.amazonaws.com',
  banksApiUrl: 'https://elrpxpxr10.execute-api.us-east-1.amazonaws.com',
};
