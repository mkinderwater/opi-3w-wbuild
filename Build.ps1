param(
    [string]$Distribution = 'Debian',
    [string]$DonorImage = '',
    [ValidateRange(2048, 32768)][int]$ImageMiB = 2048,
    [switch]$ExtractOnly
)
$ErrorActionPreference = 'Stop'
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    throw 'WSL is missing. Install Debian under WSL2 and finish its Linux user setup first.'
}
if ([string]::IsNullOrWhiteSpace($DonorImage)) {
    $DonorImage = Join-Path $PSScriptRoot 'inputs\zero3w-hardware.tar.gz'
    if (-not (Test-Path -LiteralPath $DonorImage)) { $DonorImage = Join-Path $PSScriptRoot 'inputs\vendor.img' }
}
if (-not (Test-Path -LiteralPath $DonorImage -PathType Leaf)) {
    throw ('Donor image missing. Put a working A733 Zero 3W 1 GB SD image at ' + $DonorImage)
}
$DonorImage = (Resolve-Path -LiteralPath $DonorImage -ErrorAction Stop).ProviderPath
if (-not (Test-Path -LiteralPath $DonorImage -PathType Leaf)) { throw 'Donor image must be a file.' }
$linuxDonor = @(& wsl.exe --distribution $Distribution --exec wslpath -a -u $DonorImage)
if ($LASTEXITCODE -ne 0 -or $linuxDonor.Count -ne 1) { throw 'Cannot translate the donor image path in WSL.' }
$linuxDonorPath = ([string]$linuxDonor[0]).TrimEnd("`r", "`n")
# Match the Chatbox entry pattern. Arguments remain data, without bash -c.
& wsl.exe --distribution $Distribution --cd $PSScriptRoot -- bash ./windows-entry.sh $linuxDonorPath ([string]$ImageMiB) ([string][int]$ExtractOnly.IsPresent)
if ($LASTEXITCODE -ne 0) { throw ('opi-3w-wbuild build failed. Exit code: ' + $LASTEXITCODE) }
