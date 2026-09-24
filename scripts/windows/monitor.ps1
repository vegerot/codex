param([int]$CargoPid, [string]$OutputPath)
$ErrorActionPreference = 'Stop'

$logical = (Get-CimInstance Win32_ComputerSystem).NumberOfLogicalProcessors
$previousCpu = @{}
$previousAt = Get-Date
$sample = 0
while (Get-Process -Id $CargoPid -ErrorAction SilentlyContinue) {
    $now = Get-Date
    $cpu = Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor -Filter "Name='_Total'"
    $memory = Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory
    $processes = @(Get-Process cargo,rustc,cl,link,rust-lld,cmake,ninja -ErrorAction SilentlyContinue)
    $cpuSeconds = 0.0
    $currentCpu = @{}
    foreach ($process in $processes) {
        $currentCpu[$process.Id] = $process.CPU
        if ($previousCpu.ContainsKey($process.Id)) { $cpuSeconds += [Math]::Max(0, $process.CPU - $previousCpu[$process.Id]) }
    }
    $elapsed = ($now - $previousAt).TotalSeconds
    $row = [pscustomobject]@{
        timestamp = $now.ToString('o')
        cpu_total_percent = $cpu.PercentProcessorTime
        build_cpu_percent_lower_bound = [Math]::Round(100 * $cpuSeconds / $elapsed / $logical, 1)
        available_gib = [Math]::Round($memory.AvailableMBytes / 1024, 2)
        committed_percent = $memory.PercentCommittedBytesInUse
        build_working_set_gib = [Math]::Round(($processes | Measure-Object WorkingSet64 -Sum).Sum / 1GB, 2)
        rustc_count = @($processes | Where-Object ProcessName -eq rustc).Count
        build_process_count = $processes.Count
    }
    $row | Export-Csv $OutputPath -Append -NoTypeInformation
    if ($sample % 6 -eq 0) { $row | ConvertTo-Json -Compress }
    $previousCpu = $currentCpu
    $previousAt = $now
    $sample++
    Start-Sleep -Seconds 5
}
