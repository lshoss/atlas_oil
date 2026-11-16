$ErrorActionPreference = 'Stop'

function Invoke-Orchestrate {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]] $Arguments)
    & orchestrate @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Falha no comando: orchestrate $($Arguments -join ' ')"
    }
}

if (-not $env:ATLASOIL_PUBLIC_BACKEND_URL) {
    throw 'Defina ATLASOIL_PUBLIC_BACKEND_URL com a URL HTTPS pública do backend.'
}
if (-not $env:ATLASOIL_TOOL_API_KEY) {
    throw 'Defina ATLASOIL_TOOL_API_KEY com a mesma chave configurada no backend.'
}
if (-not (Get-Command orchestrate -ErrorAction SilentlyContinue)) {
    throw 'O comando orchestrate não está no PATH. Instale/ative o ADK antes de importar.'
}

$publicUri = $null
if (-not [Uri]::TryCreate($env:ATLASOIL_PUBLIC_BACKEND_URL, [UriKind]::Absolute, [ref]$publicUri) `
    -or $publicUri.Scheme -ne 'https') {
    throw 'ATLASOIL_PUBLIC_BACKEND_URL deve ser uma URL HTTPS pública válida.'
}

$root = Resolve-Path (Join-Path $PSScriptRoot '..')
$template = Join-Path $root 'openapi\atlasoil-tools.openapi.yaml'
$generated = Join-Path $root 'openapi\atlasoil-tools.generated.yaml'
$server = $publicUri.AbsoluteUri.TrimEnd('/')
(Get-Content -LiteralPath $template -Raw).Replace('https://YOUR_PUBLIC_BACKEND_URL', $server) |
    Set-Content -LiteralPath $generated -Encoding utf8

Invoke-Orchestrate connections add --app-id atlasoil_backend
Invoke-Orchestrate connections configure --app-id atlasoil_backend --env draft --type team `
    --kind api_key --name X-AtlasOil-Tool-Key --url "$server/api"
Invoke-Orchestrate connections set-credentials --app-id atlasoil_backend --env draft `
    --api-key $env:ATLASOIL_TOOL_API_KEY
Invoke-Orchestrate tools import -k openapi -f $generated --app-id atlasoil_backend
Invoke-Orchestrate agents import -f (Join-Path $root 'agents\atlasoil.yaml')
Invoke-Orchestrate agents deploy -n atlasoil
Invoke-Orchestrate agents list -k native -v

Write-Host 'Importação concluída. Copie o UUID de atlasoil para WATSONX_ORCHESTRATE_AGENT_ID.'
