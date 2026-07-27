# briefing.ps1 — hook SessionStart.
#
# Stampa il riquadro di avvio all'apertura di ogni sessione Claude Code.
#
# PERCHE' UN HOOK E NON UNA REGOLA IN CLAUDE.md
# Il motore condiviso da cui questo pattern e' preso descrive lo stesso
# briefing e poi dichiara il proprio limite: «il markdown non impone all'AI di
# generare il briefing: e' una regola che l'AI segue, non un controllo del
# sistema. L'enforcement reale richiederebbe un hook».
# Eccolo. E' l'unico punto in cui DeutschOps supera il modello da cui copia.
#
# REGOLA DI SICUREZZA: questo hook non deve MAI far fallire una sessione.
# Qualunque errore viene inghiottito e si esce 0. Un briefing mancante e' un
# fastidio; una sessione che non parte e' un problema.

$ErrorActionPreference = 'SilentlyContinue'

try {
    $root = $env:CLAUDE_PROJECT_DIR
    if (-not $root) { $root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot) }

    # Il venv del progetto: le dipendenze stanno li', non nel Python di sistema.
    $py = Join-Path $root 'venv\Scripts\python.exe'
    if (-not (Test-Path $py)) { $py = 'py' }

    $entry = Join-Path $root 'deutschops.py'
    if (-not (Test-Path $entry)) { exit 0 }

    $env:PYTHONIOENCODING = 'utf-8'
    $out = & $py $entry briefing 2>$null | Out-String

    if ([string]::IsNullOrWhiteSpace($out)) { exit 0 }

    # additionalContext -> lo legge il modello, cosi' sa lo stato senza doverlo
    # chiedere. systemMessage -> lo vede Kevin nel terminale.
    $payload = @{
        systemMessage      = $out.TrimEnd()
        suppressOutput     = $true
        hookSpecificOutput = @{
            hookEventName     = 'SessionStart'
            additionalContext = "Stato DeutschOps all'avvio della sessione:`n$($out.TrimEnd())"
        }
    }
    $payload | ConvertTo-Json -Depth 5 -Compress
}
catch {
    # Silenzio: vedi la regola di sicurezza in cima.
}

exit 0
