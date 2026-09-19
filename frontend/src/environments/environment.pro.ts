// PROD. Fill banksApiUrl with the HttpApiUrl output of the cdts-pro-banks
// stack once Actions has run the first PRO deploy of the banks block.
export const environment = {
  stage: 'pro' as const,
  authApiUrl: 'https://yaf407aj6h.execute-api.us-east-1.amazonaws.com',
  banksApiUrl: 'https://REPLACE-AT-FIRST-PRO-DEPLOY.execute-api.us-east-1.amazonaws.com',
};
