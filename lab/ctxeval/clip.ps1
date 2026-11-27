# Copies one prompt or question of set s02 to the clipboard:  clip.ps1 p01 ... p16,  clip.ps1 q01 ... q10
param([Parameter(Mandatory = $true)][string]$Name)
$ErrorActionPreference = 'Stop'

# -Encoding UTF8: Windows PowerShell 5.1 reads BOM-less files as ANSI otherwise and garbles the Korean text.
$text = (Get-Content -Raw -Encoding UTF8 (Join-Path $PSScriptRoot "prompts\s02\$Name.txt")).TrimEnd()
Set-Clipboard -Value $text
"copied $Name ({0:N0} chars, {1:N0} lines)" -f $text.Length, ($text -split "`n").Count
