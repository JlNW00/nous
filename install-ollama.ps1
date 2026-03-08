# Install Ollama and start reasoning layer for crypto-investigator
# Run this in PowerShell as Administrator

Write-Host "Installing Ollama for free LLM reasoning..." -ForegroundColor Green

# Check if Ollama is already installed
if (Test-Path "C:\Users\$env:USERNAME\AppData\Local\Programs\Ollama\ollama.exe") {
    Write-Host "Ollama already installed!" -ForegroundColor Yellow
    $OllamaPath = "C:\Users\$env:USERNAME\AppData\Local\Programs\Ollama"
} else {
    Write-Host "Downloading Ollama installer..." -ForegroundColor Green
    $DownloadUrl = "https://ollama.ai/download/OllamaSetup.exe"
    $InstallerPath = "$env:TEMP\OllamaSetup.exe"

    # Download
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    Invoke-WebRequest -Uri $DownloadUrl -OutFile $InstallerPath -ErrorAction Stop

    Write-Host "Running installer..." -ForegroundColor Green
    Start-Process $InstallerPath -Wait

    $OllamaPath = "C:\Users\$env:USERNAME\AppData\Local\Programs\Ollama"
}

# Start Ollama service
Write-Host "Starting Ollama..." -ForegroundColor Green

# Check if service exists
$ServiceExists = Get-Service -Name "OllamaService" -ErrorAction SilentlyContinue

if ($ServiceExists) {
    Start-Service -Name "OllamaService" -ErrorAction SilentlyContinue
    Write-Host "Ollama service started" -ForegroundColor Green
} else {
    # Run Ollama directly
    Start-Process -FilePath "$OllamaPath\ollama.exe" -NoNewWindow -PassThru | Out-Null
    Write-Host "Ollama running in background" -ForegroundColor Green
}

# Wait for Ollama to be ready
Write-Host "Waiting for Ollama to start..." -ForegroundColor Yellow
$MaxRetries = 30
$Retry = 0
while ($Retry -lt $MaxRetries) {
    try {
        $Response = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -ErrorAction SilentlyContinue
        Write-Host "Ollama is running!" -ForegroundColor Green
        break
    } catch {
        $Retry++
        Start-Sleep -Seconds 1
    }
}

if ($Retry -eq $MaxRetries) {
    Write-Host "Ollama didn't start. Try running: ollama serve" -ForegroundColor Red
    exit 1
}

# Pull llama3:8b model
Write-Host "Downloading llama3:8b model (this may take a minute)..." -ForegroundColor Green
& "$OllamaPath\ollama.exe" pull llama3:8b

Write-Host "`n✅ Ollama is ready!" -ForegroundColor Green
Write-Host "Your crypto investigator now uses FREE local AI reasoning." -ForegroundColor Green
Write-Host "No API costs, instant responses, private data.`n" -ForegroundColor Cyan

Write-Host "You can now start the API server and run investigations!" -ForegroundColor Yellow
Write-Host "The system will automatically use local reasoning." -ForegroundColor Yellow
