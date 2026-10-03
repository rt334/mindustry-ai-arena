# AI 竞技场 · 一局启动脚本
#
# 用法：
#   .\start-arena.ps1                          默认 2 个 AI，veins 地图
#   .\start-arena.ps1 -Agents 4 -Map passage   4 个 AI（passage 有 4 个核心）
#   .\start-arena.ps1 -Record                  开局即开始录像
#   .\start-arena.ps1 -Fog:$false              关闭迷雾（调试用）
#
# 做的事：
#   1. 拉起 headless 服务器
#   2. 轮询 /ping 等它就绪
#   3. 调 /setup 加载地图、放核心、生成建造单位
#   4. 输出每个 AI 的连接信息（端点 + token）
#   5. 可选开始录像
#   6. Ctrl+C 时优雅停止

[CmdletBinding()]
param(
    [int]$Agents = 2,
    [string]$Map = "veins",
    [int]$Port = 7199,
    [switch]$Record,
    [bool]$Fog = $true,
    [switch]$KeepRunning,
    [string]$ServerJar = "C:\dsh\Mindustry-src\server\build\libs\server-release.jar",
    [string]$JavaExe = "C:\dsh\zulu17\zulu17.68.203-ca-jdk17.0.20.1-win_x64\bin\java.exe",
    [string]$RunDir = "C:\dsh\ai-arena\server-run"
)

$ErrorActionPreference = 'Stop'
$Script:ServerProc = $null

function Write-Head($text) {
    Write-Host ""
    Write-Host "=== $text ===" -ForegroundColor Cyan
}

function Stop-Server {
    if ($Script:ServerProc -and -not $Script:ServerProc.HasExited) {
        Write-Host "  正在停止服务器..." -ForegroundColor Yellow
        try { $Script:ServerProc.Kill() } catch { }
    }
}

# Ctrl+C 优雅退出
$null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action { Stop-Server }

# ---------------------------------------------------------------- 前置检查

Write-Head "前置检查"

if (-not (Test-Path $ServerJar)) { throw "服务器 jar 不存在: $ServerJar" }
if (-not (Test-Path $JavaExe))   { throw "Java 不存在: $JavaExe" }
if (-not (Test-Path $RunDir))    { throw "运行目录不存在: $RunDir" }

$modPath = Join-Path $RunDir "config\mods\ai-arena.jar"
if (-not (Test-Path $modPath)) { throw "AI Arena Mod 未部署: $modPath" }

Write-Host ("  服务器 jar  {0:N0} B" -f (Get-Item $ServerJar).Length)
Write-Host ("  Mod         {0:N0} B" -f (Get-Item $modPath).Length)
Write-Host "  运行目录    $RunDir"

# 端口占用检查
$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) { throw "端口 $Port 已被占用（PID $($busy.OwningProcess)）" }

# ---------------------------------------------------------------- 启动服务器

Write-Head "启动服务器"

$outLog = Join-Path $RunDir "arena-out.log"
$errLog = Join-Path $RunDir "arena-err.log"
Remove-Item $outLog, $errLog -Force -ErrorAction SilentlyContinue

$Script:ServerProc = Start-Process -FilePath $JavaExe `
    -ArgumentList '-jar', $ServerJar `
    -WorkingDirectory $RunDir `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -PassThru -WindowStyle Hidden

Write-Host "  PID $($Script:ServerProc.Id)"

# ---------------------------------------------------------------- 等待就绪

Write-Head "等待服务器就绪"

$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    if ($Script:ServerProc.HasExited) {
        Write-Host "  服务器进程已退出，日志尾部：" -ForegroundColor Red
        Get-Content $outLog -Tail 20 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "    $_" }
        throw "服务器启动失败"
    }
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/ping" -TimeoutSec 2 -ErrorAction Stop
        if ($r.ok) { $ready = $true; break }
    } catch { }
}

if (-not $ready) { throw "服务器在 30 秒内未就绪" }
Write-Host "  就绪（$([Math]::Round(($i+1)*0.5,1)) 秒）" -ForegroundColor Green

# ---------------------------------------------------------------- 读取配置

Write-Head "读取 agent 配置"

$cfgPath = Join-Path $RunDir "config\ai-arena.json"
if (-not (Test-Path $cfgPath)) { throw "配置文件未生成: $cfgPath" }

$cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
$refAgent = $cfg.agents | Where-Object { $_.admin } | Select-Object -First 1
$fighters = $cfg.agents | Where-Object { -not $_.admin }

if (-not $refAgent) { throw "配置里没有 admin agent（裁判）" }

# 参战 agent 不够时自动补足 —— 让「-Agents N」真的能一条命令起一局。
# 新 agent 用默认队伍 id（100 起，跳过已占用的），地图核心不够时由 setup 自建核心。
if ($fighters.Count -lt $Agents) {
    Write-Host "  配置里只有 $($fighters.Count) 个参战 agent，自动补足到 $Agents" -ForegroundColor Yellow

    $existing = [System.Collections.ArrayList]@()
    foreach ($a in $cfg.agents) { $null = $existing.Add($a) }

    $usedTeams = @($cfg.agents | ForEach-Object { [int]$_.team })
    for ($n = $fighters.Count; $n -lt $Agents; $n++) {
        $tid = 100
        while ($usedTeams -contains $tid) { $tid++ }
        $usedTeams += $tid

        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        $bytes = New-Object byte[] 24
        $rng.GetBytes($bytes)
        $token = ($bytes | ForEach-Object { $_.ToString("x2") }) -join ''

        $newId = "agent$($n + 1)"
        $null = $existing.Add([pscustomobject]@{
            id    = $newId
            team  = $tid
            token = $token
            admin = $false
        })
        Write-Host ("    新增 {0,-10} team={1,-5} token={2}..." -f $newId, $tid, $token.Substring(0, 12))
    }

    $newCfg = [pscustomobject]@{
        bind      = $cfg.bind
        port      = $cfg.port
        rateLimit = $cfg.rateLimit
        agents    = $existing
    }
    # 必须写「无 BOM」的 UTF-8。PowerShell 的 Set-Content -Encoding UTF8 会加 BOM，
    # 而 Java 侧读 JSON 时遇到 BOM 会解析失败，表现为所有 agent 都变成空 token。
    $json = $newCfg | ConvertTo-Json -Depth 6
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($cfgPath, $json, $utf8NoBom)

    # 服务器启动时读的是旧配置，必须重启才能加载新 agent
    Write-Host "  重启服务器以加载新配置..." -ForegroundColor Yellow
    Stop-Server
    Start-Sleep -Milliseconds 800
    Remove-Item $outLog, $errLog -Force -ErrorAction SilentlyContinue
    $Script:ServerProc = Start-Process -FilePath $JavaExe `
        -ArgumentList '-jar', $ServerJar `
        -WorkingDirectory $RunDir `
        -RedirectStandardOutput $outLog `
        -RedirectStandardError $errLog `
        -PassThru -WindowStyle Hidden
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/ping" -TimeoutSec 2 -ErrorAction Stop
            if ($r.ok) { break }
        } catch { }
    }
    Write-Host "  已重启（PID $($Script:ServerProc.Id)）" -ForegroundColor Green

    $cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $refAgent = $cfg.agents | Where-Object { $_.admin } | Select-Object -First 1
    $fighters = $cfg.agents | Where-Object { -not $_.admin }
}

Write-Host ("  裁判    {0}" -f $refAgent.id)
Write-Host ("  参战    {0}" -f (($fighters | ForEach-Object { $_.id }) -join ', '))

# ---------------------------------------------------------------- 初始化对局

Write-Head "初始化对局（$Map）"

$setupUrl = "http://127.0.0.1:$Port/v1/$($refAgent.id)/setup?map=$Map&fog=$($Fog.ToString().ToLower())"
$setup = Invoke-RestMethod -Uri $setupUrl -Headers @{ Authorization = "Bearer $($refAgent.token)" } -TimeoutSec 30

if (-not $setup.ok) { throw "setup 失败: $($setup.error)" }

Write-Host "  $($setup.data.message)"
Write-Host ("  地图 {0}  {1}x{2}" -f $setup.data.map, $setup.data.width, $setup.data.height)

if ($setup.data.cores) {
    foreach ($c in $setup.data.cores) {
        Write-Host ("    {0,-10} -> {1} @ ({2},{3})" -f $c.agent, $c.team, $c.coreX, $c.coreY)
    }
}

# ---------------------------------------------------------------- 录像

if ($Record) {
    Write-Head "开始录像"
    $rec = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/$($refAgent.id)/record?action=start&label=$Map" `
        -Method Post -Headers @{ Authorization = "Bearer $($refAgent.token)" } -TimeoutSec 15
    if ($rec.ok) { Write-Host "  $($rec.data.message)" } else { Write-Host "  失败: $($rec.error)" -ForegroundColor Yellow }
}

# ---------------------------------------------------------------- 输出连接信息

Write-Head "AI 连接信息"

Write-Host "  基础地址  http://127.0.0.1:$Port/v1/<agentId>"
Write-Host "  鉴权头    Authorization: Bearer <token>"
Write-Host ""
Write-Host ("  {0,-12} {1,-8} {2}" -f "AGENT", "TEAM", "TOKEN")
Write-Host ("  {0,-12} {1,-8} {2}" -f "-----", "----", "-----")
foreach ($a in $cfg.agents) {
    $tag = if ($a.admin) { "(裁判)" } else { "" }
    Write-Host ("  {0,-12} {1,-8} {2} {3}" -f $a.id, $a.team, $a.token, $tag)
}

Write-Head "可用端点"
@(
    "GET  /ping                                 存活探测",
    "GET  /state                                局面快照",
    "GET  /units  /buildings  /map  /content   视野内的实体与内容目录",
    "GET  /intel                                核心数据情报",
    "GET  /events?since=0                       事件流",
    "GET  /observe                              观战信息",
    "POST /place?x=&y=&block=                   单点建造",
    "POST /place?shape=line&x1=&y1=&x2=&y2=&block=   批量建造",
    "POST /break  /config  /spawn  /chat  /queue    其他操作",
    "POST /command?action=move&units=&x=&y=     指挥单位",
    "POST /control?op=enter&unit=               接管单位",
    "GET  /record  (仅裁判)                     录像控制"
) | ForEach-Object { Write-Host "  $_" }

Write-Head "对局进行中"

Write-Host "  服务器 PID $($Script:ServerProc.Id)"
Write-Host "  日志       $outLog"
if ($KeepRunning) {
    Write-Host "  按 Ctrl+C 停止" -ForegroundColor Yellow
    try {
        while (-not $Script:ServerProc.HasExited) {
            Start-Sleep -Seconds 2
            try {
                $s = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/$($refAgent.id)/state?view=all" `
                    -Headers @{ Authorization = "Bearer $($refAgent.token)" } -TimeoutSec 3
                $line = "  tick=$($s.data.tick)  单位=$($s.data.units.Count)  建筑=$($s.data.buildings.Count)  队伍=$($s.data.teams.Count)"
                Write-Host $line
            } catch { }
        }
        Write-Host "  服务器已退出" -ForegroundColor Yellow
    } finally {
        Stop-Server
    }
} else {
    Write-Host "  服务器在后台运行（-KeepRunning 可前台监控）" -ForegroundColor Green
    Write-Host "  停止：Stop-Process -Id $($Script:ServerProc.Id)"
}
