# IAM bootstrap para GitHub Actions

Este directorio documenta la configuracion IAM que usan los workflows de despliegue.

## Recursos creados

| Recurso | ARN |
|---|---|
| Policy | `arn:aws:iam::658548982073:policy/CdtsGithubActionsDeploy` |
| User (dev) | `arn:aws:iam::658548982073:user/githubactions/github-actions-dev-deployer` |
| User (pro) | `arn:aws:iam::658548982073:user/githubactions/github-actions-pro-deployer` |

Ambos usuarios tienen la policy adjunta y viven bajo el path `/githubactions/` para
tenerlos agrupados y visibles rapido en la consola IAM.

Las access keys de cada usuario estan cargadas como GitHub Environment Secrets:

- Environment `dev` -> `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
- Environment `pro` -> `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`

La region esta como GitHub repo variable: `AWS_REGION=us-east-1`.

## Filosofia de permisos

- **No es admin.** Puede hacer todo lo que Serverless Framework necesita, pero:
  - No puede crear ni tocar otros usuarios ni grupos IAM.
  - No puede crear ni modificar policies (solo consumir la ya adjunta).
  - No puede tocar Organizations, billing, ni Cost Explorer.
- **Roles IAM scopeados por prefijo `cdts-`.** Solo puede crear/borrar roles cuyo nombre
  empieza con `cdts-`. Si en el futuro necesitamos otro prefijo, hay que actualizar la
  policy.
- **CloudFormation-driven.** Los deploys van via CloudFormation (Serverless), no comandos
  directos.
- **SSM de solo lectura.** Ningun stack de este repo crea parametros: los secretos
  (`/cdts/<stage>/db/*`, `/cdts/<stage>/smtp/*`) se crean a mano, y
  `/cdts/<stage>/frontend/url` lo publica el stack del frontend desde su propio
  repo con sus propias credenciales.

## Actualizar la policy

El JSON de este directorio es la fuente de verdad. Despues de editarlo hay que publicar
una version nueva y dejarla como default:

```bash
export AWS_PROFILE=<admin-profile>
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

aws iam create-policy-version \
  --policy-arn arn:aws:iam::658548982073:policy/CdtsGithubActionsDeploy \
  --policy-document file://scripts/iam/github-actions-deploy-policy.json \
  --set-as-default
```

IAM guarda maximo 5 versiones: si falla por ese limite, borrar la mas vieja con
`aws iam delete-policy-version --version-id <vN>`.

## Reproducibilidad

Si perdemos el bootstrap (o migramos de cuenta), este directorio permite recrear todo:

```bash
export AWS_PROFILE=<admin-profile>
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"

# 1) Crear policy
aws iam create-policy \
  --policy-name CdtsGithubActionsDeploy \
  --policy-document file://scripts/iam/github-actions-deploy-policy.json

POLICY_ARN=$(aws iam list-policies --scope Local \
  --query "Policies[?PolicyName=='CdtsGithubActionsDeploy'].Arn | [0]" --output text)

# 2) Crear usuarios y adjuntar la policy
for stage in dev pro; do
  user="github-actions-${stage}-deployer"
  aws iam create-user --user-name "$user" --path /githubactions/ \
    --tags Key=Project,Value=cdts Key=Stage,Value=$stage Key=ManagedBy,Value=bootstrap
  aws iam attach-user-policy --user-name "$user" --policy-arn "$POLICY_ARN"
done

# 3) Generar access keys y cargarlas como GitHub environment secrets
REPO="salo368/ingenieria-de-software-proyecto"
for stage in dev pro; do
  user="github-actions-${stage}-deployer"
  OUT=$(aws iam create-access-key --user-name "$user" \
    --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text)
  KEY_ID=$(printf '%s' "$OUT" | awk '{print $1}')
  SECRET=$(printf '%s' "$OUT" | awk '{print $2}')
  printf '%s' "$KEY_ID" | gh secret set AWS_ACCESS_KEY_ID     --env "$stage" -R "$REPO"
  printf '%s' "$SECRET" | gh secret set AWS_SECRET_ACCESS_KEY --env "$stage" -R "$REPO"
  unset OUT KEY_ID SECRET
done

# 4) Variable de region (repo-level)
gh variable set AWS_REGION -R "$REPO" -b "us-east-1"
```

## Rotacion de credenciales

AWS recomienda rotar access keys cada 90 dias. Para rotar manualmente:

```bash
export AWS_PROFILE=<admin-profile>
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL="*"
REPO="salo368/ingenieria-de-software-proyecto"
STAGE=dev  # o pro
user="github-actions-${STAGE}-deployer"

# 1) Crear nueva key
OUT=$(aws iam create-access-key --user-name "$user" \
  --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text)
NEW_KEY_ID=$(printf '%s' "$OUT" | awk '{print $1}')
NEW_SECRET=$(printf '%s' "$OUT" | awk '{print $2}')

# 2) Sobreescribir secrets en GitHub
printf '%s' "$NEW_KEY_ID" | gh secret set AWS_ACCESS_KEY_ID     --env "$STAGE" -R "$REPO"
printf '%s' "$NEW_SECRET" | gh secret set AWS_SECRET_ACCESS_KEY --env "$STAGE" -R "$REPO"

# 3) Verificar que el proximo deploy funciona con la nueva key.
# 4) Borrar la key vieja:
#    aws iam list-access-keys --user-name "$user"
#    aws iam delete-access-key --user-name "$user" --access-key-id <OLD_ID>

unset OUT NEW_KEY_ID NEW_SECRET
```
