# Platform block: assets

Public S3 bucket for static assets referenced by database rows and served
directly to the frontend.

## Layout

```
backend/platform/assets/
├── serverless.yml       # bucket + public-read policy
└── files/               # content dir - everything here gets synced to S3
    └── banks/
        ├── bancolombia.png
        └── ...
```

## URL

- **dev**: `https://cdts-dev-assets.s3.us-east-1.amazonaws.com/<key>`
- **pro**: `https://cdts-pro-assets.s3.us-east-1.amazonaws.com/<key>`

Also exported as `cdts-<stage>-assets-base-url` from CloudFormation for
services that need it as an env var.

## How the DB uses it

Rows store the **key** (relative path), not the full URL. Example:
`banks.logo_key = 'banks/bancolombia.png'`. The handler in
`services/banks/` reads `ASSETS_BASE_URL` from env and returns the
absolute URL in the API response.

## Deploy

The block is a `platform` block with content dir `files/` declared in
`scripts/ci/plan-deploy.sh` (`PLATFORM_CONTENT_DIRS["assets"]="files"`):

- Change only inside `files/**` → deploy only `assets` (fast: bucket
  already exists, just `aws s3 sync`).
- Any other change (`serverless.yml`, this README) → full backend redeploy.

The deploy job runs `scripts/ci/deploy-assets.sh` which:

1. `sls deploy` (idempotent; creates or updates the bucket).
2. `aws s3 sync files/ s3://cdts-<stage>-assets/` with correct content types.
