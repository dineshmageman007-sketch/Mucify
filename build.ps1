<#
  Builds the Mucify installer on Windows.
    ./build.ps1                      -> tests, PyInstaller app, self-test, Inno Setup installer
    ./build.ps1 -SkipInstaller       -> only dist\Mucify\Mucify.exe
    ./build.ps1 -Version 1.2.3       -> override the version shown in the installer
  Needs: Python 3.11 (64-bit) and, for the installer, Inno Setup 6 (ISCC.exe).
#>
param(
  [string]$Version = "",
  [switch]$SkipInstaller,
  [switch]$SkipTests
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Step($t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }

if (-not $Version) {
  $Version = (Select-String -Path "mucify\__init__.py" -Pattern '__version__\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
}
Write-Host "Mucify version $Version"

Step "Checking bundled tools"
foreach ($f in @("tools\sldl\sldl.exe", "tools\rsgain\rsgain.exe", "assets\mucify.ico", "LICENSE", "THIRD_PARTY.md", "DISCLAIMER.md", "PRIVACY.md", "CREDITS.md", "tools\sldl\VERSION.txt")) {
  if (-not (Test-Path $f)) { throw "Missing required file: $f" }
}

Step "Installing Python dependencies"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

if (-not $SkipTests) {
  Step "Running tests"
  python -m pytest -q
  if ($LASTEXITCODE -ne 0) { throw "Tests failed" }
}

Step "Building Mucify.exe with PyInstaller"
if (Test-Path build) { Remove-Item build -Recurse -Force }
if (Test-Path dist)  { Remove-Item dist  -Recurse -Force }
python -m PyInstaller --noconfirm --clean mucify.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Step "Collecting license files"
$lic = "dist\Mucify\licenses"
New-Item -ItemType Directory -Force $lic | Out-Null
foreach ($f in @("LICENSE", "THIRD_PARTY.md", "DISCLAIMER.md", "PRIVACY.md", "CREDITS.md", "SECURITY.md")) { Copy-Item $f $lic }
Copy-Item "tools\sldl\LICENSE.txt"   "$lic\sldl-LICENSE.txt"
Copy-Item "tools\sldl\VERSION.txt"   "$lic\sldl-VERSION.txt"
Copy-Item "tools\rsgain\LICENSE.txt" "$lic\rsgain-LICENSE.txt"
Copy-Item "tools\rsgain\LICENSE-CRCpp.txt" "$lic\rsgain-CRCpp-LICENSE.txt"
python -m piplicenses --format=plain-vertical --with-license-file --no-license-path --output-file "$lic\python-packages.txt"
if ($LASTEXITCODE -ne 0) { Write-Warning "Could not generate python-packages.txt (continuing)" }

Step "Self-test of the packaged app"
$home_ = Join-Path $env:TEMP ("mucify-selftest-" + [guid]::NewGuid().ToString("N"))
$env:MUCIFY_HOME = $home_
$p = Start-Process -FilePath "dist\Mucify\Mucify.exe" -ArgumentList "--selftest" -Wait -PassThru
$report = Join-Path $home_ "logs\selftest.txt"
if (Test-Path $report) { Get-Content $report }
Remove-Item Env:\MUCIFY_HOME
if ($p.ExitCode -ne 0) { throw "Packaged app self-test failed (exit $($p.ExitCode))" }

if ($SkipInstaller) { Write-Host "`nDone: dist\Mucify\Mucify.exe"; exit 0 }

Step "Fetching the WebView2 bootstrapper (installed automatically if a PC lacks it)"
New-Item -ItemType Directory -Force installer\redist | Out-Null
$wv = "installer\redist\MicrosoftEdgeWebview2Setup.exe"
if (-not (Test-Path $wv)) {
  try { Invoke-WebRequest -Uri "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -OutFile $wv -UseBasicParsing }
  catch { Write-Warning "Could not download the WebView2 bootstrapper ($_). The installer will be built without it." }
}

Step "Building the installer with Inno Setup"
$iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
  foreach ($c in @("$env:ProgramFiles\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
                   "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) { if (Test-Path $c) { $iscc = $c; break } }
}
if (-not $iscc) { throw "Inno Setup 6 not found. Install it from https://jrsoftware.org/isdl.php or run: choco install innosetup" }
& $iscc "/DMyAppVersion=$Version" "installer\mucify.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

Step "Done"
Get-ChildItem installer\Output | ForEach-Object { Write-Host $_.FullName ("({0:N1} MB)" -f ($_.Length / 1MB)) }
