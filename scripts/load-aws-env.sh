#!/usr/bin/env bash
# Carga las credenciales AWS desde access.csv en la sesion actual.
# Uso:  source ./scripts/load-aws-env.sh
#
# NOTA: hay que usar 'source' (o '.'), NO ejecutar directamente,
# porque las variables tienen que quedar en la shell padre.

# Detecta si fue ejecutado en vez de sourced
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "ERROR: usa 'source ./scripts/load-aws-env.sh' (no ejecutar directamente)."
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CSV_PATH="${SCRIPT_DIR}/../access.csv"

if [[ ! -f "$CSV_PATH" ]]; then
  echo "ERROR: no se encontro access.csv en la raiz del proyecto ($CSV_PATH)."
  return 1
fi

# Lee header y linea de datos
HEADER=$(head -n 1 "$CSV_PATH" | tr -d '\r')
DATA=$(sed -n '2p' "$CSV_PATH" | tr -d '\r')

if [[ -z "$DATA" ]]; then
  echo "ERROR: el archivo access.csv esta vacio o solo tiene el header."
  return 1
fi

# Detecta formato: corto (2 columnas) o largo (5 columnas)
NUM_FIELDS=$(awk -F',' '{print NF}' <<< "$HEADER")

if [[ "$NUM_FIELDS" == "2" ]]; then
  # Formato: Access key ID,Secret access key
  AWS_ACCESS_KEY_ID=$(awk -F',' '{print $1}' <<< "$DATA")
  AWS_SECRET_ACCESS_KEY=$(awk -F',' '{print $2}' <<< "$DATA")
elif [[ "$NUM_FIELDS" == "5" ]]; then
  # Formato: User name,Password,Access key ID,Secret access key,Console login link
  AWS_ACCESS_KEY_ID=$(awk -F',' '{print $3}' <<< "$DATA")
  AWS_SECRET_ACCESS_KEY=$(awk -F',' '{print $4}' <<< "$DATA")
else
  echo "ERROR: formato de CSV no reconocido ($NUM_FIELDS columnas). Header: $HEADER"
  return 1
fi

if [[ -z "$AWS_ACCESS_KEY_ID" || -z "$AWS_SECRET_ACCESS_KEY" ]]; then
  echo "ERROR: no se pudieron extraer las credenciales del CSV."
  return 1
fi

export AWS_ACCESS_KEY_ID
export AWS_SECRET_ACCESS_KEY
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

# Confirmacion sin mostrar el secret
MASKED_KEY="${AWS_ACCESS_KEY_ID:0:4}****${AWS_ACCESS_KEY_ID: -4}"
echo "AWS credenciales cargadas en la sesion actual."
echo "  Access Key: $MASKED_KEY"
echo "  Region:     $AWS_DEFAULT_REGION"
echo ""
echo "Verifica con: aws sts get-caller-identity"
