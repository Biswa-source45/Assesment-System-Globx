<#
Run this on the OFFICE PC while a load test is going (PowerShell, as Administrator, in the folder that holds docker-compose.yml):

  powershell -ExecutionPolicy Bypass -File .\monitor_host.ps1 -Token <a long random word you choose>

It does three things and nothing else:
  1. every 3 seconds it notes how the PC and the containers are doing: free memory, processor, every container's processor and memory, restarts and
     "killed for memory" flags, database connections and size, disk space, whether the exam server is healthy. The notes are kept in a file.
  2. it answers two read-only web addresses on the office network only (nothing is changed by them):
       http://<this PC>:9100/status/<token>    the latest note (the test computer reads it to stop the test if the PC runs short of memory)
       http://<this PC>:9100/metrics/<token>   all notes so far (read once at the end for the report)
  3. it opens port 9100 for the office network while it runs, and closes it again when you press Ctrl+C.
It never starts, stops or changes a container.
#>
param(
    [Parameter(Mandatory = $true)][string]$Token,
    [int]$Port = 9100,
    [int]$Every = 3,
    [string]$Project = "oap",
    [string]$Bind = "+",          # "localhost" only to try the script on a computer that is not the office PC
    [switch]$NoDocker             # try the script without Docker
)
$ErrorActionPreference = "SilentlyContinue"
if ($Token.Length -lt 12) { Write-Host "Choose a longer -Token (at least 12 characters)." -ForegroundColor Red; exit 1 }
$out = Join-Path $PSScriptRoot "loadtest-metrics.jsonl"
if (Test-Path $out) { Remove-Item $out -Force }
$ruleName = "Load test monitor"
if ($Bind -ne "localhost") {
    Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Protocol TCP -LocalPort $Port -RemoteAddress LocalSubnet -Action Allow | Out-Null
}
$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://${Bind}:$Port/")
try { $listener.Start() } catch { Write-Host "Could not listen on port ${Port}: run PowerShell as Administrator." -ForegroundColor Red; exit 1 }
Write-Host "Monitor running. Status:  http://<this PC's address>:$Port/status/$Token   (Ctrl+C to stop)" -ForegroundColor Green

function Parse-Size($text) {   # "123.4MiB" / "1.2GiB" / "56kB" -> megabytes
    if ($text -match '^([\d\.]+)\s*([KMGT]?i?B)') {
        $n = [double]$Matches[1]
        switch -Regex ($Matches[2]) { '^B$' { return $n / 1MB } '^K' { return $n / 1024 } '^M' { return $n } '^G' { return $n * 1024 } '^T' { return $n * 1048576 } }
    }
    return 0
}

function Sample {
    $os = Get-CimInstance Win32_OperatingSystem
    $cpu = (Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor -Filter "Name='_Total'").PercentProcessorTime
    $disk = Get-PSDrive -Name ($PSScriptRoot.Substring(0, 1))
    $vm = Get-Process vmmem* | Measure-Object WorkingSet64 -Sum
    $row = [ordered]@{
        t = [math]::Round(([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()) / 1000, 1)
        free_mb = [int]($os.FreePhysicalMemory / 1024); total_mb = [int]($os.TotalVisibleMemorySize / 1024)
        cpu = $cpu; disk_free_gb = [math]::Round($disk.Free / 1GB, 1); wsl_vm_mb = [int]($vm.Sum / 1MB)
        api_ok = $true; restarts_total = 0; oom = $false; others_restarts = 0; containers = @(); db = $null
    }
    if (-not $NoDocker) {
        $stats = docker stats --no-stream --format "{{json .}}" 2>$null | ForEach-Object { $_ | ConvertFrom-Json }
        $state = @{}
        docker ps -q 2>$null | ForEach-Object {
            $i = docker inspect $_ 2>$null | ConvertFrom-Json
            if ($i) { $state[$i[0].Name.TrimStart("/")] = $i[0] }
        }
        foreach ($s in $stats) {
            $mine = $s.Name -like "$Project-*"
            $mem = ($s.MemUsage -split "/")[0].Trim()
            $net = $s.NetIO -split "/"
            $blk = $s.BlockIO -split "/"
            $st = $state[$s.Name]
            $restarts = if ($st) { [int]$st.RestartCount } else { 0 }
            $row.containers += [ordered]@{
                name = $s.Name; mine = $mine; cpu = [double]($s.CPUPerc -replace "%", ""); mem_mb = [math]::Round((Parse-Size $mem), 1)
                mem_pct = [double]($s.MemPerc -replace "%", ""); net_in_mb = [math]::Round((Parse-Size $net[0].Trim()), 2); net_out_mb = [math]::Round((Parse-Size $net[1].Trim()), 2)
                disk_read_mb = [math]::Round((Parse-Size $blk[0].Trim()), 1); disk_write_mb = [math]::Round((Parse-Size $blk[1].Trim()), 1)
                pids = [int]$s.PIDs; restarts = $restarts; oom = [bool]($st.State.OOMKilled)
            }
            if ($mine) { $row.restarts_total += $restarts; if ($st.State.OOMKilled) { $row.oom = $true } } else { $row.others_restarts += $restarts }
        }
        $health = docker inspect -f "{{.State.Health.Status}}" "$Project-api-1" 2>$null
        $row.api_ok = ($health -eq "healthy")
        $q = docker exec "$Project-db-1" psql -U oap -d oap -tAc "select count(*), count(*) filter (where state='active'), count(*) filter (where wait_event_type='Lock'), pg_database_size('oap')/1048576 from pg_stat_activity where datname='oap'" 2>$null
        if ($q) {
            $p = ($q | Select-Object -First 1) -split "\|"
            $row.db = [ordered]@{ connections = [int]$p[0]; active = [int]$p[1]; waiting_on_lock = [int]$p[2]; size_mb = [int]$p[3] }
        }
    }
    return $row
}

$last = $null
$next = Get-Date
$pending = $listener.GetContextAsync()
try {
    while ($true) {
        if ((Get-Date) -ge $next) {
            $last = Sample
            ($last | ConvertTo-Json -Compress -Depth 6) | Add-Content -Path $out -Encoding UTF8
            $next = (Get-Date).AddSeconds($Every)
        }
        if ($pending.Wait(200)) {
            $ctx = $pending.Result
            $pending = $listener.GetContextAsync()
            $path = $ctx.Request.Url.AbsolutePath
            $body = $null
            if ($path -eq "/status/$Token" -and $last) { $body = ($last | ConvertTo-Json -Compress -Depth 6) }
            elseif ($path -eq "/metrics/$Token" -and (Test-Path $out)) { $body = [IO.File]::ReadAllText($out) }
            if ($null -eq $body) { $ctx.Response.StatusCode = 404; $body = "not found" }
            $bytes = [Text.Encoding]::UTF8.GetBytes($body)
            $ctx.Response.ContentType = "application/json"
            $ctx.Response.ContentLength64 = $bytes.Length
            $ctx.Response.OutputStream.Write($bytes, 0, $bytes.Length)
            $ctx.Response.Close()
        }
    }
}
finally {
    $listener.Stop()
    if ($Bind -ne "localhost") { Remove-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue }
    Write-Host "Monitor stopped, port closed. The notes are in $out" -ForegroundColor Yellow
}
