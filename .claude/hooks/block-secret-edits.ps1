$ErrorActionPreference = 'Stop'
$stdin = [Console]::In.ReadToEnd()
try { $data = $stdin | ConvertFrom-Json } catch { exit 0 }

$path = $data.tool_input.file_path
if (-not $path) { $path = $data.tool_input.notebook_path }
if (-not $path) { exit 0 }

$normalized = $path -replace '/', '\'
if ($normalized -imatch '(^|\\)(\.env|credentials\.json|token\.json(\.bak_expired|\.expired_bak)?)$') {
    $reason = "Blocked by DeutschOps policy (CLAUDE.md): '$path' is a secret/credential file (.env, credentials.json, token.json). Edit it manually outside Claude Code if needed."
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
