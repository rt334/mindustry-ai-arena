# AI 竞技场 · 起一局完整对抗 + 打开观战
#
# 顺序很关键（踩过坑）：
#   1. setup  加载地图、放核心、生成建造单位 —— 需要进入 playing 状态
#   2. host   打开游戏端口 —— 注意 openServer() 会把状态切回 menu/paused，
#             所以必须在 setup 之后调，反过来的话 setup 会失败
#   3. 启动 AI 客户端
#   4. 启动 Mindustry 客户端（自带 ai-observer mod，会自动连上）
#
# 用法：
#   .\live-match.ps1                       默认配置
#   .\live-match.ps1 -Map passage -NoClient   只起服务器和 AI，不开客户端

[CmdletBinding()]
param(
    [string]$Map = "veins",
    [int]$Port = 7199,
    [int]$GamePort = 6567,
    [switch]$NoClient,
    [switch]$NoAI,
    [switch]$Record,
    [string]$ServerJar = "C:\dsh\Mindustry-src\server\build\libs\server-release.jar",
    [string]$JavaExe = "C:\dsh\zulu17\zulu17.68.203-ca-jdk17.0.20.1-win_x64\bin\java.exe",
    # ⚠ 必须是**自建**的客户端（含 core 补丁 + ai-arena mod），不是 vanilla。
    # 原默认值指向 C:\dsh\_dl\mindustry-v160.5\Mindustry.jar —— 那是原版，
    # 启动后会报 Unknown revision '3' for entity type 'PlayerComp' 直接崩。
    [string]$GameJar = "C:\dsh\Mindustry-src\desktop\build\libs\Mindustry.jar",
    [string]$RunDir = "C:\dsh\ai-arena\server-run"
)

$ErrorActionPreference = 'Continue'
$Script:Procs = [ordered]@{}

function Say($t) { Write-Host ""; Write-Host "=== $t ===" -ForegroundColor Cyan }
function Step($t) { Write-Host "   $t" }

function Cleanup {
    Say "停止所有进程"
    foreach ($k in $Script:Procs.Keys) {
        $p = $Script:Procs[$k]
        if ($p -and -not $p.HasExited) {
            try { $p.Kill(); Step "$k (PID $($p.Id)) 已停止" } catch {}
        }
    }
}

# ---------------------------------------------------------------- 前置

Say "前置检查"
if (-not (Test-Path $ServerJar)) { throw "服务器 jar 不存在: $ServerJar" }
if (-not (Test-Path $JavaExe))   { throw "Java 不存在: $JavaExe" }
Step ("服务器 jar  {0:N0} B" -f (Get-Item $ServerJar).Length)

# 确认服务器 jar 的版本和客户端一致 —— 不一致会报
# "Unknown object type: N"（内容 ID 表不同）
$srcVer = "?"
if (Test-Path "C:\dsh\Mindustry-src\.git") {
    Push-Location "C:\dsh\Mindustry-src"
    $srcVer = (git describe --tags 2>&1) -join ''
    Pop-Location
}
Step "服务器源码 $srcVer"

foreach ($pt in @($Port, $GamePort)) {
    $b = Get-NetTCPConnection -LocalPort $pt -State Listen -ErrorAction SilentlyContinue
    if ($b) { Step "端口 $pt 已被占用（PID $($b.OwningProcess)），先清掉" }
}
Get-CimInstance Win32_Process -Filter "Name='java.exe'" -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'ai-client|watch\.py' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 3

# ---------------------------------------------------------------- 服务器

Say "启动服务器"
$outLog = Join-Path $RunDir "live-out.log"
$errLog = Join-Path $RunDir "live-err.log"
Remove-Item $outLog, $errLog -Force -ErrorAction SilentlyContinue

$Script:Procs['server'] = Start-Process -FilePath $JavaExe `
    -ArgumentList '-jar', $ServerJar `
    -WorkingDirectory $RunDir `
    -RedirectStandardOutput $outLog -RedirectStandardError $errLog `
    -PassThru -WindowStyle Hidden
Step "PID $($Script:Procs['server'].Id)"

for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    if ($Script:Procs['server'].HasExited) { throw "服务器提前退出，见 $outLog" }
    try { if ((Invoke-RestMethod "http://127.0.0.1:$Port/ping" -TimeoutSec 2).ok) { break } } catch {}
}
Step "就绪"

$cfg = Get-Content (Join-Path $RunDir "config\ai-arena.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$ref = ($cfg.agents | Where-Object { $_.admin } | Select-Object -First 1).token
$fighters = @($cfg.agents | Where-Object { -not $_.admin })

# ---------------------------------------------------------------- setup

Say "初始化对局（$Map）"
$s = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/referee/setup?map=$Map" `
    -Headers @{ Authorization = "Bearer $ref" } -TimeoutSec 30
if (-not $s.ok) { throw "setup 失败: $($s.error)" }
Step "地图 $($s.data.map)  $($s.data.width)x$($s.data.height)"
foreach ($c in $s.data.cores) {
    Step ("  {0,-8} -> team {1}  核心 @ ({2},{3})" -f $c.agent, $c.team, $c.coreX, $c.coreY)
}
Start-Sleep -Seconds 3

# ---------------------------------------------------------------- host

Say "打开游戏端口（必须放在 setup 之后）"
$h = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/referee/host" -Method Post `
    -Headers @{ Authorization = "Bearer $ref" } -TimeoutSec 20
if ($h.ok) { Step $h.data.message } else { Step "失败: $($h.error)" }
Start-Sleep -Seconds 2

$listening = Get-NetTCPConnection -LocalPort $GamePort -State Listen -ErrorAction SilentlyContinue
Step "端口 $GamePort $(if($listening){'监听中'}else{'未监听'})"

# 关掉所有自动暂停，否则没玩家时引擎会把状态改回 paused
$st = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/referee/start" -Method Post `
    -Headers @{ Authorization = "Bearer $ref" } -TimeoutSec 20
if ($st.ok) { Step "已解除暂停: $($st.data.message)" } else { Step "start 失败: $($st.error)" }
Start-Sleep -Seconds 2

if ($Record) {
    $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/referee/record?action=start&label=$Map" -Method Post `
        -Headers @{ Authorization = "Bearer $ref" } -TimeoutSec 15
    Step "录像: $($r.data.message)"
}

# ---------------------------------------------------------------- AI

if (-not $NoAI) {
    Say "启动 AI（$($fighters.Count) 个）"
    $env:PYTHONIOENCODING = 'utf-8'
    foreach ($f in $fighters) {
        $Script:Procs["ai-$($f.id)"] = Start-Process -FilePath 'python' `
            -ArgumentList 'C:\dsh\ai-arena\ai-client.py', '--agent', $f.id, '--token', $f.token,
                          '--seconds', '3600', '--interval', '0.5' `
            -RedirectStandardOutput (Join-Path $RunDir "ai-$($f.id).log") `
            -RedirectStandardError  (Join-Path $RunDir "ai-$($f.id)-err.log") `
            -PassThru -WindowStyle Hidden
        Step "$($f.id)  PID $($Script:Procs["ai-$($f.id)"].Id)"
    }
    Start-Sleep -Seconds 15
}

# ---------------------------------------------------------------- 客户端

if (-not $NoClient) {
    Say "启动 Mindustry 客户端（会自动连上 $GamePort）"
    if (-not (Test-Path $GameJar)) { Step "客户端 jar 不存在: $GameJar"; }
    else {
        # -Djava.net.preferIPv4Stack=true **必须带**：不带的话 JVM 会把 UDP 绑到
        # IPv6，而服务端按 IPv4 发快照，客户端永远收不到 →
        # 反复 "Timed out after not received UDP snapshots." + Disconnecting。
        # 服务端一直带着这个参数，客户端漏掉过一次，现象就是每隔一两分钟断一次。
        # -Dmindustry.autoreconnect=true 打开断线自动重连（引擎补丁，
        # 见 core/src/mindustry/net/Net.java 的 updateAutoReconnect）。
        # ⚠ 数据目录（存档/设置/mods）由引擎决定，是 OS 的 app-data 目录
        # （%APPDATA%\Mindustry），与 -WorkingDirectory 无关，不要试图用
        # 工作目录去隔离它。
        $Script:Procs['client'] = Start-Process -FilePath $JavaExe `
            -ArgumentList '-Xmx2G',
                          '-Djava.net.preferIPv4Stack=true',
                          '-Dmindustry.autoreconnect=true',
                          '-jar', $GameJar `
            -WorkingDirectory (Split-Path $GameJar -Parent) `
            -RedirectStandardOutput (Join-Path $RunDir "client-out.log") `
            -RedirectStandardError  (Join-Path $RunDir "client-err.log") `
            -PassThru -WindowStyle Normal
        Step "PID $($Script:Procs['client'].Id)"
        Step "等待启动与自动连接（75 秒）…"
        Start-Sleep -Seconds 75

        $clog = Join-Path $RunDir "client-out.log"
        if (Test-Path $clog) {
            $conn = Get-Content $clog -Encoding UTF8 -ErrorAction SilentlyContinue |
                    Select-String -Pattern 'Connecting|Disconnect|Received world|Unknown object' |
                    Select-Object -First 6
            foreach ($c in $conn) { Step $c.Line }
        }

        # 把它设成观察者：derelict 队 + admin，这样能看到全图且不干扰对局
        try {
            $players = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/referee/admin" `
                -Headers @{ Authorization = "Bearer $ref" } -TimeoutSec 15
            foreach ($p in $players.data.players) {
                $o = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/referee/admin?action=observe&player=$($p.id)" `
                    -Method Post -Headers @{ Authorization = "Bearer $ref" } -TimeoutSec 15
                if ($o.ok) { Step "已设为观察者: $($p.name) — $($o.data.message)" }
            }
            if ($players.data.count -eq 0) { Step "还没有客户端连上" }
        } catch { Step "设置观察者失败: $($_.Exception.Message)" }
    }
}

# ---------------------------------------------------------------- 状态

Say "当前状态"
try {
    $st = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/referee/state?view=all" `
        -Headers @{ Authorization = "Bearer $ref" } -TimeoutSec 10
    $bl = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/referee/buildings?view=all" `
        -Headers @{ Authorization = "Bearer $ref" } -TimeoutSec 10
    $un = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/referee/units?view=all" `
        -Headers @{ Authorization = "Bearer $ref" } -TimeoutSec 10
    Step "tick $($st.data.tick)   单位 $($un.data.units.Count)   建筑 $($bl.data.buildings.Count)"
    $bl.data.buildings | Where-Object { $_.block -like 'core-*' } | Sort-Object team | ForEach-Object {
        Step ("  核心 team {0} @ ({1},{2})  hp {3}/{4}" -f $_.team, $_.x, $_.y, [int]$_.health, [int]$_.maxHealth)
    }
} catch { Step "取状态失败: $($_.Exception.Message)" }

Say "进程清单"
foreach ($k in $Script:Procs.Keys) {
    $p = $Script:Procs[$k]
    Step ("{0,-12} PID {1,-8} {2}" -f $k, $p.Id, $(if ($p.HasExited) { '已退出' } else { '运行中' }))
}

Write-Host ""
Write-Host "  停止全部: Get-Process java,python | Where-Object { `$_.Path -like '*zulu17*' -or `$_.ProcessName -eq 'python' } | Stop-Process" -ForegroundColor Yellow
