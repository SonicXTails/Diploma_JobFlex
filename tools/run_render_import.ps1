# Импорт HH в Postgres на Render с ПК (Shell на Render не нужен).
# 1) Скопируй .env.render.example → .env.render и заполни DATABASE_URL + DJANGO_SECRET_KEY.
# 2) Запуск из корня репозитория:
#      .\tools\run_render_import.ps1
#    С аргументами:
#      .\tools\run_render_import.ps1 --pages 2

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $Passthrough
)

$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path '.env.render')) {
    Write-Error "Создай файл .env.render из .env.render.example и заполни секреты."
}
$env:JOBFLEX_USE_RENDER_DB = '1'
if ($Passthrough -and $Passthrough.Length -gt 0) {
    & python manage.py render_prod_smoke @Passthrough
} else {
    & python manage.py render_prod_smoke
}
