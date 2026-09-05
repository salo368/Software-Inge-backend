# Proyecto Ingeniería de Software — Javeriana

Web App + API desplegada en AWS con Terraform.

## Requisitos previos

- [AWS CLI v2](https://awscli.amazonaws.com/AWSCLIV2.msi)
- [Terraform](https://developer.hashicorp.com/terraform/install)
- Git
- Cuenta AWS con un usuario IAM (`dev-salomon`) con access keys

## Setup local

Las credenciales de AWS **no están enlazadas al CLI global**. Viven en `access.csv` dentro del proyecto (excluido de git por `.gitignore`).

### Cargar credenciales en la sesión actual

**Git Bash:**

```bash
source ./scripts/load-aws-env.sh
aws sts get-caller-identity   # verifica que quedo cargado
```

**PowerShell:**

```powershell
. .\scripts\load-aws-env.ps1
aws sts get-caller-identity
```

> Las credenciales solo viven en la sesión actual. Al cerrar la terminal se van.

## Estructura

```
.
├── access.csv              # Credenciales AWS (NO SE COMMITEA)
├── scripts/
│   ├── load-aws-env.sh     # Loader para git bash
│   └── load-aws-env.ps1    # Loader para PowerShell
├── infra/                  # (proximamente) Módulos Terraform
├── backend/                # (proximamente) API
└── frontend/               # (proximamente) Web
```

## Seguridad

- `access.csv` está en `.gitignore`. **Nunca lo commitees.**
- Si sospechas fuga, ve a IAM → `dev-salomon` → Security credentials → Delete access key y crea una nueva.
- Rota las keys cada 90 días como buena práctica.
