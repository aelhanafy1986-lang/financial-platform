$ErrorActionPreference = 'Stop'
$src = Join-Path $PWD 'reports\export_11.xlsx'
$out = Join-Path $PWD 'doc_previews'
Write-Output "src: $src"
$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
try {
    $wb = $excel.Workbooks.Open($src, 0, $true)
    $ws = $wb.Worksheets.Item(1)   # الملخص is the first sheet (index avoids PS1 encoding issues)

    # 1) whole summary sheet -> PDF (respects fitToWidth print setup)
    $pdf = Join-Path $out 'excel_summary.pdf'
    $ws.ExportAsFixedFormat(0, $pdf)   # 0 = xlTypePDF
    Write-Output "pdf: $pdf"

    # 2) ratio-cards block -> PNG via chart paste trick
    $rng = $ws.Range('A31:E36')
    $rng.CopyPicture(1, 2) | Out-Null   # xlScreen, xlBitmap
    $co = $ws.ChartObjects().Add(10, 10, 900, 320)
    $co.Chart.Paste()
    $png = Join-Path $out 'excel_cards.png'
    $co.Chart.Export($png, 'PNG')
    $co.Delete()
    Write-Output "png: $png"

    # 3) header banner block -> PNG
    $rng2 = $ws.Range('A1:F8')
    $rng2.CopyPicture(1, 2) | Out-Null
    $co2 = $ws.ChartObjects().Add(10, 10, 900, 260)
    $co2.Chart.Paste()
    $png2 = Join-Path $out 'excel_banner.png'
    $co2.Chart.Export($png2, 'PNG')
    $co2.Delete()
    Write-Output "png: $png2"

    $wb.Close($false)
} finally {
    $excel.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null
}
Write-Output "DONE"
