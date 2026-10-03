# AI 竞技场 · 全功能压力测试
#
# 五个阶段：
#   1. 功能覆盖    全部 18 个端点顺序验证
#   2. 并发读      RunspacePool 多线程同时轮询（模拟 N 个 AI 同时读局面）
#   3. 高频写      批量建造 / 指挥 / 生成 / 发言
#   4. 边界与错误  越界 / 超限 / 越权 / 游标过期
#   5. 稳定性      持续轮询，监控服务器内存与响应延迟
#
# 用法：
#   .\stress-test.ps1                       默认配置
#   .\stress-test.ps1 -Threads 16 -Seconds 60
#   .\stress-test.ps1 -SkipStability        跳过第 5 阶段

[CmdletBinding()]
param(
    [int]$Threads = 12,
    [int]$PerThread = 40,
    [int]$Seconds = 45,
    [switch]$SkipStability,
    [int]$Port = 7199,
    [string]$ServerJar = "C:\dsh\Mindustry-src\server\build\libs\server-release.jar",
    [string]$JavaExe = "C:\dsh\zulu17\zulu17.68.203-ca-jdk17.0.20.1-win_x64\bin\java.exe",
    [string]$RunDir = "C:\dsh\ai-arena\server-run"
)

$ErrorActionPreference = 'Continue'
$Script:ServerProc = $null
$Script:Results = [System.Collections.ArrayList]@()

# ---------------------------------------------------------------- 工具

function Say($t) { Write-Host ""; Write-Host "=== $t ===" -ForegroundColor Cyan }
function Sub($t) { Write-Host "--- $t" -ForegroundColor DarkCyan }

function Record($stage, $name, $ok, $ms, $note) {
    # [bool] 强制转换：否则 PowerShell 可能把 $ok 存成字符串，
    # 汇总时 Where-Object { $_.Ok } 判定失效（表现为通过数显示为空）。
    $null = $Script:Results.Add([pscustomobject]@{
        Stage = $stage; Name = $name; Ok = [bool]$ok; Ms = [int]$ms; Note = $note
    })
}

# 统一的请求函数：返回 @{ Code; Body; Ms }
function Req($method, $path, $token, $body) {
    $url = "http://127.0.0.1:$Port$path"
    $args = @('-sS', '-o', '-', '-w', "`n%{http_code}", '--max-time', '25')
    if ($method -ne 'GET') { $args += @('-X', $method) }
    if ($token) { $args += @('-H', "Authorization: Bearer $token") }
    if ($body) { $args += @('-d', $body) }
    $args += $url

    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $out = (& curl.exe @args 2>&1) -join "`n"
    $sw.Stop()

    $lines = $out -split "`n"
    $code = $lines[-1].Trim()
    $text = ($lines[0..([Math]::Max(0, $lines.Count - 2))] -join "`n").Trim()

    return @{ Code = $code; Body = $text; Ms = $sw.ElapsedMilliseconds }
}

function Assert($stage, $name, $r, $expectCode) {
    $ok = ($r.Code -eq $expectCode)
    $note = $r.Body
    if ($note.Length -gt 100) { $note = $note.Substring(0, 100) + "..." }
    Record $stage $name $ok $r.Ms $note
    $mark = if ($ok) { "OK  " } else { "FAIL" }
    $color = if ($ok) { "Green" } else { "Red" }
    Write-Host ("  [{0}] {1,-44} {2,5}ms  HTTP {3}" -f $mark, $name, $r.Ms, $r.Code) -ForegroundColor $color
    if (-not $ok) { Write-Host "         $note" -ForegroundColor DarkGray }
    # 刻意不返回值 —— 否则调用处写 `Assert ...` 时 PowerShell 会把布尔结果打印出来
}

# ---------------------------------------------------------------- 启动

Say "启动服务器"

$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) { throw "端口 $Port 已被占用" }

$outLog = Join-Path $RunDir "stress-out.log"
$errLog = Join-Path $RunDir "stress-err.log"
Remove-Item $outLog, $errLog -Force -ErrorAction SilentlyContinue

$Script:ServerProc = Start-Process -FilePath $JavaExe `
    -ArgumentList '-jar', $ServerJar `
    -WorkingDirectory $RunDir `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog `
    -PassThru -WindowStyle Hidden

Write-Host "  PID $($Script:ServerProc.Id)"

for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Milliseconds 500
    if ($Script:ServerProc.HasExited) { throw "服务器提前退出" }
    try { if ((Invoke-RestMethod "http://127.0.0.1:$Port/ping" -TimeoutSec 2).ok) { break } } catch { }
}
Write-Host "  就绪" -ForegroundColor Green

$cfg = Get-Content (Join-Path $RunDir "config\ai-arena.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$refAgent = $cfg.agents | Where-Object { $_.admin } | Select-Object -First 1
$fighters = @($cfg.agents | Where-Object { -not $_.admin })
$refTok = $refAgent.token
$tok0 = $fighters[0].token
$id0 = $fighters[0].id

Write-Host "  裁判 $($refAgent.id)  参战 $(($fighters | ForEach-Object { $_.id }) -join ', ')"

# 初始化对局
$setup = Req 'GET' "/v1/$($refAgent.id)/setup?map=veins" $refTok
if ($setup.Code -ne '200') { throw "setup 失败: $($setup.Body)" }
Write-Host "  对局已初始化" -ForegroundColor Green

Start-Sleep -Seconds 3

# ================================================================ 阶段 1

Say "阶段 1 / 功能覆盖（18 个端点）"

Sub "读端点"
Assert 'cover' 'GET /ping'                      (Req 'GET' '/ping' $null) '200'
Assert 'cover' 'GET /state'                     (Req 'GET' "/v1/$id0/state" $tok0) '200'
Assert 'cover' 'GET /units'                     (Req 'GET' "/v1/$id0/units" $tok0) '200'
Assert 'cover' 'GET /buildings'                 (Req 'GET' "/v1/$id0/buildings" $tok0) '200'
Assert 'cover' 'GET /map 区域模式'               (Req 'GET' "/v1/$id0/map?x=55&y=98&w=8&h=8" $tok0) '200'
Assert 'cover' 'GET /map 全图模式'               (Req 'GET' "/v1/$id0/map" $tok0) '200'
Assert 'cover' 'GET /content'                   (Req 'GET' "/v1/$id0/content" $tok0) '200'
Assert 'cover' 'GET /intel'                     (Req 'GET' "/v1/$id0/intel" $tok0) '200'
Assert 'cover' 'GET /events'                    (Req 'GET' "/v1/$id0/events?since=0" $tok0) '200'
Assert 'cover' 'GET /observe'                   (Req 'GET' "/v1/$id0/observe" $tok0) '200'
Assert 'cover' 'GET /queue'                     (Req 'GET' "/v1/$id0/queue" $tok0) '200'
Assert 'cover' 'GET /maps (裁判)'                (Req 'GET' "/v1/$($refAgent.id)/maps" $refTok) '200'
Assert 'cover' 'GET /record (裁判)'              (Req 'GET' "/v1/$($refAgent.id)/record" $refTok) '200'

# 取单位位置
$u = (Req 'GET' "/v1/$id0/units" $tok0).Body | ConvertFrom-Json
$uid = $u.data.units[0].id
$tx = [int]([int]$u.data.units[0].x / 8)
$ty = [int]([int]$u.data.units[0].y / 8)

Sub "写端点"
Assert 'cover' 'POST /place 单点'                (Req 'POST' "/v1/$id0/place?x=$($tx+3)&y=$($ty+3)&block=conveyor" $tok0) '200'
Assert 'cover' 'POST /place shape=line'          (Req 'POST' "/v1/$id0/place?shape=line&x1=$($tx+3)&y1=$($ty+5)&x2=$($tx+7)&y2=$($ty+5)&block=conveyor" $tok0) '200'
Assert 'cover' 'POST /place shape=area'          (Req 'POST' "/v1/$id0/place?shape=area&x1=$($tx+3)&y1=$($ty+7)&x2=$($tx+5)&y2=$($ty+9)&block=conveyor" $tok0) '200'
Assert 'cover' 'POST /place shape=circle'        (Req 'POST' "/v1/$id0/place?shape=circle&x=$($tx+10)&y=$($ty+10)&radius=2&block=conveyor" $tok0) '200'
Assert 'cover' 'POST /place shape=outline'       (Req 'POST' "/v1/$id0/place?shape=outline&x1=$($tx-6)&y1=$($ty-6)&x2=$($tx-2)&y2=$($ty-2)&block=conveyor" $tok0) '200'
Assert 'cover' 'POST /break'                     (Req 'POST' "/v1/$id0/break?x=$($tx+3)&y=$($ty+3)" $tok0) '200'
Assert 'cover' 'POST /config'                    (Req 'POST' "/v1/$id0/config?x=61&y=104&value=7" $tok0) '200'
Assert 'cover' 'POST /spawn'                     (Req 'POST' "/v1/$id0/spawn?type=mono" $tok0) '200'
Assert 'cover' 'POST /chat'                      (Req 'POST' "/v1/$id0/chat?text=stress-test" $tok0) '200'
Assert 'cover' 'POST /command move'              (Req 'POST' "/v1/$id0/command?action=move&units=$uid&x=$($tx+6)&y=$($ty+6)" $tok0) '200'
Assert 'cover' 'POST /command setStance'         (Req 'POST' "/v1/$id0/command?action=setStance&units=$uid&stance=holdFire&enable=true" $tok0) '200'
Assert 'cover' 'POST /command setCommand'        (Req 'POST' "/v1/$id0/command?action=setCommand&units=$uid&cmd=mine" $tok0) '200'
Assert 'cover' 'POST /control enter'             (Req 'POST' "/v1/$id0/control?op=enter&unit=$uid" $tok0) '200'
Assert 'cover' 'POST /control fire'              (Req 'POST' "/v1/$id0/control?op=fire&x=$($tx+5)&y=$($ty+5)&on=true" $tok0) '200'
Assert 'cover' 'POST /control release'           (Req 'POST' "/v1/$id0/control?op=release" $tok0) '200'
Assert 'cover' 'POST /queue?clear'               (Req 'POST' "/v1/$id0/queue?clear=true" $tok0) '200'

# ================================================================ 阶段 2

Say "阶段 2 / 并发读（$Threads 线程 × $PerThread 次）"

$paths = @("/v1/$id0/state", "/v1/$id0/units", "/v1/$id0/buildings", "/v1/$id0/intent".Replace('/intent','/intel'))
$tokenMap = @{}
foreach ($f in $fighters) { $tokenMap[$f.id] = $f.token }

$pool = [runspacefactory]::CreateRunspacePool(1, $Threads)
$pool.Open()
$jobs = @()

$sw = [System.Diagnostics.Stopwatch]::StartNew()

for ($t = 0; $t -lt $Threads; $t++) {
    $f = $fighters[$t % $fighters.Count]
    $ps = [powershell]::Create()
    $ps.RunspacePool = $pool
    $null = $ps.AddScript({
        param($port, $agentId, $token, $count)
        # PowerShell 5.1 里 HttpClient 需要显式加载程序集；
        # 而且 RunspacePool 的每个 runspace 是独立的，必须在这里加载而不是脚本开头。
        Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue
        $lat = New-Object System.Collections.ArrayList
        $okc = 0; $badc = 0
        $http = New-Object System.Net.Http.HttpClient
        $http.Timeout = [TimeSpan]::FromSeconds(20)
        $http.DefaultRequestHeaders.Add('Authorization', "Bearer $token")

        for ($i = 0; $i -lt $count; $i++) {
            $p = @('/state', '/units', '/buildings')[($i % 3)]
            $url = "http://127.0.0.1:$port/v1/$agentId$p"
            $s = [System.Diagnostics.Stopwatch]::StartNew()
            try {
                $resp = $http.GetAsync($url).Result
                $null = $resp.Content.ReadAsStringAsync().Result
                $null = $lat.Add($s.ElapsedMilliseconds)
                if ($resp.IsSuccessStatusCode) { $okc++ } else { $badc++ }
            } catch { $badc++ }
            $s.Stop()
        }
        $http.Dispose()
        return @{ Lat = $lat; Ok = $okc; Bad = $badc }
    }).AddArgument($Port).AddArgument($f.id).AddArgument($f.token).AddArgument($PerThread)

    $jobs += @{ PS = $ps; H = $ps.BeginInvoke() }
}

$agg = @{ Lat = New-Object System.Collections.ArrayList; Ok = 0; Bad = 0 }
foreach ($j in $jobs) {
    try {
        $r = $j.PS.EndInvoke($j.H)
        if ($r) {
            foreach ($v in $r[0].Lat) { $null = $agg.Lat.Add($v) }
            $agg.Ok += $r[0].Ok
            $agg.Bad += $r[0].Bad
        }
    } catch { }
    $j.PS.Dispose()
}
$pool.Close()
$sw.Stop()

$total = $agg.Ok + $agg.Bad
$sorted = $agg.Lat | Sort-Object
$p50 = if ($sorted.Count) { $sorted[[int]($sorted.Count * 0.5)] } else { 0 }
$p95 = if ($sorted.Count) { $sorted[[int]($sorted.Count * 0.95)] } else { 0 }
$p99 = if ($sorted.Count) { $sorted[[int]($sorted.Count * 0.99)] } else { 0 }
$avg = if ($sorted.Count) { [int](($sorted | Measure-Object -Average).Average) } else { 0 }

Write-Host ("  请求总数   {0}" -f $total)
Write-Host ("  成功/失败  {0} / {1}" -f $agg.Ok, $agg.Bad) -ForegroundColor $(if ($agg.Bad -eq 0) { 'Green' } else { 'Yellow' })
Write-Host ("  耗时       {0:N2} 秒  ({1:N0} req/s)" -f ($sw.ElapsedMilliseconds / 1000), ($total / ($sw.ElapsedMilliseconds / 1000)))
Write-Host ("  延迟       avg {0}ms  p50 {1}ms  p95 {2}ms  p99 {3}ms" -f $avg, $p50, $p95, $p99)
Record 'concurrent' "并发读 $Threads 线程 x $PerThread" ($agg.Bad -eq 0) $avg "total=$total ok=$($agg.Ok) bad=$($agg.Bad) p95=${p95}ms"

# ================================================================ 阶段 3

Say "阶段 3 / 高频写"

Sub "连续批量建造（每批 ≤200 格）"
$built = 0; $failed = 0
for ($i = 0; $i -lt 20; $i++) {
    $bx = $tx + ($i % 5) * 3 - 6
    $by = $ty + [int]($i / 5) * 3 + 12
    $r = Req 'POST' "/v1/$id0/place?shape=area&x1=$bx&y1=$by&x2=$($bx+2)&y2=$($by+2)&block=conveyor" $tok0
    if ($r.Code -eq '200') { $built++ } else { $failed++ }
}
Write-Host ("  20 次批量建造：成功 {0}  失败 {1}" -f $built, $failed) -ForegroundColor $(if ($failed -eq 0) { 'Green' } else { 'Yellow' })
Record 'write' '20x 批量建造 (3x3)' ($failed -eq 0) 0 "ok=$built fail=$failed"

Sub "连续生成单位（人口上限会拦）"
$spawnOk = 0; $spawnCap = 0
for ($i = 0; $i -lt 30; $i++) {
    $r = Req 'POST' "/v1/$id0/spawn?type=mono" $tok0
    if ($r.Code -eq '200') { $spawnOk++ }
    elseif ($r.Body -match 'unit cap') { $spawnCap++ }
}
Write-Host ("  30 次生成：成功 {0}  人口拦截 {1}" -f $spawnOk, $spawnCap) -ForegroundColor Green
Record 'write' '30x spawn (含人口上限)' $true 0 "ok=$spawnOk cap=$spawnCap"

Sub "连续指挥"
$cmdOk = 0; $cmdFail = 0
$us = (Req 'GET' "/v1/$id0/units" $tok0).Body | ConvertFrom-Json
$ids = ($us.data.units | Select-Object -First 5 | ForEach-Object { $_.id }) -join ','
for ($i = 0; $i -lt 20; $i++) {
    $r = Req 'POST' "/v1/$id0/command?action=move&units=$ids&x=$($tx+($i%7))&y=$($ty+($i%5))" $tok0
    if ($r.Code -eq '200') { $cmdOk++ } else { $cmdFail++ }
}
Write-Host ("  20 次指挥：成功 {0}  失败 {1}" -f $cmdOk, $cmdFail) -ForegroundColor $(if ($cmdFail -eq 0) { 'Green' } else { 'Yellow' })
Record 'write' '20x 多单位指挥' ($cmdFail -eq 0) 0 "ok=$cmdOk fail=$cmdFail"

Sub "连续事件轮询（游标推进）"
$since = 0; $evTotal = 0; $evOk = 0
for ($i = 0; $i -lt 15; $i++) {
    $r = Req 'GET' "/v1/$id0/events?since=$since&limit=100" $tok0
    if ($r.Code -eq '200') {
        $evOk++
        $j = $r.Body | ConvertFrom-Json
        $evTotal += $j.data.count
        $since = $j.data.nextSince
    }
}
Write-Host ("  15 次事件轮询：成功 {0}  累计事件 {1}  最终游标 {2}" -f $evOk, $evTotal, $since) -ForegroundColor Green
Record 'write' '15x 事件轮询' ($evOk -eq 15) 0 "events=$evTotal since=$since"

# ================================================================ 阶段 4

Say "阶段 4 / 边界与错误路径"

Sub "坐标与范围"
Assert 'edge' '越界坐标'          (Req 'POST' "/v1/$id0/place?x=99999&y=99999&block=conveyor" $tok0) '400'
Assert 'edge' '负坐标'            (Req 'POST' "/v1/$id0/place?x=-5&y=-5&block=conveyor" $tok0) '400'
Assert 'edge' '视野外建造'        (Req 'POST' "/v1/$id0/place?x=5&y=5&block=conveyor" $tok0) '403'
Assert 'edge' '视野外指挥'        (Req 'POST' "/v1/$id0/command?action=move&units=$uid&x=5&y=5" $tok0) '403'

Sub "参数校验"
Assert 'edge' '未知方块'          (Req 'POST' "/v1/$id0/place?x=$tx&y=$ty&block=not-a-block" $tok0) '404'
Assert 'edge' '未知 shape'        (Req 'POST' "/v1/$id0/place?shape=nonsense&x=1&y=1&block=conveyor" $tok0) '400'
Assert 'edge' '未知单位类型'      (Req 'POST' "/v1/$id0/spawn?type=nonsense" $tok0) '404'
Assert 'edge' '未知 command'      (Req 'POST' "/v1/$id0/command?action=nonsense&units=$uid" $tok0) '400'
Assert 'edge' '未知 control op'   (Req 'POST' "/v1/$id0/control?op=nonsense" $tok0) '400'
Assert 'edge' '未知 stance'       (Req 'POST' "/v1/$id0/command?action=setStance&units=$uid&stance=nonsense" $tok0) '404'
Assert 'edge' '缺少必填参数'      (Req 'POST' "/v1/$id0/place" $tok0) '400'
Assert 'edge' '空 units 列表'     (Req 'POST' "/v1/$id0/command?action=move&x=$tx&y=$ty" $tok0) '404'
Assert 'edge' '未知 action'       (Req 'GET' "/v1/$id0/nonsense" $tok0) '404'

Sub "配额上限"
Assert 'edge' '批量超限 (900 格)'  (Req 'POST' "/v1/$id0/place?shape=area&x1=0&y1=0&x2=29&y2=29&block=conveyor" $tok0) '429'
Assert 'edge' 'map 区域超限'       (Req 'GET' "/v1/$id0/map?x=0&y=0&w=200&h=200" $tok0) '400'
Assert 'edge' 'map 负数尺寸'       (Req 'GET' "/v1/$id0/map?x=0&y=0&w=-1&h=-1" $tok0) '400'

Sub "鉴权与越权"
Assert 'edge' '无 token'           (Req 'GET' "/v1/$id0/state" $null) '401'
Assert 'edge' '错误 token'         (Req 'GET' "/v1/$id0/state" 'wrongtokenwrongtoken') '401'
Assert 'edge' '跨 agent 访问'      (Req 'GET' "/v1/$($refAgent.id)/state" $tok0) '403'
Assert 'edge' '非 admin 调 setup'  (Req 'GET' "/v1/$id0/setup?map=veins" $tok0) '403'
Assert 'edge' '非 admin 调 record' (Req 'POST' "/v1/$id0/record?action=start" $tok0) '403'

Sub "视角降级（非 admin 请求 view=all 应静默降级而非报错）"
$r = Req 'GET' "/v1/$id0/state?view=all" $tok0
$j = $r.Body | ConvertFrom-Json
$degraded = ($r.Code -eq '200') -and ($j.data.view -ne 'all')
Record 'edge' 'view=all 静默降级' $degraded $r.Ms "view=$($j.data.view)"
$mark = if ($degraded) { "OK  " } else { "FAIL" }
Write-Host ("  [{0}] {1,-44} {2,5}ms  view={3}" -f $mark, 'view=all 静默降级', $r.Ms, $j.data.view) -ForegroundColor $(if ($degraded) { 'Green' } else { 'Red' })

Sub "裁判特权"
Assert 'edge' '裁判 view=all'      (Req 'GET' "/v1/$($refAgent.id)/state?view=all" $refTok) '200'
Assert 'edge' '裁判 view=2'        (Req 'GET' "/v1/$($refAgent.id)/buildings?view=2" $refTok) '200'
Assert 'edge' '录像路径穿越'       (Req 'GET' "/v1/$($refAgent.id)/record?action=download&name=../../../ai-arena.json" $refTok) '400'

Sub "游标过期"
$r = Req 'GET' "/v1/$id0/events?since=1" $tok0
Record 'edge' '事件游标正常' ($r.Code -eq '200' -or $r.Code -eq '410') $r.Ms "HTTP $($r.Code)"
$mark = if ($r.Code -eq '200' -or $r.Code -eq '410') { "OK  " } else { "FAIL" }
Write-Host ("  [{0}] {1,-44} {2,5}ms  HTTP {3}" -f $mark, '事件游标（200 或 410）', $r.Ms, $r.Code) -ForegroundColor $(if ($mark -eq 'OK  ') { 'Green' } else { 'Red' })

# ================================================================ 阶段 5

if (-not $SkipStability) {
    Say "阶段 5 / 稳定性（$Seconds 秒持续轮询）"

    $stopAt = (Get-Date).AddSeconds($Seconds)
    $okc = 0; $badc = 0; $lat = New-Object System.Collections.ArrayList
    $memSamples = New-Object System.Collections.ArrayList
    $proc = Get-Process -Id $Script:ServerProc.Id -ErrorAction SilentlyContinue
    $tickStart = 0; $tickEnd = 0

    Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue
    $http = New-Object System.Net.Http.HttpClient
    $http.Timeout = [TimeSpan]::FromSeconds(10)
    $http.DefaultRequestHeaders.Add('Authorization', "Bearer $tok0")

    $lastMemCheck = Get-Date
    while ((Get-Date) -lt $stopAt) {
        $p = @('/state', '/units', '/buildings', '/intel', '/events?since=0')[($okc % 5)]
        $s = [System.Diagnostics.Stopwatch]::StartNew()
        try {
            $resp = $http.GetAsync("http://127.0.0.1:$Port/v1/$id0$p").Result
            $body = $resp.Content.ReadAsStringAsync().Result
            $null = $lat.Add($s.ElapsedMilliseconds)
            if ($resp.IsSuccessStatusCode) {
                $okc++
                if ($p -eq '/state' -and $body -match '"tick":(\d+)') {
                    if ($tickStart -eq 0) { $tickStart = [int]$Matches[1] }
                    $tickEnd = [int]$Matches[1]
                }
            } else { $badc++ }
        } catch { $badc++ }
        $s.Stop()

        if (((Get-Date) - $lastMemCheck).TotalSeconds -ge 5) {
            $lastMemCheck = Get-Date
            $pr = Get-Process -Id $Script:ServerProc.Id -ErrorAction SilentlyContinue
            if ($pr) { $null = $memSamples.Add([int]($pr.WorkingSet64 / 1MB)) }
            else { Write-Host "  服务器进程已退出！" -ForegroundColor Red; break }
        }
        Start-Sleep -Milliseconds 50
    }
    $http.Dispose()

    $sorted = $lat | Sort-Object
    $p95 = if ($sorted.Count) { $sorted[[int]($sorted.Count * 0.95)] } else { 0 }
    $avg = if ($sorted.Count) { [int](($sorted | Measure-Object -Average).Average) } else { 0 }
    $memFirst = if ($memSamples.Count) { $memSamples[0] } else { 0 }
    $memLast = if ($memSamples.Count) { $memSamples[$memSamples.Count - 1] } else { 0 }

    Write-Host ("  请求      {0} 成功 / {1} 失败" -f $okc, $badc) -ForegroundColor $(if ($badc -eq 0) { 'Green' } else { 'Yellow' })
    Write-Host ("  延迟      avg {0}ms  p95 {1}ms" -f $avg, $p95)
    Write-Host ("  服务器内存 {0} MB → {1} MB  (增长 {2} MB)" -f $memFirst, $memLast, ($memLast - $memFirst))
    Write-Host ("  tick 推进  {0} → {1}  (+{2}，约 {3:N1} tick/s)" -f $tickStart, $tickEnd, ($tickEnd - $tickStart), (($tickEnd - $tickStart) / $Seconds))

    $alive = -not $Script:ServerProc.HasExited
    Record 'stability' "$Seconds 秒持续轮询" ($badc -eq 0 -and $alive) $avg "ok=$okc bad=$badc mem=${memFirst}->${memLast}MB tick+$($tickEnd-$tickStart)"

    Sub "服务器日志中的异常"
    $errs = Get-Content $outLog -Encoding UTF8 -ErrorAction SilentlyContinue | Select-String -Pattern 'Exception|route error|failed'
    if ($errs) {
        $errs | Select-Object -First 8 | ForEach-Object { Write-Host "  $($_.Line)" -ForegroundColor Red }
        Record 'stability' '日志无异常' $false 0 "$($errs.Count) 条"
    } else {
        Write-Host "  无异常" -ForegroundColor Green
        Record 'stability' '日志无异常' $true 0 "clean"
    }
}

# ================================================================ 汇总

Say "汇总"

$total = $Script:Results.Count
$passed = ($Script:Results | Where-Object { $_.Ok }).Count
$failed = $total - $passed

Write-Host ""
Write-Host ("  总用例  {0}   通过 {1}   失败 {2}" -f $total, $passed, $failed) `
    -ForegroundColor $(if ($failed -eq 0) { 'Green' } else { 'Red' })
Write-Host ""

Write-Host "  按阶段:"
$Script:Results | Group-Object Stage | ForEach-Object {
    # @() 强制数组：PowerShell 5.1 里对单个对象取 .Count 不可靠，
    # 会让只有一条记录的阶段（concurrent）显示成空白。
    $grp = @($_.Group)
    $p = @($grp | Where-Object { $_.Ok }).Count
    $f = $grp.Count - $p
    $c = if ($f -eq 0) { 'Green' } else { 'Red' }
    Write-Host ("    {0,-12} {1,3} 用例   通过 {2,3}   失败 {3,3}" -f $_.Name, $grp.Count, $p, $f) -ForegroundColor $c
}

if ($failed -gt 0) {
    Write-Host ""
    Write-Host "  失败明细:" -ForegroundColor Red
    $Script:Results | Where-Object { -not $_.Ok } | ForEach-Object {
        Write-Host ("    [{0}] {1}" -f $_.Stage, $_.Name) -ForegroundColor Red
        Write-Host ("           {0}" -f $_.Note) -ForegroundColor DarkGray
    }
}

$latencies = $Script:Results | Where-Object { $_.Ms -gt 0 }
if ($latencies) {
    Write-Host ""
    Write-Host "  单次请求延迟（功能测试部分）:"
    $sorted = ($latencies | Sort-Object Ms)
    Write-Host ("    min {0}ms  中位 {1}ms   max {2}ms" -f `
        $sorted[0].Ms, $sorted[[int]($sorted.Count/2)].Ms, $sorted[$sorted.Count-1].Ms)
}

# 保存报告
$report = Join-Path $RunDir "stress-report.json"
$Script:Results | ConvertTo-Json -Depth 4 | Out-File $report -Encoding UTF8
Write-Host ""
Write-Host "  报告已保存 $report"

Say "停止服务器"
if (-not $Script:ServerProc.HasExited) { $Script:ServerProc.Kill() }
Write-Host "  已停止"

if ($failed -gt 0) { exit 1 }
