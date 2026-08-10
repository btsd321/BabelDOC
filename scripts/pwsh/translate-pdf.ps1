# BabelDOC PDF Translation Script
# This script wraps the babeldoc command with configurable parameters
# Priority: Command line arguments > In-file configuration

# ============================================
# Environment Setup
# ============================================
# Add uv tools to PATH
$env:Path = "C:\Users\11233\.local\bin;$env:Path"

# Check if babeldoc is installed
$babeldocExists = Get-Command babeldoc -ErrorAction SilentlyContinue
if (-not $babeldocExists) {
    Write-Host "BabelDOC not found. Installing via uv..." -ForegroundColor Yellow
    & uv tool install --python 3.12 BabelDOC

    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to install BabelDOC" -ForegroundColor Red
        exit 1
    }

    Write-Host "BabelDOC installed successfully!" -ForegroundColor Green
    Write-Host ""
}

# ============================================
# Default Configuration (Edit these values)
# ============================================
$Config = @{
    # Translation Service
    OpenAI = $true
    OpenAIModel = "gpt-4o-mini"
    OpenAIBaseUrl = "https://api.openai.com/v1"
    OpenAIApiKey = "your-api-key-here"

    # Language Options
    LangIn = "en"
    LangOut = "zh"

    # PDF Files (can be overridden by command line)
    Files = @()

    # PDF Processing Options
    Pages = $null
    QPS = 4
    OutputDir = $null

    # Advanced Options
    SplitShortLines = $false
    SkipClean = $false
    DualTranslateFirst = $false
    DisableRichTextTranslate = $false
    UseAlternatingPagesDual = $false
    WatermarkOutputMode = "watermarked"  # watermarked, no_watermark, both
    MaxPagesPerPart = $null
    SkipScannedDetection = $false
    OCRWorkaround = $false
    AutoEnableOCRWorkaround = $false
    OnlyIncludeTranslatedPage = $false

    # Translation Options
    NoDual = $false
    NoMono = $false
    MinTextLength = 5
    IgnoreCache = $false
    CustomSystemPrompt = $null

    # Glossary
    GlossaryFiles = $null

    # Other
    Debug = $false
    ConfigFile = $null
}

# ============================================
# Command Line Parameters
# ============================================
param(
    [string[]]$Files,
    [string]$OpenAIModel,
    [string]$OpenAIBaseUrl,
    [string]$OpenAIApiKey,
    [string]$LangIn,
    [string]$LangOut,
    [string]$Pages,
    [int]$QPS,
    [string]$OutputDir,
    [string]$WatermarkOutputMode,
    [int]$MaxPagesPerPart,
    [switch]$SplitShortLines,
    [switch]$SkipClean,
    [switch]$DualTranslateFirst,
    [switch]$DisableRichTextTranslate,
    [switch]$UseAlternatingPagesDual,
    [switch]$SkipScannedDetection,
    [switch]$OCRWorkaround,
    [switch]$AutoEnableOCRWorkaround,
    [switch]$OnlyIncludeTranslatedPage,
    [switch]$NoDual,
    [switch]$NoMono,
    [int]$MinTextLength,
    [switch]$IgnoreCache,
    [string]$CustomSystemPrompt,
    [string]$GlossaryFiles,
    [switch]$Debug,
    [string]$ConfigFile
)

# ============================================
# Override Configuration with Command Line Parameters
# ============================================
if ($PSBoundParameters.ContainsKey('Files')) { $Config.Files = $Files }
if ($PSBoundParameters.ContainsKey('OpenAIModel')) { $Config.OpenAIModel = $OpenAIModel }
if ($PSBoundParameters.ContainsKey('OpenAIBaseUrl')) { $Config.OpenAIBaseUrl = $OpenAIBaseUrl }
if ($PSBoundParameters.ContainsKey('OpenAIApiKey')) { $Config.OpenAIApiKey = $OpenAIApiKey }
if ($PSBoundParameters.ContainsKey('LangIn')) { $Config.LangIn = $LangIn }
if ($PSBoundParameters.ContainsKey('LangOut')) { $Config.LangOut = $LangOut }
if ($PSBoundParameters.ContainsKey('Pages')) { $Config.Pages = $Pages }
if ($PSBoundParameters.ContainsKey('QPS')) { $Config.QPS = $QPS }
if ($PSBoundParameters.ContainsKey('OutputDir')) { $Config.OutputDir = $OutputDir }
if ($PSBoundParameters.ContainsKey('WatermarkOutputMode')) { $Config.WatermarkOutputMode = $WatermarkOutputMode }
if ($PSBoundParameters.ContainsKey('MaxPagesPerPart')) { $Config.MaxPagesPerPart = $MaxPagesPerPart }
if ($PSBoundParameters.ContainsKey('SplitShortLines')) { $Config.SplitShortLines = $SplitShortLines }
if ($PSBoundParameters.ContainsKey('SkipClean')) { $Config.SkipClean = $SkipClean }
if ($PSBoundParameters.ContainsKey('DualTranslateFirst')) { $Config.DualTranslateFirst = $DualTranslateFirst }
if ($PSBoundParameters.ContainsKey('DisableRichTextTranslate')) { $Config.DisableRichTextTranslate = $DisableRichTextTranslate }
if ($PSBoundParameters.ContainsKey('UseAlternatingPagesDual')) { $Config.UseAlternatingPagesDual = $UseAlternatingPagesDual }
if ($PSBoundParameters.ContainsKey('SkipScannedDetection')) { $Config.SkipScannedDetection = $SkipScannedDetection }
if ($PSBoundParameters.ContainsKey('OCRWorkaround')) { $Config.OCRWorkaround = $OCRWorkaround }
if ($PSBoundParameters.ContainsKey('AutoEnableOCRWorkaround')) { $Config.AutoEnableOCRWorkaround = $AutoEnableOCRWorkaround }
if ($PSBoundParameters.ContainsKey('OnlyIncludeTranslatedPage')) { $Config.OnlyIncludeTranslatedPage = $OnlyIncludeTranslatedPage }
if ($PSBoundParameters.ContainsKey('NoDual')) { $Config.NoDual = $NoDual }
if ($PSBoundParameters.ContainsKey('NoMono')) { $Config.NoMono = $NoMono }
if ($PSBoundParameters.ContainsKey('MinTextLength')) { $Config.MinTextLength = $MinTextLength }
if ($PSBoundParameters.ContainsKey('IgnoreCache')) { $Config.IgnoreCache = $IgnoreCache }
if ($PSBoundParameters.ContainsKey('CustomSystemPrompt')) { $Config.CustomSystemPrompt = $CustomSystemPrompt }
if ($PSBoundParameters.ContainsKey('GlossaryFiles')) { $Config.GlossaryFiles = $GlossaryFiles }
if ($PSBoundParameters.ContainsKey('Debug')) { $Config.Debug = $Debug }
if ($PSBoundParameters.ContainsKey('ConfigFile')) { $Config.ConfigFile = $ConfigFile }

# ============================================
# Validate Required Parameters
# ============================================
if ($Config.Files.Count -eq 0) {
    Write-Host "Error: No PDF files specified!" -ForegroundColor Red
    Write-Host "Usage: .\translate-pdf.ps1 -Files file1.pdf,file2.pdf [other options]"
    Write-Host "Or configure the Files array in the script."
    exit 1
}

if ($Config.OpenAIApiKey -eq "your-api-key-here") {
    Write-Host "Warning: Please configure your OpenAI API key!" -ForegroundColor Yellow
    Write-Host "Edit the script or use -OpenAIApiKey parameter"
}

# ============================================
# Build Command
# ============================================
$cmd = "babeldoc"
$args = @()

# Files
foreach ($file in $Config.Files) {
    $args += "--files"
    $args += $file
}

# OpenAI Configuration
if ($Config.OpenAI) {
    $args += "--openai"
}
$args += "--openai-model"
$args += $Config.OpenAIModel
$args += "--openai-base-url"
$args += $Config.OpenAIBaseUrl
$args += "--openai-api-key"
$args += $Config.OpenAIApiKey

# Language Options
$args += "--lang-in"
$args += $Config.LangIn
$args += "--lang-out"
$args += $Config.LangOut

# Pages
if ($Config.Pages) {
    $args += "--pages"
    $args += $Config.Pages
}

# QPS
$args += "--qps"
$args += $Config.QPS

# Output Directory
if ($Config.OutputDir) {
    $args += "--output"
    $args += $Config.OutputDir
}

# Watermark Mode
$args += "--watermark-output-mode"
$args += $Config.WatermarkOutputMode

# Max Pages Per Part
if ($Config.MaxPagesPerPart) {
    $args += "--max-pages-per-part"
    $args += $Config.MaxPagesPerPart
}

# Boolean Flags
if ($Config.SplitShortLines) { $args += "--split-short-lines" }
if ($Config.SkipClean) { $args += "--skip-clean" }
if ($Config.DualTranslateFirst) { $args += "--dual-translate-first" }
if ($Config.DisableRichTextTranslate) { $args += "--disable-rich-text-translate" }
if ($Config.UseAlternatingPagesDual) { $args += "--use-alternating-pages-dual" }
if ($Config.SkipScannedDetection) { $args += "--skip-scanned-detection" }
if ($Config.OCRWorkaround) { $args += "--ocr-workaround" }
if ($Config.AutoEnableOCRWorkaround) { $args += "--auto-enable-ocr-workaround" }
if ($Config.OnlyIncludeTranslatedPage) { $args += "--only-include-translated-page" }
if ($Config.NoDual) { $args += "--no-dual" }
if ($Config.NoMono) { $args += "--no-mono" }
if ($Config.IgnoreCache) { $args += "--ignore-cache" }
if ($Config.Debug) { $args += "--debug" }

# Min Text Length
$args += "--min-text-length"
$args += $Config.MinTextLength

# Custom System Prompt
if ($Config.CustomSystemPrompt) {
    $args += "--custom-system-prompt"
    $args += $Config.CustomSystemPrompt
}

# Glossary Files
if ($Config.GlossaryFiles) {
    $args += "--glossary-files"
    $args += $Config.GlossaryFiles
}

# Config File
if ($Config.ConfigFile) {
    $args += "--config"
    $args += $Config.ConfigFile
}

# ============================================
# Execute Command
# ============================================
Write-Host "Executing BabelDOC translation..." -ForegroundColor Cyan
Write-Host "Command: $cmd $($args -join ' ')" -ForegroundColor Gray
Write-Host ""

& $cmd $args

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Translation completed successfully!" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "Translation failed with exit code $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}
