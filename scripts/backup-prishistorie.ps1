$ErrorActionPreference = "Stop"

# ------------------------------------------------------------
# Konfigurasjon
# ------------------------------------------------------------

$Namespace  = "prishistorie"
$SecretName = "prishistorie-postgres-secret"
$BackupDir  = "C:\docker-backup\PrisHistorie"

# Lokal port som brukes midlertidig av kubectl port-forward.
# PostgreSQL inne i Kubernetes bruker fortsatt 5432.
$LocalPort  = 15432
$RemotePort = 5432

$PortForwardProcess = $null


# ------------------------------------------------------------
# Hjelpefunksjon for å hente verdier fra Kubernetes Secret
# ------------------------------------------------------------

function Get-KubernetesSecretValue {
    param (
        [Parameter(Mandatory = $true)]
        [string]$Key
    )

    $EncodedValue = kubectl get secret $SecretName `
        -n $Namespace `
        -o "jsonpath={.data.$Key}"

    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($EncodedValue)) {
        throw "Kunne ikke hente '$Key' fra Kubernetes Secret '$SecretName'."
    }

    return [System.Text.Encoding]::UTF8.GetString(
        [System.Convert]::FromBase64String($EncodedValue)
    )
}


try {

    # --------------------------------------------------------
    # 1. Sjekk nødvendige programmer
    # --------------------------------------------------------

    if (-not (Get-Command kubectl -ErrorAction SilentlyContinue)) {
        throw "kubectl ble ikke funnet."
    }


    # --------------------------------------------------------
    # 2. Opprett backup-mappen dersom den ikke finnes
    # --------------------------------------------------------

    if (-not (Test-Path $BackupDir)) {
        New-Item `
            -ItemType Directory `
            -Path $BackupDir `
            -Force | Out-Null
    }


    # --------------------------------------------------------
    # 3. Hent databaseinformasjon fra Kubernetes Secret
    # --------------------------------------------------------

    Write-Host "Henter databaseinformasjon fra Kubernetes..."

    $Database = Get-KubernetesSecretValue "POSTGRES_DB"
    $Username = Get-KubernetesSecretValue "POSTGRES_USER"
    $Password = Get-KubernetesSecretValue "POSTGRES_PASSWORD"

    # pg_dump leser denne automatisk.
    $env:PGPASSWORD = $Password


    # --------------------------------------------------------
    # 4. Start kubectl port-forward
    # --------------------------------------------------------

    Write-Host "Starter port-forward localhost:$LocalPort -> PostgreSQL:$RemotePort..."

    $PortForwardProcess = Start-Process `
        -FilePath "kubectl" `
        -ArgumentList @(
            "port-forward",
            "-n", $Namespace,
            "svc/prishistorie-postgres",
            "${LocalPort}:${RemotePort}"
        ) `
        -PassThru `
        -WindowStyle Hidden


    # --------------------------------------------------------
    # 5. Vent til port-forward faktisk er klar
    # --------------------------------------------------------

    Write-Host "Venter på PostgreSQL..."

    $Ready = $false

    for ($i = 0; $i -lt 20; $i++) {

        if ($PortForwardProcess.HasExited) {
            throw "kubectl port-forward stoppet uventet."
        }

        if (Test-NetConnection `
                -ComputerName "127.0.0.1" `
                -Port $LocalPort `
                -InformationLevel Quiet `
                -WarningAction SilentlyContinue) {

            $Ready = $true
            break
        }

        Start-Sleep -Seconds 1
    }

    if (-not $Ready) {
        throw "PostgreSQL ble ikke tilgjengelig på localhost:$LocalPort."
    }


    # --------------------------------------------------------
    # 6. Lag filnavn
    # --------------------------------------------------------

    $Timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"

    $BackupFile = Join-Path `
        $BackupDir `
        "prishistorie-$Timestamp.dump"


    # --------------------------------------------------------
    # 7. Ta backup
    # --------------------------------------------------------

    Write-Host "Starter PostgreSQL-backup..."

    docker run --rm `
        --network host `
        -e PGPASSWORD="$Password" `
        postgres:17 `
        pg_dump `
            -h host.docker.internal `
            -p $LocalPort `
            -U $Username `
            -d $Database `
            --format=custom `
            --file=/tmp/backup.dump


    docker run --rm `
        -e PGPASSWORD="$Password" `
        -v "${BackupDir}:/backup" `
        postgres:17 `
        pg_dump `
            -h host.docker.internal `
            -p $LocalPort `
            -U $Username `
            -d $Database `
            --format=custom `
            --file="/backup/prishistorie-$Timestamp.dump"            

    if ($LASTEXITCODE -ne 0) {
        throw "pg_dump feilet med exit code $LASTEXITCODE."
    }


    # --------------------------------------------------------
    # 8. Kontroller resultatet
    # --------------------------------------------------------

    if (-not (Test-Path $BackupFile)) {
        throw "pg_dump rapporterte OK, men backupfilen finnes ikke."
    }

    $Backup = Get-Item $BackupFile

    if ($Backup.Length -eq 0) {
        throw "Backupfilen er tom."
    }


    Write-Host ""
    Write-Host "Backup fullført."
    Write-Host "Fil: $($Backup.FullName)"
    Write-Host "Størrelse: $([math]::Round($Backup.Length / 1MB, 2)) MB"
}

catch {

    Write-Error "Backup feilet: $($_.Exception.Message)"

    exit 1
}

finally {

    # --------------------------------------------------------
    # 9. Stopp port-forward
    # --------------------------------------------------------

    if ($null -ne $PortForwardProcess) {

        if (-not $PortForwardProcess.HasExited) {

            Write-Host "Stopper port-forward..."

            Stop-Process `
                -Id $PortForwardProcess.Id `
                -Force `
                -ErrorAction SilentlyContinue
        }
    }


    # --------------------------------------------------------
    # 10. Fjern passord fra miljøet
    # --------------------------------------------------------

    Remove-Item `
        Env:\PGPASSWORD `
        -ErrorAction SilentlyContinue

    $Password = $null
}