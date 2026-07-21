$ErrorActionPreference = 'Stop'
$stdin = [Console]::In.ReadToEnd()
try { $data = $stdin | ConvertFrom-Json } catch { exit 0 }

$path = $data.tool_input.file_path
if (-not $path) { exit 0 }

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path.TrimEnd('\')

try {
    if ([System.IO.Path]::IsPathRooted($path)) {
        $full = [System.IO.Path]::GetFullPath($path)
    } else {
        $full = [System.IO.Path]::GetFullPath((Join-Path $projectRoot $path))
    }
} catch {
    exit 0
}

if (-not $full.ToLower().StartsWith(($projectRoot.ToLower() + '\'))) {
    $reason = "Blocked by DeutschOps policy (CLAUDE.md): '$path' resolves outside the project folder ($projectRoot). Nothing should be written to Il mio Drive/OneDrive or other paths outside DeutschOps/."
    $out = @{
        hookSpecificOutput = @{
            hookEventName            = 'PreToolUse'
            permissionDecision       = 'deny'
            permissionDecisionReason = $reason
        }
    }
    $out | ConvertTo-Json -Compress -Depth 5
    exit 0
}

exit 0
