param([string]$Python, [switch]$Windowed)
$ErrorActionPreference = 'Stop'
if (-not $Python) { throw 'Pass the full path of the clean venv Python.' }
$buildRoot = Join-Path $env:TEMP 'omr_v52_build'
$sourceRoot = Join-Path $buildRoot 'src'
New-Item -ItemType Directory -Force $sourceRoot | Out-Null
$allow = @('share_launcher.py','main_qt.py','omr_processor.py','omr_upgrade.py','detection_0914.py','config_manager.py','config_dialog.py','param_dialog.py','guide_dialog.py','classsheet.py')
foreach ($name in $allow) { Copy-Item -LiteralPath (Join-Path $PSScriptRoot $name) -Destination $sourceRoot -Force }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'assets') -Destination $sourceRoot -Recurse -Force
$argsPyi = @('-m','PyInstaller','--noconfirm','--clean','--onedir','--noupx','--name','OMR_Grader_V52','--workpath',"$buildRoot\build",'--distpath',"$buildRoot\dist",'--specpath',$buildRoot,'--add-data',"$sourceRoot\assets;assets",'--hidden-import','config_dialog','--hidden-import','param_dialog','--hidden-import','guide_dialog')
foreach ($module in @('scipy','matplotlib','torch','torchvision','torchaudio','tensorflow','transformers','sklearn','numba','llvmlite','sympy','whisper','IPython','notebook','PyQt5','PySide6','PySide2','tkinter')) { $argsPyi += @('--exclude-module',$module) }
if ($Windowed) { $argsPyi += '--windowed' }
$argsPyi += "$sourceRoot\share_launcher.py"
Push-Location $sourceRoot
try { & $Python @argsPyi; if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' } } finally { Pop-Location }
$internal = "$buildRoot\dist\OMR_Grader_V52\_internal"
$qtBin = Join-Path (Split-Path (Split-Path $Python -Parent) -Parent) 'Lib\site-packages\PyQt6\Qt6\bin'
# Keep the wheel's complete matching VC runtime family, including threads/atomic_wait.
Get-ChildItem -LiteralPath $qtBin -File | Where-Object { $_.Name -match '^(vcruntime|msvcp|concrt|vccorlib)140.*\.dll$' } | Copy-Item -Destination $internal -Force
Get-ChildItem -LiteralPath $qtBin -File | Where-Object { $_.Name -match '^(vcruntime|msvcp|concrt|vccorlib)140.*\.dll$' } | Copy-Item -Destination "$internal\PyQt6\Qt6\bin" -Force
if (-not (Test-Path "$internal\PyQt6\Qt6\plugins\platforms\qwindows.dll")) { throw 'qwindows.dll missing' }
if (-not (Test-Path "$internal\vcruntime140_1.dll")) { throw 'VC runtime missing' }
& $Python -m pip freeze | Set-Content -Encoding utf8 (Join-Path $PSScriptRoot 'requirements-share-lock.txt')
Write-Output "$buildRoot\dist\OMR_Grader_V52"
