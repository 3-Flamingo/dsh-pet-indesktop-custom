# -*- coding: utf-8 -*-
<#
.SYNOPSIS
    一键「ruff + 聚焦测试 → PyInstaller onedir → 换部署 → 重启验证」重建脚本。

.DESCRIPTION
    把「改完源码到新版本跑起来」这条链固化，省掉每次手工装依赖、补素材、
    摆路径的时间。默认按仓库布局推导路径，也可以用参数覆盖：

      <repo>\tools\rebuild.ps1                       本脚本
      <repo>\assets\characters\<角色>\frameseq\       帧序列素材（构建硬门要求，不在 git 里）
      <repo>\dist-onedir\<AppName>\                  PyInstaller 产物（保留，供 -SkipBuild 复用）
      <deploy>\<AppName>.exe                        部署目录（默认 <repo>\deploy）

    前置：Python 3.11 环境已装好依赖（pip install -r requirements.txt pyinstaller），
    且 frameseq 素材齐备（否则上游 build_onedir.ps1 的硬门会中止）。

.PARAMETER Source
    源码根目录。默认：本脚本所在 tools 目录的上一级。

.PARAMETER Python
    用于测试与打包的解释器。默认：<repo>\.venv\Scripts\python.exe，不存在时退回 PATH 上的 python。

.PARAMETER DeployTo
    部署目录（换部署后在此运行 exe）。默认：<repo>\deploy。

.PARAMETER AppName
    变体名。默认 dsh-pet-standalone-webm-chat。

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\rebuild.ps1 -SkipTests

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\rebuild.ps1 -SkipBuild -NoRestart

.NOTES
    退出码：0 成功；1 测试失败；2 构建失败；3 部署或启动失败。
#>
param(
    [string]$Source = '',
    [string]$Python = '',
    [string]$DeployTo = '',
    [string]$AppName = 'dsh-pet-standalone-webm-chat',
    [switch]$SkipTests,
    [switch]$SkipBuild,
    [switch]$NoRestart
)

$ErrorActionPreference = 'Stop'
$Stamp = (Get-Date).ToString('yyyyMMdd-HHmmss')

$ToolsDir = Split-Path -Parent $PSCommandPath
if (-not $Source) { $Source = Split-Path -Parent $ToolsDir }
if (-not $Python) {
    $venvPy = Join-Path $Source '.venv\Scripts\python.exe'
    if (Test-Path $venvPy) { $Python = $venvPy } else { $Python = 'python' }
}
if (-not $DeployTo) { $DeployTo = Join-Path $Source 'deploy' }

$LogDir = Join-Path $Source 'build-logs'
$Dist   = Join-Path $Source "dist-onedir\$AppName"
$Exe    = Join-Path $DeployTo "$AppName.exe"
$Log    = Join-Path $LogDir "rebuild-$Stamp.log"

if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
Start-Transcript -Path $Log -Force | Out-Null

function Step([string]$Text) { Write-Host ''; Write-Host "=== $Text ===" -ForegroundColor Cyan }

function Fail([int]$Code, [string]$Text) {
    Write-Host ''
    Write-Host "FAILED: $Text" -ForegroundColor Red
    Write-Host "日志：$Log" -ForegroundColor Yellow
    Stop-Transcript | Out-Null
    exit $Code
}

# 外部命令统一走这里：PS 5.1 下 EAP=Stop 会把子进程 stderr 当成终止错误
# （PyInstaller 的日志全在 stderr，直接调用会在第 2 步误判失败）。
function Run-External {
    param(
        [Parameter(Mandatory = $true)][string]$Exe,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [string]$WorkDir = $Source
    )
    $eap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    Push-Location $WorkDir
    try {
        $lines = & $Exe @Arguments 2>&1
        $code = $LASTEXITCODE
    } finally {
        Pop-Location
        $ErrorActionPreference = $eap
    }
    return [pscustomobject]@{ Lines = @($lines); Code = $code }
}

$t0 = Get-Date
Write-Host "重建 $Stamp" -ForegroundColor Green
Write-Host "源码 $Source"
Write-Host "解释器 $Python"
Write-Host "部署 $DeployTo"

# 上游 build_onedir.ps1 直接调 `python`，所以先把同一个解释器目录放到 PATH 最前面
$PyDir = Split-Path -Parent $Python
if ($PyDir -and (Test-Path $PyDir)) { $env:PATH = "$PyDir;$env:PATH" }

$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:QT_QPA_PLATFORM = 'offscreen'   # 仅测试用；打包的冒烟测试要真实窗口，第 2 步前必须清掉

# ---------------------------------------------------------------- 1. 静态检查 + 聚焦测试
if (-not $SkipTests) {
    Step '[1/5] ruff + 聚焦回归'
    $ruff = Run-External -Exe $Python -Arguments @('-m', 'ruff', 'check', 'pet', 'tests')
    if ($ruff.Code -ne 0) { Fail 1 ('ruff 未通过：' + ($ruff.Lines -join [Environment]::NewLine)) }

    $focus = @(
        'tests/test_menu_dismiss.py',
        'tests/test_weather.py',
        'tests/test_weather_fallback.py',
        'tests/test_context_menu_lifecycle.py',
        'tests/test_sprite_menu.py'
    )
    $py = Run-External -Exe $Python -Arguments (@('-m', 'pytest', '-q') + $focus)
    if ($py.Code -ne 0) { Fail 1 ('聚焦测试未通过：' + ($py.Lines -join [Environment]::NewLine)) }
    $py.Lines | Select-Object -Last 2 | Write-Host -ForegroundColor DarkGray
}

# ---------------------------------------------------------------- 2. 打包
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
if (-not $SkipBuild) {
    Step '[2/5] PyInstaller onedir'
    $build = Run-External -Exe 'powershell.exe' -Arguments @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', 'scripts\build_onedir.ps1', '-SkipZip'
    )
    if ($build.Code -ne 0) {
        $build.Lines | Select-Object -Last 30 | Write-Host
        Fail 2 "构建失败（exit=$($build.Code)）"
    }
    $build.Lines | Select-Object -Last 3 | Write-Host -ForegroundColor DarkGray
}
if (-not (Test-Path (Join-Path $Dist "$AppName.exe"))) { Fail 2 "找不到构建产物：$Dist" }

# ---------------------------------------------------------------- 3. 停旧进程
Step '[3/5] 停止正在运行的桌宠'
Get-Process -Name $AppName -ErrorAction SilentlyContinue | ForEach-Object {
    Write-Host "  stop pid=$($_.Id)"
    try { $_.CloseMainWindow() | Out-Null } catch { }
}
Start-Sleep -Milliseconds 800
Get-Process -Name $AppName -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 500

# ---------------------------------------------------------------- 4. 换部署（保留一代备份）
Step '[4/5] 换部署目录'
$Backup = "$DeployTo.bak"
if (Test-Path $Backup) { Remove-Item $Backup -Recurse -Force }
if (Test-Path $DeployTo) { Move-Item $DeployTo $Backup }
$copy = Run-External -Exe 'robocopy' -Arguments @(
    $Dist, $DeployTo, '/E', '/MT:16', '/NFL', '/NDL', '/NJH', '/NJS', '/NP'
)
if ($copy.Code -ge 8) {
    Fail 3 "复制产物失败（robocopy=$($copy.Code)）；回退：Move-Item '$Backup' '$DeployTo' -Force"
}
Write-Host "  产物已就位（上一代在 $Backup）"

# ---------------------------------------------------------------- 5. 启动并确认
if (-not $NoRestart) {
    Step '[5/5] 启动并确认'
    Start-Process -FilePath $Exe -WorkingDirectory $DeployTo
    $ok = $false
    $procPid = 0
    for ($i = 0; $i -lt 40; $i++) {
        Start-Sleep -Milliseconds 500
        $proc = Get-CimInstance Win32_Process -Filter "Name='$AppName.exe'" -ErrorAction SilentlyContinue |
            Where-Object { $_.ExecutablePath -eq $Exe }
        if ($proc) { $ok = $true; $procPid = $proc.ProcessId; break }
    }
    if (-not $ok) { Fail 3 "启动失败：进程没起来；回退：Move-Item '$Backup' '$DeployTo' -Force" }
    Write-Host "  已启动 pid=$procPid" -ForegroundColor Green
}

$dur = [math]::Round(((Get-Date) - $t0).TotalMinutes, 1)
Write-Host ''
Write-Host "OK 用时 $dur 分钟" -ForegroundColor Green
Write-Host "日志：$Log"
Write-Host "回退：Move-Item '$Backup' '$DeployTo' -Force" -ForegroundColor DarkGray
Stop-Transcript | Out-Null
exit 0
