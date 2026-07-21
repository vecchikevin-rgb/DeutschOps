<#
ollama_benchmark.ps1
Misura l'utilizzo di CPU/RAM/GPU (VRAM + utilizzo%) mentre Ollama elabora un
prompt realistico (stessa forma della Call 1 di extractor.py), per decidere
se conviene un upgrade hardware (CPU vs GPU/VRAM) sulla macchina che fa da
backend LLM_BACKEND=ollama.

Uso:
  .\ollama_benchmark.ps1                       # testa tutti i modelli installati
  .\ollama_benchmark.ps1 -Models qwen2.5:7b-instruct,llama3.2:3b
  .\ollama_benchmark.ps1 -MaxTokens 400 -IntervalMs 500

Output:
  benchmarks/ollama_bench_<modello>_<timestamp>.csv   (serie temporale campioni)
  benchmarks/summary_<timestamp>.csv                  (tabella comparativa finale)
#>

param(
    [string[]]$Models,
    [int]$IntervalMs = 1000,
    [int]$MaxTokens = 800,
    [string]$OllamaHost = "http://localhost:11434",
    [string]$OutDir = "benchmarks"
)

$ErrorActionPreference = "Stop"
$stamp = Get-Date -Format "yyyy-MM-dd_HHmmss"

if (-not (Test-Path $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir | Out-Null
}

# ---------------------------------------------------------------- pre-check

try {
    $version = Invoke-RestMethod -Uri "$OllamaHost/api/version" -TimeoutSec 5
    Write-Host "Ollama raggiungibile (v$($version.version)) su $OllamaHost" -ForegroundColor Green
} catch {
    Write-Host "ERRORE: Ollama non raggiungibile su $OllamaHost. Il servizio e' avviato?" -ForegroundColor Red
    exit 1
}

$hasGpu = [bool](Get-Command nvidia-smi -ErrorAction SilentlyContinue)
if (-not $hasGpu) {
    Write-Host "nvidia-smi non trovato: verranno registrati solo CPU/RAM (nessuna GPU NVIDIA su questa macchina)." -ForegroundColor Yellow
}

if (-not $Models -or $Models.Count -eq 0) {
    $raw = ollama list
    $Models = $raw | Select-Object -Skip 1 | ForEach-Object { ($_ -split '\s{2,}')[0] } | Where-Object { $_ -and $_.Trim() -ne "" }
}

if (-not $Models -or $Models.Count -eq 0) {
    Write-Host "ERRORE: nessun modello Ollama trovato (ollama list e' vuoto)." -ForegroundColor Red
    exit 1
}

Write-Host "Modelli da testare: $($Models -join ', ')`n"

# ---------------------------------------------------------------- prompt di test

$SystemPrompt = @"
You are a German language tutor. Student: Kevin (Italian, A2->B1), lessons in English with native speaker Stefanie. Transcript: English + German examples + occasional Italian.

Return ONLY valid JSON -- no backticks, no extra text.

{"lesson_number":"<int or ''>","topic":"<5 words>","summary_en":"<=120 words>","summary_it":"<Italian>","vocabulary":[{"german":"<base word>","article":"<der|die|das|''>","plural":"<or ''>","category":"<noun|verb|adjective|phrase>","italian":"<str>","english":"<str>","example_de":"<str>","example_it":"<str>","level":"<A1|A2|B1|B2>"}],"grammar_points":[{"rule":"<str>","explanation_en":"<str>","examples":["<str>"]}],"phrases":[{"german":"<str>","english":"<str>","context":"<str>"}],"comprehension_questions":[{"question_de":"<str>","answer_de":"<str>"}]}
"@

$UserPrompt = @"
Stefanie: Guten Tag Kevin, wie geht es dir heute?
Kevin: Mir geht es gut, danke. Ich habe diese Woche viel gearbeitet.
Stefanie: Das ist gut. Heute lernen wir die Verben mit Praepositionen: warten auf, sich freuen auf, denken an, sich interessieren fuer.
Kevin: Ich warte auf meinen Kollegen. Ich freue mich auf das Wochenende.
Stefanie: Sehr gut! Und kannst du einen Satz mit "denken an" bilden?
Kevin: Ich denke oft an meine Familie in Italien.
Stefanie: Perfekt. Jetzt ueben wir die Wechselpraepositionen: in, an, auf, unter, ueber, vor, hinter, neben, zwischen.
Kevin: Das Buch liegt auf dem Tisch. Ich lege das Buch auf den Tisch.
Stefanie: Genau, das ist der Unterschied zwischen Dativ und Akkusativ.
"@

# ---------------------------------------------------------------- helper: singolo campione risorse

function Get-ResourceSample {
    param([string]$ModelName)

    $ts = Get-Date -Format "o"
    $cpuPct = $null
    $ramPct = $null
    $gpuUtil = $null
    $vramUsed = $null
    $vramTotal = $null
    $gpuTemp = $null
    $sizeVram = $null
    $sizeTotal = $null

    try {
        $cpuPct = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
    } catch {}

    try {
        $os = Get-CimInstance Win32_OperatingSystem
        $ramPct = [math]::Round((($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / $os.TotalVisibleMemorySize) * 100, 1)
    } catch {}

    if ($hasGpu) {
        try {
            $line = (nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits) -split ','
            $gpuUtil   = [double]($line[0].Trim())
            $vramUsed  = [double]($line[1].Trim())
            $vramTotal = [double]($line[2].Trim())
            $gpuTemp   = [double]($line[3].Trim())
        } catch {}
    }

    try {
        $ps = Invoke-RestMethod -Uri "$OllamaHost/api/ps" -TimeoutSec 5
        $m = $ps.models | Where-Object { $_.name -eq $ModelName -or $_.model -eq $ModelName } | Select-Object -First 1
        if ($m) {
            $sizeTotal = $m.size
            $sizeVram  = $m.size_vram
        }
    } catch {}

    [PSCustomObject]@{
        timestamp     = $ts
        cpu_pct       = $cpuPct
        ram_pct       = $ramPct
        gpu_util_pct  = $gpuUtil
        vram_used_mib = $vramUsed
        vram_total_mib= $vramTotal
        gpu_temp_c    = $gpuTemp
        size_bytes    = $sizeTotal
        size_vram_bytes = $sizeVram
    }
}

# ---------------------------------------------------------------- loop principale

$summaries = @()

foreach ($model in $Models) {
    Write-Host "=== Benchmark: $model ===" -ForegroundColor Cyan

    $body = @{
        model    = $model
        messages = @(
            @{ role = "system"; content = $SystemPrompt }
            @{ role = "user"; content = $UserPrompt }
        )
        stream  = $false
        options = @{ num_predict = $MaxTokens }
    } | ConvertTo-Json -Depth 8

    $job = Start-Job -ScriptBlock {
        param($uri, $jsonBody)
        $sw = [System.Diagnostics.Stopwatch]::StartNew()
        try {
            $resp = Invoke-RestMethod -Uri $uri -Method Post -Body $jsonBody -ContentType "application/json; charset=utf-8" -TimeoutSec 1800
            $sw.Stop()
            [PSCustomObject]@{ Ok = $true; Response = $resp; WallMs = $sw.ElapsedMilliseconds }
        } catch {
            $sw.Stop()
            [PSCustomObject]@{ Ok = $false; Error = $_.Exception.Message; WallMs = $sw.ElapsedMilliseconds }
        }
    } -ArgumentList "$OllamaHost/api/chat", $body

    $samples = New-Object System.Collections.Generic.List[object]
    while ($job.State -eq "Running") {
        $samples.Add((Get-ResourceSample -ModelName $model))
        Start-Sleep -Milliseconds $IntervalMs
    }
    $result = Receive-Job -Job $job
    Remove-Job -Job $job

    if (-not $result.Ok) {
        Write-Host "  FALLITO: $($result.Error)" -ForegroundColor Red
        $summaries += [PSCustomObject]@{
            model = $model; ok = $false; error = $result.Error
        }
        continue
    }

    $safeName = ($model -replace '[:\\/]', '_')
    $csvPath = Join-Path $OutDir "ollama_bench_${safeName}_${stamp}.csv"
    $samples | Export-Csv -Path $csvPath -NoTypeInformation -Encoding UTF8

    $resp = $result.Response
    $evalCount = $resp.eval_count
    $evalNs    = $resp.eval_duration
    $promptCount = $resp.prompt_eval_count
    $promptNs    = $resp.prompt_eval_duration
    $tokPerSec = if ($evalNs -gt 0) { [math]::Round($evalCount / ($evalNs / 1e9), 1) } else { $null }
    $promptTokPerSec = if ($promptNs -gt 0) { [math]::Round($promptCount / ($promptNs / 1e9), 1) } else { $null }

    $gpuSamples = $samples | Where-Object { $null -ne $_.gpu_util_pct }
    $avgCpu = [math]::Round(($samples | Measure-Object -Property cpu_pct -Average).Average, 1)
    $maxCpu = ($samples | Measure-Object -Property cpu_pct -Maximum).Maximum
    $avgGpu = if ($gpuSamples) { [math]::Round(($gpuSamples | Measure-Object -Property gpu_util_pct -Average).Average, 1) } else { $null }
    $maxGpu = if ($gpuSamples) { ($gpuSamples | Measure-Object -Property gpu_util_pct -Maximum).Maximum } else { $null }
    $peakVram = if ($gpuSamples) { ($gpuSamples | Measure-Object -Property vram_used_mib -Maximum).Maximum } else { $null }
    $vramTotal = if ($gpuSamples) { ($gpuSamples | Select-Object -First 1).vram_total_mib } else { $null }

    $lastSized = $samples | Where-Object { $_.size_bytes -gt 0 } | Select-Object -Last 1
    $offloadPct = $null
    if ($lastSized -and $lastSized.size_bytes -gt 0) {
        $offloadPct = [math]::Round(($lastSized.size_vram_bytes / $lastSized.size_bytes) * 100, 1)
    }

    $summary = [PSCustomObject]@{
        model             = $model
        ok                = $true
        wall_time_s       = [math]::Round($result.WallMs / 1000, 1)
        tokens_generated  = $evalCount
        tokens_per_sec    = $tokPerSec
        prompt_tok_per_sec= $promptTokPerSec
        avg_cpu_pct       = $avgCpu
        max_cpu_pct       = $maxCpu
        avg_gpu_pct       = $avgGpu
        max_gpu_pct       = $maxGpu
        peak_vram_mib     = $peakVram
        vram_total_mib    = $vramTotal
        gpu_offload_pct   = $offloadPct
        samples_csv       = $csvPath
    }
    $summaries += $summary

    Write-Host ("  {0:N1}s | {1} tok generati | {2} tok/s | CPU avg/max {3}%/{4}% | GPU avg/max {5}%/{6}% | VRAM picco {7}/{8} MiB | offload GPU {9}%" -f `
        $summary.wall_time_s, $summary.tokens_generated, $summary.tokens_per_sec, `
        $summary.avg_cpu_pct, $summary.max_cpu_pct, $summary.avg_gpu_pct, $summary.max_gpu_pct, `
        $summary.peak_vram_mib, $summary.vram_total_mib, $summary.gpu_offload_pct) -ForegroundColor White
    Write-Host ""
}

# ---------------------------------------------------------------- riepilogo finale

$summaryCsv = Join-Path $OutDir "summary_${stamp}.csv"
$summaries | Export-Csv -Path $summaryCsv -NoTypeInformation -Encoding UTF8

Write-Host "=== Riepilogo comparativo ===" -ForegroundColor Cyan
$summaries | Where-Object { $_.ok } | Sort-Object tokens_per_sec -Descending |
    Format-Table model, tokens_per_sec, avg_cpu_pct, max_cpu_pct, avg_gpu_pct, gpu_offload_pct, peak_vram_mib, vram_total_mib -AutoSize

Write-Host "`nCSV salvati in: $OutDir\ (per-modello + summary_${stamp}.csv)"

foreach ($s in ($summaries | Where-Object { $_.ok })) {
    if ($null -ne $s.gpu_offload_pct -and $s.gpu_offload_pct -lt 100) {
        Write-Host ("NOTA: '{0}' supera la VRAM disponibile ({1} MiB totali) -> solo il {2}% del modello resta in GPU, il resto gira su CPU/RAM (piu' lento). Un upgrade GPU con piu' VRAM aiuterebbe qui." -f $s.model, $s.vram_total_mib, $s.gpu_offload_pct) -ForegroundColor Yellow
    } elseif ($s.avg_cpu_pct -ge 85) {
        Write-Host ("NOTA: '{0}' sta con la CPU quasi satura (avg {1}%) pur restando in VRAM -> qui aiuterebbe una CPU piu' veloce, non la GPU." -f $s.model, $s.avg_cpu_pct) -ForegroundColor Yellow
    }
}
