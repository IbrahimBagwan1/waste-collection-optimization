# Opens the generated report in MS Word, refreshes the table of contents and the
# lists of figures/tables and saves it. (Export a PDF from Word with File > Save As.)
#   powershell -ExecutionPolicy Bypass -File docs\finalize_report.ps1
$src = Join-Path $PSScriptRoot "WASTEX_Project_Report.docx"
$w = New-Object -ComObject Word.Application
$w.Visible = $false
$w.DisplayAlerts = 0
try {
    $doc = $w.Documents.Open($src)
    foreach ($t in $doc.TablesOfContents) { $t.Update() }
    $doc.Fields.Update() | Out-Null
    $doc.Save()
    "pages: " + $doc.ComputeStatistics(2)
    $doc.Close()
} finally { $w.Quit() }
