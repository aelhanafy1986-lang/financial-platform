$ErrorActionPreference = 'Stop'
$src = Join-Path $PWD 'reports\pptx_11_ar.pptx'
$out = Join-Path $PWD 'doc_previews'
Write-Output "src: $src"
$app = New-Object -ComObject PowerPoint.Application
try {
    $pres = $app.Presentations.Open($src, $true, $false, $false)
    $n = [Math]::Min($pres.Slides.Count, 3)
    Write-Output "slides total: $($pres.Slides.Count), exporting: $n"
    for ($i = 1; $i -le $n; $i++) {
        $png = Join-Path $out ("pptx_s{0}.png" -f $i)
        $pres.Slides.Item($i).Export($png, "PNG", 1280, 720)
        Write-Output ("saved: " + $png)
    }
    $pres.Close()
} finally {
    $app.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($app) | Out-Null
}
Write-Output "DONE"
