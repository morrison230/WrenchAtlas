# Windows built-in OCR (Windows.Media.Ocr) batch driver.
#
# Called by builder/ocr.py. Paths are passed via job.json, NOT command-line
# args -- PowerShell 5.1 mangles non-ASCII parameters, files are safer.
#
# input : TEMP\wa_ocr_job.json   { "dir": "...", "files": ["a.png", ...] }
# output: <dir>\_ocr_result.json [{ file, ok, ms, text }, ...]

Add-Type -AssemblyName System.Runtime.WindowsRuntime

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await($op, $type) {
    $t = $asTaskGeneric.MakeGenericMethod($type).Invoke($null, @($op))
    $t.Wait(-1) | Out-Null
    $t.Result
}

[void][Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
[void][Windows.Storage.Streams.IRandomAccessStream, Windows.Storage, ContentType=WindowsRuntime]
[void][Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType=WindowsRuntime]
[void][Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics, ContentType=WindowsRuntime]
[void][Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) {
    Write-Output 'NO_OCR_ENGINE'
    exit 1
}

$jobPath = Join-Path $env:TEMP 'wa_ocr_job.json'
if (-not (Test-Path $jobPath)) {
    Write-Output 'JOB_NOT_FOUND'
    exit 1
}

$job = Get-Content -Path $jobPath -Raw -Encoding UTF8 | ConvertFrom-Json
$dir = $job.dir
$out = New-Object System.Collections.ArrayList

foreach ($name in $job.files) {
    $full = Join-Path $dir $name
    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
        $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($full)) ([Windows.Storage.StorageFile])
        $stream = Await ($file.OpenAsync(0)) ([Windows.Storage.Streams.IRandomAccessStream])
        $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bmp = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $res = Await ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
        $sw.Stop()
        [void]$out.Add([PSCustomObject]@{
            file = $name
            ok   = $true
            ms   = [int]$sw.ElapsedMilliseconds
            text = $res.Text
        })
        $bmp.Dispose()
        $stream.Dispose()
    } catch {
        $sw.Stop()
        [void]$out.Add([PSCustomObject]@{
            file = $name
            ok   = $false
            ms   = -1
            text = $_.Exception.Message
        })
    }
}

$resultPath = Join-Path $dir '_ocr_result.json'
$out | ConvertTo-Json -Depth 3 | Out-File -FilePath $resultPath -Encoding utf8
Write-Output ('DONE ' + $out.Count)
