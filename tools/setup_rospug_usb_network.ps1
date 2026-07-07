param(
    [string]$AdapterDescription = "Remote NDIS Compatible Device",
    [string]$LocalIp = "192.168.55.100",
    [int]$PrefixLength = 24,
    [string]$RobotIp = "192.168.55.1",
    [switch]$RestoreDhcp
)

$ErrorActionPreference = "Stop"

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltinRole]::Administrator)
}

if (-not (Test-Admin)) {
    Write-Error "请使用管理员 PowerShell 运行本脚本。"
}

$adapter = Get-NetAdapter |
    Where-Object { $_.InterfaceDescription -eq $AdapterDescription -and $_.Status -eq "Up" } |
    Select-Object -First 1

if (-not $adapter) {
    Write-Error "未找到已连接的 ROSPug USB 网卡：$AdapterDescription"
}

Write-Host "目标网卡：" $adapter.Name "/" $adapter.InterfaceDescription

if ($RestoreDhcp) {
    Set-NetIPInterface -InterfaceAlias $adapter.Name -Dhcp Enabled
    Write-Host "已恢复 DHCP：" $adapter.Name
} else {
    Set-NetIPInterface -InterfaceAlias $adapter.Name -Dhcp Disabled
    Get-NetIPAddress -InterfaceAlias $adapter.Name -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue
    New-NetIPAddress -InterfaceAlias $adapter.Name -IPAddress $LocalIp -PrefixLength $PrefixLength | Out-Null
    Write-Host "已设置静态地址：$LocalIp/$PrefixLength"
}

Write-Host ""
Write-Host "当前 IPv4 配置："
Get-NetIPAddress -InterfaceAlias $adapter.Name -AddressFamily IPv4 |
    Select-Object InterfaceAlias, IPAddress, PrefixLength, AddressState |
    Format-Table -AutoSize

Write-Host ""
Write-Host "ROSPug 连接测试："
foreach ($port in @(22, 8080, 9090)) {
    $ok = Test-NetConnection $RobotIp -Port $port -InformationLevel Quiet
    Write-Host ("{0}:{1} -> {2}" -f $RobotIp, $port, ($(if ($ok) { "OK" } else { "FAILED" })))
}
