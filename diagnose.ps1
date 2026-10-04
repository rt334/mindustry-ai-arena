# AI 竞技场 · 日志诊断
#
# 一次跑完，把排查「看不到单位 / 切队跳回 / 建筑延迟出现」所需的全部事实
# 收进一个文件。不用猜 —— 每一条结论都能在报告里找到对应的原始数据。
#
# 用法：
#   .\diagnose.ps1                    跑 120 秒并生成报告
#   .\diagnose.ps1 -Seconds 240       跑更久（更容易抓到断线重连）
#   .\diagnose.ps1 -NoClient          只起服务器和 AI
#
# 产出：
#   C:\dsh\ai-arena\diagnostics\diag-<时间戳>.md    人类可读报告
#   C:\dsh\ai-arena\diagnostics\diag-<时间戳>\      原始日志

[CmdletBinding()]
param(
    [string]$Map = "veins",
    [int]$Port = 7199,
    [int]$Seconds = 120,
    [switch]$NoClient,
    [string]$ServerJar = "C:\dsh\Mindustry-src\server\build\libs\server-release.jar",
    [string]$JavaExe = "C:\dsh\zulu17\zulu17.68.203-ca-jdk17.0.20.1-win_x64\bin\java.exe",
    [string]$GameJar = "C:\dsh\Mindustry-src\desktop\build\libs\Mindustry.jar",
    [string]$RunDir = "C:\dsh\ai-arena\server-run"
)

$ErrorActionPreference = 'Continue'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$diagDir = "C:\dsh\ai-arena\diagnostics\$stamp"
New-Item -ItemType Directory -Force -Path $diagDir | Out-Null
$report = "C:\dsh\ai-arena\diagnostics\diag-$stamp.md"

function Say($t) { Write-Host ""; Write-Host "=== $t ===" -ForegroundColor Cyan }
function Step($t) { Write-Host "   $t" }

$lines = New-Object System.Collections.Generic.List[string]
function Rep($t) { $lines.Add($t) | Out-Null; if ($t -match '^\s*$') { Write-Host "" } else { Write-Host "   $t" } }

# ---------------------------------------------------------------- 前置

Say "清理旧进程"
Get-CimInstance Win32_Process -Filter "Name='java.exe'" -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'ai-client' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 3

Rep "# AI 竞技场 · 日志诊断"
Rep ""
Rep "- 时间: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Rep "- 地图: $Map   时长: ${Seconds}s"
Rep "- 服务器 jar: $ServerJar"
Rep "- 客户端 jar: $GameJar"
Rep ""

# ---------------------------------------------------------------- 启动

Say "启动服务器"
$srvOut = Join-Path $diagDir 'server-out.log'
$srvErr = Join-Path $diagDir 'server-err.log'
$srv = Start-Process -FilePath $JavaExe -ArgumentList '-Djava.net.preferIPv4Stack=true','-jar',$ServerJar `
    -WorkingDirectory $RunDir -RedirectStandardOutput $srvOut -RedirectStandardError $srvErr `
    -PassThru -WindowStyle Hidden
Step "PID $($srv.Id)"

for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    try { if ((Invoke-RestMethod "http://127.0.0.1:$Port/ping" -TimeoutSec 2).ok) { break } } catch {}
}
Step "就绪"

$cfg = Get-Content (Join-Path $RunDir "config\ai-arena.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$ref = ($cfg.agents | Where-Object { $_.admin } | Select-Object -First 1).token
$fighters = @($cfg.agents | Where-Object { -not $_.admin })
$H = @{ Authorization = "Bearer $ref" }

function Api($path, $method = 'GET') {
    try {
        if ($method -eq 'POST') {
            return Invoke-RestMethod -Uri "http://127.0.0.1:$Port$path" -Method POST -Headers $H -TimeoutSec 30
        }
        return Invoke-RestMethod -Uri "http://127.0.0.1:$Port$path" -Headers $H -TimeoutSec 30
    } catch { return $null }
}

Say "初始化对局"
Api "/v1/referee/setup?map=$Map" | Out-Null
Start-Sleep -Seconds 3
Api "/v1/referee/host" 'POST' | Out-Null
Start-Sleep -Seconds 3
Api "/v1/referee/start" 'POST' | Out-Null
Start-Sleep -Seconds 2

Say "启动 AI"
foreach ($f in $fighters) {
    Start-Process -FilePath 'python' `
        -ArgumentList '-u','C:\dsh\ai-arena\ai-client.py','--agent',$f.id,'--token',$f.token,'--seconds',"$Seconds",'--interval','0.5' `
        -RedirectStandardOutput (Join-Path $diagDir "ai-$($f.id).log") `
        -RedirectStandardError  (Join-Path $diagDir "ai-$($f.id)-err.log") `
        -PassThru -WindowStyle Hidden | Out-Null
}
Step "$($fighters.Count) 个"

$cli = $null
if (-not $NoClient) {
    Say "启动观战客户端"
    $cli = Start-Process -FilePath $JavaExe `
        -ArgumentList '-Djava.net.preferIPv4Stack=true','-Xmx2G','-jar',$GameJar `
        -WorkingDirectory (Split-Path $GameJar) `
        -RedirectStandardOutput (Join-Path $diagDir 'client-out.log') `
        -RedirectStandardError  (Join-Path $diagDir 'client-err.log') `
        -PassThru -WindowStyle Normal
    Step "PID $($cli.Id)"
}

# ---------------------------------------------------------------- 采样

Say "采样 ${Seconds}s（每 5 秒记录一次服务端状态 + 客户端计数）"
$timeline = New-Object System.Collections.Generic.List[string]
$deadline = (Get-Date).AddSeconds($Seconds)
$lastDisconnects = -1
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 5
    $d = Api "/v1/referee/diag"
    if (-not $d) { $timeline.Add("t=$( [int]((Get-Date) - $srv.StartTime).TotalSeconds )s  <diag 无响应>") | Out-Null; continue }

    $cliUnits = 'n/a'; $cliTeam = 'n/a'; $cliFog = 'n/a'; $cliAlive = 'dead'
    $clog = Join-Path $diagDir 'client-out.log'
    if (Test-Path $clog) {
        $last = Get-Content $clog -Encoding UTF8 -ErrorAction SilentlyContinue |
                Select-String -Pattern '\[diag\]' | Select-Object -Last 1
        if ($last) {
            if ($last.Line -match 'team=(\S+)')   { $cliTeam = $Matches[1] }
            if ($last.Line -match 'fog=(\S+)')    { $cliFog = $Matches[1] }
            if ($last.Line -match 'units=(\d+)')  { $cliUnits = $Matches[1] }
        }
        if ($cli -and (Get-Process -Id $cli.Id -ErrorAction SilentlyContinue)) { $cliAlive = 'alive' }
    }

    $viewInfo = ($d.data.players | Where-Object { $_.observer } | ForEach-Object { "view=$($_.view)" }) -join ','
    if (-not $viewInfo) { $viewInfo = '-' }

    $dc = ($d.data.connectionEvents | Where-Object { $_.kind -eq 'leave' }).Count
    $mark = ''
    if ($lastDisconnects -ge 0 -and $dc -gt $lastDisconnects) { $mark = '   <-- 发生断线!' }
    $lastDisconnects = $dc

    $timeline.Add(("t={0,4}s  服务端 units={1} builds={2} players={3} | 客户端 units={4} team={5} fog={6} {7} | 观战者 {8} | 断开累计={9}{10}" -f `
        [int]((Get-Date) - $srv.StartTime).TotalSeconds,
        $d.data.worldUnits, $d.data.worldBuilds, $d.data.worldPlayers,
        $cliUnits, $cliTeam, $cliFog, $cliAlive, $viewInfo, $dc, $mark)) | Out-Null
    Write-Host ("   " + $timeline[$timeline.Count-1])
}

# ---------------------------------------------------------------- 报告

Say "生成报告"
$final = Api "/v1/referee/diag"

Rep "## 1. 采样时间线"
Rep ""
Rep '```'
foreach ($l in $timeline) { Rep $l }
Rep '```'
Rep ""

if ($final) {
    Rep "## 2. 最终状态"
    Rep ""
    Rep '```'
    Rep "state=$($final.data.state) paused=$($final.data.paused) fog=$($final.data.fog) staticFog=$($final.data.staticFog) pvp=$($final.data.pvp)"
    Rep "worldUnits=$($final.data.worldUnits) worldBuilds=$($final.data.worldBuilds) worldPlayers=$($final.data.worldPlayers)"
    Rep ""
    Rep "队伍:"
    foreach ($t in $final.data.teams) {
        Rep ("  team {0,-5} {1,-12} units={2,-4} builds={3,-4} cores={4,-3} players={5}" -f $t.id, $t.name, $t.units, $t.builds, $t.cores, $t.players)
    }
    Rep ""
    Rep "玩家:"
    foreach ($p in $final.data.players) {
        Rep ("  {0,-12} id={1,-5} team={2,-12} view={3,-5} spectator={4,-6} observer={5,-6} hasUnit={6,-6} conn={7}" -f `
            $p.name, $p.id, $p.teamName, $p.view, $p.spectator, $p.observer, $p.hasUnit, $p.connected)
    }
    Rep '```'
    Rep ""

    Rep "## 3. 断开原因直方图"
    Rep ""
    Rep '```'
    Rep ($final.data.disconnectReasons | ConvertTo-Json -Compress)
    Rep '```'
    Rep ""
    Rep "解读:"
    Rep "- ``closed`` = 客户端正常关闭（人关了窗口），不需要修"
    Rep "- ``timeout`` = 心跳超时，通常是 UDP 被拦或丢包"
    Rep "- ``error`` = 底层读写错误，网络栈层面的问题"
    Rep "- 反复出现 timeout/error 就说明是网络层在拦包，游戏侧改不动"
    Rep ""

    Rep "## 4. 快照路由计数"
    Rep ""
    Rep '```'
    Rep "teamBatchSends=$($final.data.teamBatchSends) fullViewSends=$($final.data.fullViewSends) spectatorRouted=$($final.data.spectatorRouted)"
    Rep '```'
    Rep ""
    Rep "- spectatorRouted > 0 说明观战者确实被单独路由了"
    Rep "- fullViewSends 增长说明全图视角在持续发全量实体"
    Rep ""

    Rep "## 5. 连接事件时间线"
    Rep ""
    Rep '```'
    foreach ($e in $final.data.connectionEvents) {
        Rep ("  t={0,-10} tick={1,-8} {2,-6} {3,-12} reason={4}" -f $e.t, $e.tick, $e.kind, $e.name, $e.reason)
    }
    Rep '```'
    Rep ""
}

Rep "## 6. 客户端日志（关键行）"
Rep ""
Rep '```'
$clog = Join-Path $diagDir 'client-out.log'
if (Test-Path $clog) {
    Get-Content $clog -Encoding UTF8 -ErrorAction SilentlyContinue |
        Select-String -Pattern '\[diag\]|\[observer\]|Connecting|Disconnecting|world data|Received world' |
        Select-Object -Last 60 | ForEach-Object { Rep $_.Line }
} else { Rep "(无客户端日志)" }
Rep '```'
Rep ""

Rep "## 7. 原始日志"
Rep ""
Rep "- ``$diagDir``"

Set-Content -Path $report -Value ($lines -join "`r`n") -Encoding UTF8
Step "报告: $report"

Say "停止进程"
foreach ($p in @($cli, $srv)) { if ($p -and -not $p.HasExited) { try { $p.Kill() } catch {} } }
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'ai-client' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Write-Host ""
Write-Host "  报告已生成: $report" -ForegroundColor Green
