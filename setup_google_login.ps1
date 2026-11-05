# Writes the Google sign-in settings into backend\.env (asks for the Client ID and Client Secret).
$env_file = Join-Path $PSScriptRoot 'backend\.env'
Write-Host ''
Write-Host 'Google sign-in setup' -ForegroundColor Cyan
Write-Host 'Paste the values from Google Cloud Console > APIs & Services > Credentials > your Web client.'
$id = (Read-Host 'Client ID').Trim()
$secret = (Read-Host 'Client secret').Trim()
if (-not $id.EndsWith('.apps.googleusercontent.com') -or $secret.Length -lt 10) {
    Write-Host 'These do not look right: the Client ID must end with .apps.googleusercontent.com. Nothing was changed.' -ForegroundColor Red
    exit 1
}
$lines = @()
if (Test-Path $env_file) { $lines = Get-Content $env_file | Where-Object { $_ -notmatch '^\s*OIDC_' } }
$lines += 'OIDC_ISSUER_URL=https://accounts.google.com'
$lines += "OIDC_CLIENT_ID=$id"
$lines += "OIDC_CLIENT_SECRET=$secret"
$lines += 'OIDC_REDIRECT_URI=http://127.0.0.1:8000/api/auth/oidc/callback'
[IO.File]::WriteAllLines($env_file, $lines, (New-Object Text.UTF8Encoding($false)))
Write-Host 'Saved. Close the app window and run start.bat again; the Continue with Google button will appear.' -ForegroundColor Green
