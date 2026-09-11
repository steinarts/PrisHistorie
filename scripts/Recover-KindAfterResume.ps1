$ErrorActionPreference = "Stop"

# ------------------------------------------------------------
# PrisHistorie kind recovery after Windows sleep/resume
# ------------------------------------------------------------

$Namespace = "prishistorie"
$CronJob   = "prishistorie-cron"

# CronJob schedule:
# 09:00, 10:00, 14:00, 18:00, 22:00 Europe/Oslo
$ScheduleHours = @(9, 10, 14, 18, 22)

# Hvor lenge vi venter på Docker/Kubernetes etter resume.
$StartupTimeoutSeconds = 120

# Litt slingringsmonn etter et planlagt tidspunkt.
# Hvis klokken f.eks. er 10:01 trenger vi ikke konkludere med feil ennå.
$ScheduleGraceMinutes = 5


function Write-Info($Message) {
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
}


function Wait-ForDocker {

    Write-Info "Venter på Docker Desktop..."

    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)

    while ((Get-Date) -lt $deadline) {

        try {
            docker info *> $null

            if ($LASTEXITCODE -eq 0) {
                Write-Info "Docker er tilgjengelig."
                return
            }
        }
        catch {
        }

        Start-Sleep -Seconds 5
    }

    throw "Docker ble ikke tilgjengelig innen $StartupTimeoutSeconds sekunder."
}


function Wait-ForKubernetes {

    Write-Info "Venter på Kubernetes API..."

    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)

    while ((Get-Date) -lt $deadline) {

        try {
            kubectl get --raw="/readyz" *> $null

            if ($LASTEXITCODE -eq 0) {
                Write-Info "Kubernetes API er tilgjengelig."
                return
            }
        }
        catch {
        }

        Start-Sleep -Seconds 5
    }

    throw "Kubernetes API ble ikke tilgjengelig innen $StartupTimeoutSeconds sekunder."
}


function Test-NodesReady {

    $nodes = kubectl get nodes -o json | ConvertFrom-Json

    foreach ($node in $nodes.items) {

        $readyCondition = $node.status.conditions |
            Where-Object { $_.type -eq "Ready" }

        if ($readyCondition.status -ne "True") {
            Write-Info "Node $($node.metadata.name) er IKKE Ready."
            return $false
        }
    }

    Write-Info "Alle Kubernetes-noder er Ready."
    return $true
}


function Get-ExpectedLastSchedule {

    # Windows timezone-id som tilsvarer Europe/Oslo.
    $timezone = [System.TimeZoneInfo]::FindSystemTimeZoneById(
        "W. Europe Standard Time"
    )

    $nowUtc   = [DateTime]::UtcNow
    $nowLocal = [System.TimeZoneInfo]::ConvertTimeFromUtc(
        $nowUtc,
        $timezone
    )

    $candidates = @()

    # I dag
    foreach ($hour in $ScheduleHours) {

        $localTime = [DateTime]::SpecifyKind(
            $nowLocal.Date.AddHours($hour),
            [DateTimeKind]::Unspecified
        )

        $utcTime = [System.TimeZoneInfo]::ConvertTimeToUtc(
            $localTime,
            $timezone
        )

        $candidates += $utcTime
    }

    # I går - nødvendig hvis scriptet kjører før kl. 09
    $yesterday = $nowLocal.Date.AddDays(-1)

    foreach ($hour in $ScheduleHours) {

        $localTime = [DateTime]::SpecifyKind(
            $yesterday.AddHours($hour),
            [DateTimeKind]::Unspecified
        )

        $utcTime = [System.TimeZoneInfo]::ConvertTimeToUtc(
            $localTime,
            $timezone
        )

        $candidates += $utcTime
    }

    $graceLimit = $nowUtc.AddMinutes(-$ScheduleGraceMinutes)

    return $candidates |
        Where-Object { $_ -le $graceLimit } |
        Sort-Object -Descending |
        Select-Object -First 1
}


function Get-LastCronSchedule {

    $value = kubectl get cronjob $CronJob `
        -n $Namespace `
        -o jsonpath="{.status.lastScheduleTime}"

    if ($LASTEXITCODE -ne 0) {
        throw "Kunne ikke lese CronJob $CronJob."
    }

    if ([string]::IsNullOrWhiteSpace($value)) {
        return $null
    }

    return [DateTime]::Parse(
        $value,
        $null,
        [System.Globalization.DateTimeStyles]::AdjustToUniversal
    ).ToUniversalTime()
}


function Start-RecoveryJob($ExpectedSchedule) {

    # ExpectedSchedule er UTC.
    # Vi bruker tidspunktet i jobbnavnet slik at samme schedule
    # ikke får flere recovery-jobs.
    $scheduleText = $ExpectedSchedule.ToString("yyyyMMdd-HHmm")

    $jobName = "prishistorie-recovery-$scheduleText"

    Write-Info "Sjekker om recovery-jobben finnes: $jobName"

    $existing = kubectl get job $jobName `
        -n $Namespace `
        --ignore-not-found `
        -o name

    if (-not [string]::IsNullOrWhiteSpace($existing)) {
        Write-Info "Recovery-jobben finnes allerede. Starter ikke en ny."
        return
    }

    Write-Info "Oppretter recovery-jobb for manglende schedule:"
    Write-Info "$ExpectedSchedule UTC"

    kubectl create job `
        --from=cronjob/$CronJob `
        $jobName `
        -n $Namespace

    if ($LASTEXITCODE -ne 0) {
        throw "Kunne ikke opprette recovery-jobb."
    }

    Write-Info "Recovery-jobb opprettet: $jobName"
}

function Test-PrisHistorieJobRunning {

    $activeJobs = kubectl get jobs `
        -n $Namespace `
        -o json |
        ConvertFrom-Json

    foreach ($job in $activeJobs.items) {

        $name = $job.metadata.name

        if (
            ($name -like "prishistorie-cron-*") -or
            ($name -like "prishistorie-recovery-*")
        ) {

            if ($job.status.active -gt 0) {
                Write-Info "Aktiv PrisHistorie-jobb finnes: $name"
                return $true
            }
        }
    }

    return $false
}

# ============================================================
# MAIN
# ============================================================

try {

    Write-Info "Starter recovery-kontroll."

    Wait-ForDocker
    Wait-ForKubernetes

    if (-not (Test-NodesReady)) {
        throw "En eller flere Kubernetes-noder er ikke Ready."
    }

    $expected = Get-ExpectedLastSchedule
    $actual   = Get-LastCronSchedule

    Write-Info "Forventet siste schedule (UTC): $expected"

    if ($null -eq $actual) {

        Write-Info "CronJob har ingen LastScheduleTime."
        $needsRecovery = $true
    }
    else {

        Write-Info "Registrert siste schedule (UTC): $actual"

        if ($actual -lt $expected) {

            Write-Info "CronJob ligger etter forventet schedule."
            $needsRecovery = $true
        }
        else {

            Write-Info "CronJob schedule ser frisk ut."
            $needsRecovery = $false
        }
    }

    if ($needsRecovery) {

        Write-Info "CronJob har mistet minst én planlagt kjøring."

        if (Test-PrisHistorieJobRunning) {
            Write-Info "Starter ikke recovery fordi en PrisHistorie-jobb allerede kjører."
        }
        else {
            Start-RecoveryJob $expected
        }

        Start-Sleep -Seconds 3

        Write-Info "Job-status etter recovery:"

        kubectl get jobs -n $Namespace `
            --sort-by=.metadata.creationTimestamp
    }
    else {

        Write-Info "Ingen recovery nødvendig."
    }

    Write-Info "Recovery-kontroll ferdig."
    exit 0
}
catch {

    Write-Error "Recovery feilet: $($_.Exception.Message)"
    exit 1
}