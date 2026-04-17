param(
    [string]$Destination = "..\StockClaw",
    [switch]$ForceClean
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$sourceRoot = Split-Path -Parent $PSScriptRoot
$destinationRoot = [System.IO.Path]::GetFullPath((Join-Path $sourceRoot $Destination))

function Normalize-RelativePath {
    param([string]$Path)

    $normalized = ($Path -replace "\\", "/")
    if ($normalized.StartsWith("./")) {
        $normalized = $normalized.Substring(2)
    }
    if ($normalized.StartsWith("/")) {
        $normalized = $normalized.Substring(1)
    }
    return $normalized.ToLowerInvariant()
}

function Get-RelativePath {
    param([string]$FullPath)

    $relative = $FullPath.Substring($sourceRoot.Length).TrimStart([char[]]@([char]92, [char]47))
    return $relative
}

$excludedDirectoryPrefixes = @(
    ".git/",
    ".venv/",
    ".vscode/",
    ".pytest_cache/",
    "cache/",
    "deploy/",
    "docs/interview-prep/",
    "docs/worklog/",
    "frontend/node_modules/",
    "frontend/.next/",
    "deploy/certs/",
    "langchain_agent/cache/",
    "langchain_agent/data/",
    "langchain_agent/db/",
    "scripts/"
)

$excludedExactFiles = @(
    "scripts/export-open-source.ps1",
    "deploy/readme.md",
    "deploy/atlas-images.tar.gz",
    "deploy/build-and-export.sh",
    "deploy/deploy.sh",
    "deploy/docker-compose.prod.yml",
    "docs/architecture_zh.md",
    "docs/blog-agent-harness.md",
    "docs/harness-architecture.md",
    "docs/interview-walkthrough.md",
    "docs/product-overview.md",
    "langchain_agent/docs/langchain_workflow.md",
    "langchain_agent/readme.md",
    "monitor/instruct.1019.md",
    "monitor/instruct.md",
    "monitor/readme.md",
    "_obb_install.txt",
    "_test.txt"
)

$allowedMarkdownFiles = @(
    "readme.md",
    "docs/architecture.md",
    "docs/local_deployment.md"
)

function Should-ExcludePath {
    param(
        [string]$RelativePath,
        [bool]$IsDirectory
    )

    $normalized = Normalize-RelativePath $RelativePath
    if ([string]::IsNullOrWhiteSpace($normalized)) {
        return $false
    }

    foreach ($prefix in $excludedDirectoryPrefixes) {
        $trimmedPrefix = $prefix.TrimEnd("/")
        if ($normalized -eq $trimmedPrefix -or $normalized.StartsWith($prefix)) {
            return $true
        }
    }

    if (-not $IsDirectory -and $excludedExactFiles -contains $normalized) {
        return $true
    }

    $leaf = [System.IO.Path]::GetFileName($normalized)
    if (-not $IsDirectory) {
        if ($leaf -eq ".env") { return $true }
        if ($leaf -like "*.local") { return $true }
        if ($leaf -like "*.db") { return $true }
        if ($leaf -like "*.db-shm") { return $true }
        if ($leaf -like "*.db-wal") { return $true }
        if ($leaf -like "*.tsbuildinfo") { return $true }
        if ($leaf -like "*.tar.gz") { return $true }
    }

    return $false
}

if (Test-Path -LiteralPath $destinationRoot) {
    $existingItems = @(Get-ChildItem -LiteralPath $destinationRoot -Force)
    if ($existingItems.Count -gt 0) {
        if (-not $ForceClean) {
            throw "Destination '$destinationRoot' is not empty. Re-run with -ForceClean to overwrite it."
        }
        $existingItems | Remove-Item -Recurse -Force
    }
} else {
    New-Item -ItemType Directory -Path $destinationRoot | Out-Null
}

$allDirectories = Get-ChildItem -LiteralPath $sourceRoot -Directory -Recurse -Force |
    Sort-Object { $_.FullName.Length }

foreach ($directory in $allDirectories) {
    $relativePath = Get-RelativePath -FullPath $directory.FullName
    if (Should-ExcludePath -RelativePath $relativePath -IsDirectory $true) {
        continue
    }
    $targetDirectory = Join-Path $destinationRoot $relativePath
    if (-not (Test-Path -LiteralPath $targetDirectory)) {
        New-Item -ItemType Directory -Path $targetDirectory | Out-Null
    }
}

$allFiles = Get-ChildItem -LiteralPath $sourceRoot -File -Recurse -Force
$copiedCount = 0

foreach ($file in $allFiles) {
    $relativePath = Get-RelativePath -FullPath $file.FullName
    if (Should-ExcludePath -RelativePath $relativePath -IsDirectory $false) {
        continue
    }

    $targetFile = Join-Path $destinationRoot $relativePath
    $targetParent = Split-Path -Parent $targetFile
    if (-not (Test-Path -LiteralPath $targetParent)) {
        New-Item -ItemType Directory -Path $targetParent | Out-Null
    }

    Copy-Item -LiteralPath $file.FullName -Destination $targetFile -Force
    $copiedCount += 1
}

foreach ($prefix in $excludedDirectoryPrefixes) {
    $trimmedPrefix = $prefix.TrimEnd("/")
    if ([string]::IsNullOrWhiteSpace($trimmedPrefix)) {
        continue
    }
    $targetDirectory = Join-Path $destinationRoot ($trimmedPrefix -replace "/", "\\")
    if (Test-Path -LiteralPath $targetDirectory) {
        Remove-Item -LiteralPath $targetDirectory -Recurse -Force
    }
}

foreach ($relativeFile in $excludedExactFiles) {
    $targetFile = Join-Path $destinationRoot ($relativeFile -replace "/", "\\")
    if (Test-Path -LiteralPath $targetFile) {
        Remove-Item -LiteralPath $targetFile -Force
    }
}

$exportedMarkdownFiles = Get-ChildItem -LiteralPath $destinationRoot -File -Recurse -Force -Filter *.md
foreach ($markdownFile in $exportedMarkdownFiles) {
    $relativePath = Get-RelativePath -FullPath $markdownFile.FullName
    $normalized = Normalize-RelativePath $relativePath
    if ($allowedMarkdownFiles -notcontains $normalized) {
        Remove-Item -LiteralPath $markdownFile.FullName -Force
    }
}

Write-Host "Open-source export created at: $destinationRoot"
Write-Host "Files copied: $copiedCount"
Write-Host "Suggested next steps:"
Write-Host "  1. Set-Location $destinationRoot"
Write-Host "  2. git init"
Write-Host "  3. git add ."
Write-Host "  4. git commit -m 'Initial open-source import'"
Write-Host "  5. git remote add origin <your StockClaw repo URL>"
Write-Host "  6. git push -u origin main"
