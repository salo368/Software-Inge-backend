# Carga las credenciales AWS desde access.csv en la sesion actual de PowerShell.
# Uso:  . .\scripts\load-aws-env.ps1
#
# NOTA: hay que usar dot-sourcing (el punto al inicio), NO ejecutar directo,
# porque las variables tienen que quedar en la sesion actual.

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$CsvPath   = Join-Path $ScriptDir "..\access.csv"
$CsvPath   = [System.IO.Path]::GetFullPath($CsvPath)

if (-not (Test-Path $CsvPath)) {
    Write-Host "ERROR: no se encontro access.csv en la raiz del proyecto ($CsvPath)." -ForegroundColor Red
    return
}

$Csv = Import-Csv -Path $CsvPath

if (-not $Csv -or $Csv.Count -eq 0) {
    Write-Host "ERROR: el archivo access.csv esta vacio o mal formateado." -ForegroundColor Red
    return
}

$Row = $Csv[0]
$AccessKey = $null
$SecretKey = $null

# Nombres posibles de columnas (AWS ha variado el header con el tiempo)
$AccessKeyCandidates = @("Access key ID", "AccessKeyId", "Access Key Id")
$SecretKeyCandidates = @("Secret access key", "SecretAccessKey", "Secret Access Key")

foreach ($name in $AccessKeyCandidates) {
    if ($Row.PSObject.Properties.Name -contains $name) {
        $AccessKey = $Row.$name
        break
    }
}
foreach ($name in $SecretKeyCandidates) {
    if ($Row.PSObject.Properties.Name -contains $name) {
        $SecretKey = $Row.$name
        break
    }
}

if (-not $AccessKey -or -not $SecretKey) {
    Write-Host "ERROR: no se encontraron columnas de Access Key / Secret en el CSV." -ForegroundColor Red
    Write-Host "Columnas detectadas: $($Row.PSObject.Properties.Name -join ', ')" -ForegroundColor Yellow
    return
}

$env:AWS_ACCESS_KEY_ID     = $AccessKey
$env:AWS_SECRET_ACCESS_KEY = $SecretKey
if (-not $env:AWS_DEFAULT_REGION) {
    $env:AWS_DEFAULT_REGION = "us-east-1"
}

$Masked = $AccessKey.Substring(0,4) + "****" + $AccessKey.Substring($AccessKey.Length - 4)
Write-Host "AWS credenciales cargadas en la sesion actual." -ForegroundColor Green
Write-Host "  Access Key: $Masked"
Write-Host "  Region:     $($env:AWS_DEFAULT_REGION)"
Write-Host ""
Write-Host "Verifica con: aws sts get-caller-identity"
