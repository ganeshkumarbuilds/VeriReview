$path = "frontend\src\pages\Review.jsx"
$content = Get-Content $path -Raw
$content = $content.Replace('<a`n                href={API_BASE', "<a`r`n                href={API_BASE")
Set-Content -Path $path -Value $content -NoNewline
Write-Host "Fixed."