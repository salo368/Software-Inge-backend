// PROD. Fill each URL with the HttpApiUrl output of the matching cdts-pro-<service>
// stack once Actions has run the first PRO deploy for that block.
export const environment = {
  stage: 'pro' as const,
  authApiUrl: 'https://yaf407aj6h.execute-api.us-east-1.amazonaws.com',
  banksApiUrl: 'https://REPLACE-AT-FIRST-PRO-DEPLOY.execute-api.us-east-1.amazonaws.com',
  filesApiUrl: 'https://REPLACE-AT-FIRST-PRO-DEPLOY.execute-api.us-east-1.amazonaws.com',
  formsApiUrl: 'https://REPLACE-AT-FIRST-PRO-DEPLOY.execute-api.us-east-1.amazonaws.com',
  processesApiUrl: 'https://REPLACE-AT-FIRST-PRO-DEPLOY.execute-api.us-east-1.amazonaws.com',
  signaturesApiUrl: 'https://REPLACE-AT-FIRST-PRO-DEPLOY.execute-api.us-east-1.amazonaws.com',
};
