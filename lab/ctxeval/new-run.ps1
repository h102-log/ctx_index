# Creates runs\<Name>\A (all hooks off) and runs\<Name>\B (hooks on) for one A/B run.
# Both folders get the same project settings; A only adds "disableAllHooks".
param([Parameter(Mandatory = $true)][string]$Name)
$ErrorActionPreference = 'Stop'

$run = Join-Path $PSScriptRoot "runs\$Name"
if (Test-Path $run) { throw "already exists: $run" }

$common = '"model": "claude-opus-5-5", "env": { "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "400000" }'
$settings = @{ A = "{ $common, `"disableAllHooks`": true }"; B = "{ $common }" }

foreach ($cond in 'A', 'B') {
    $dir = Join-Path $run "$cond\.claude"
    New-Item -ItemType Directory -Force $dir | Out-Null
    Set-Content -Path (Join-Path $dir 'settings.json') -Value $settings[$cond] -Encoding ascii
}
"created $run\A (hooks off) and $run\B (hooks on)"
