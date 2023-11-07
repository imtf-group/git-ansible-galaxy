$MyArray = @()
Get-LocalGroupMember -Group Users | Where-Object {$_.ObjectClass -eq "User"} | ForEach-Object {$MyArray += $_.Name.Split("\")[1]}
if (!$MyArray) {
    Write-Host "[]"
} else {
    $MyArray
}
