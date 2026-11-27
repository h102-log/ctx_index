# Lists the sessions started in runs\<Name>\A and \B with what the CLI and the ctx-index hook recorded.
# Expect A: hook_turns 0, hook_compactions 0.  B: hook_turns > 0, hook_compactions = number of compactions.
param([Parameter(Mandatory = $true)][string]$Name)

$claude = Join-Path $env:USERPROFILE '.claude'
$rows = foreach ($cond in 'A', 'B') {
    $cwd = Join-Path $PSScriptRoot "runs\$Name\$cond"
    $project = Join-Path $claude ('projects\' + ($cwd -replace '[^A-Za-z0-9]', '-'))
    foreach ($t in Get-ChildItem $project -Filter *.jsonl -ErrorAction SilentlyContinue | Sort-Object LastWriteTime) {
        $ctx = Join-Path $claude "ctx-index\$($t.BaseName)"
        $compactions = Select-String -Path $t.FullName -AllMatches -Pattern '"compactMetadata":\{"trigger":"(\w+)","preTokens":(\d+),"postTokens":(\d+)' |
            ForEach-Object { $_.Matches } |
            ForEach-Object { '{0} {1}>{2}' -f $_.Groups[1].Value, $_.Groups[2].Value, $_.Groups[3].Value }
        [pscustomobject]@{
            cond             = $cond
            session          = $t.BaseName
            hook_turns       = @(Get-ChildItem (Join-Path $ctx 'turns') -Filter *.md -ErrorAction SilentlyContinue).Count
            hook_compactions = @(Get-Content (Join-Path $ctx 'compactions.jsonl') -ErrorAction SilentlyContinue).Count
            compactions      = $compactions -join ', '
        }
    }
}
if ($rows) { $rows | Format-Table -AutoSize -Wrap } else { "no sessions found for run '$Name'" }
