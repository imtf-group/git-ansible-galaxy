$MyArray = @()
if (Get-Module -ListAvailable -Name "SQLPS") {
    Import-Module "SQLPS"
    $sqlServer = New-Object ('Microsoft.SqlServer.Management.Smo.Server') $env:ComputerName
    $ErrorActionPreference = 'SilentlyContinue'
    $sqlServer.Logins | Where-Object {$_.LoginType -eq "WindowsUser"} | ForEach-Object {if ($_.Name.StartsWith($env:ComputerName)) {$MyArray += $_.Name.Split("\")[1]}}
    $ErrorActionPreference = 'Stop'
}
if (!$MyArray) {
    Write-Host "[]"
} else {
    $MyArray
}
