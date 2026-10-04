# Script de configuracao para Qwen 3.5 Multimodal (Ollama & LM Studio)
# Executa de forma portavel resolvendo caminhos com base no perfil do usuario atual.

$ErrorActionPreference = "Stop"
$userProfile = [System.Environment]::GetFolderPath('UserProfile')
$lmStudioDir = Join-Path $userProfile ".lmstudio\models\unsloth\Qwen3.5-9B-GGUF"
$modelFile = Join-Path $lmStudioDir "Qwen3.5-9B-GGUF-UD-Q4_K_XL.gguf"
$projectorFile = Join-Path $lmStudioDir "mmproj-F16.gguf"
$ollamaAppDir = Join-Path $userProfile "AppData\Local\Programs\Ollama"
$ollamaExe = Join-Path $ollamaAppDir "ollama.exe"
$ollamaBlobsDir = Join-Path $userProfile ".ollama\models\blobs"

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   CONFIGURADOR DE MOTOR DE VISAO (OLLAMA & LM STUDIO)    " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Verifica/cria o diretorio do LM Studio
if (-not (Test-Path $lmStudioDir)) {
    Write-Host "[*] Criando diretorio do LM Studio em:" -ForegroundColor Yellow
    Write-Host "    $lmStudioDir" -ForegroundColor Gray
    New-Item -ItemType Directory -Path $lmStudioDir -Force | Out-Null
}

# 2. Verifica se o GGUF principal esta na pasta
if (-not (Test-Path $modelFile)) {
    Write-Host "[!] ATENCAO: O modelo principal nao foi encontrado em:" -ForegroundColor Red
    Write-Host "    $modelFile" -ForegroundColor Red
    Write-Host "    Buscando se ha algum outro GGUF na pasta do LM Studio..." -ForegroundColor Yellow
    
    $otherGguf = Get-ChildItem -Path $lmStudioDir -Filter "*.gguf" | Where-Object { $_.Name -like "*Qwen3.5-9B*" -and $_.Name -notlike "*mmproj*" } | Select-Object -First 1
    
    if ($otherGguf) {
        $modelFile = $otherGguf.FullName
        Write-Host "[+] Modelo principal alternativo encontrado: $($otherGguf.Name)" -ForegroundColor Green
    } else {
        Write-Host "[!] ERRO: Nenhum modelo Qwen3.5 GGUF encontrado na pasta do LM Studio." -ForegroundColor Red
        Write-Host "    Por favor, coloque o arquivo de modelo GGUF no diretorio:" -ForegroundColor Gray
        Write-Host "    $lmStudioDir" -ForegroundColor Gray
        Exit
    }
} else {
    Write-Host "[+] Modelo principal GGUF encontrado: Qwen3.5-9B-GGUF-UD-Q4_K_XL.gguf" -ForegroundColor Green
}

# 3. Verifica/copia/baixa o projetor multimodal
if (-not (Test-Path $projectorFile)) {
    Write-Host "[*] Projetor mmproj-F16.gguf nao encontrado no diretorio do LM Studio." -ForegroundColor Yellow
    Write-Host "[*] Procurando nos blobs de cache do Ollama..." -ForegroundColor Yellow
    
    $foundBlob = $null
    if (Test-Path $ollamaBlobsDir) {
        $blobs = Get-ChildItem -Path $ollamaBlobsDir -File
        foreach ($blob in $blobs) {
            # O projector F16 original possui exatamente 921705024 bytes (879 MiB)
            if ($blob.Length -eq 921705024) {
                $foundBlob = $blob.FullName
                break
            }
        }
    }
    
    if ($foundBlob) {
        Write-Host "[+] Projetor compativel localizado nos blobs do Ollama!" -ForegroundColor Green
        Write-Host "[*] Copiando projetor para a pasta do LM Studio..." -ForegroundColor Yellow
        Copy-Item -Path $foundBlob -Destination $projectorFile -Force
        Write-Host "[+] Copia concluida." -ForegroundColor Green
    } else {
        Write-Host "[*] Baixando mmproj-F16.gguf do Hugging Face..." -ForegroundColor Yellow
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $url = "https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/main/mmproj-F16.gguf"
        try {
            $webClient = New-Object System.Net.WebClient
            $webClient.Headers.Add("User-Agent", "Mozilla/5.0")
            Write-Host "    Destino: $projectorFile" -ForegroundColor Gray
            $webClient.DownloadFile($url, $projectorFile)
            Write-Host "[+] Download concluido com sucesso!" -ForegroundColor Green
        } catch {
            Write-Host "[!] Falha ao baixar o projetor de visao automaticamente: $_" -ForegroundColor Red
            Write-Host "    Faca o download manual em: $url" -ForegroundColor Gray
            Write-Host "    E salve o arquivo como 'mmproj-F16.gguf' na pasta do modelo." -ForegroundColor Gray
            Exit
        }
    }
} else {
    Write-Host "[+] Projetor de visao (mmproj-F16.gguf) encontrado na pasta do modelo." -ForegroundColor Green
}

# 4. Cria o Modelfile para o Ollama
Write-Host "[*] Escrevendo Modelfile..." -ForegroundColor Yellow
$modelfileContent = @"
FROM $modelFile
ADAPTER $projectorFile
TEMPLATE "{{ .Prompt }}"
"@

# Salva na pasta do script atual
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
if (-not $scriptDir) { $scriptDir = "." }
$modelfilePath = Join-Path $scriptDir "Modelfile"
Set-Content -Path $modelfilePath -Value $modelfileContent -Encoding UTF8
Write-Host "[+] Modelfile gerado em: $modelfilePath" -ForegroundColor Green

# 5. Verifica se o executavel do Ollama esta no local padrao
if (-not (Test-Path $ollamaExe)) {
    Write-Host "[*] Ollama nao encontrado no local padrao. Tentando encontrar no PATH do sistema..." -ForegroundColor Yellow
    $ollamaExe = "ollama"
}

# 6. Registra/Atualiza o modelo no Ollama
Write-Host "[*] Registrando modelo 'qwen3.5-9b-custom:latest' no Ollama..." -ForegroundColor Yellow
try {
    & $ollamaExe create qwen3.5-9b-custom:latest -f $modelfilePath
    Write-Host "[+] Modelo registrado e ativado no Ollama com sucesso!" -ForegroundColor Green
} catch {
    Write-Host "[!] ERRO ao registrar o modelo no Ollama: $_" -ForegroundColor Red
    Write-Host "    Certifique-se de que o aplicativo do Ollama esta aberto e ativo na barra de tarefas." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   PROCESSO CONCLUIDO!                                    " -ForegroundColor Cyan
Write-Host "   O modelo agora e funcional para LM Studio e Ollama.    " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
