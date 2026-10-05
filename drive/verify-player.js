// 独立验证 replay/index.html 的核心逻辑：解析 → RLE 解码 → 增量重建。
// 不碰 DOM，只把播放器里那几段纯函数抄过来跑真实录像，看结果是否自洽。
//
// 为什么值得单独验：播放器没有自动化测试环境（headless 浏览器不可用），
// 但「重建出来的状态对不对」是纯逻辑，可以被独立复核。
// 判据：最后一帧重建出的建筑数，必须等于「meta 之后所有 builds 减去所有 removed」
//       的去重计数。两套算法独立算，对得上才算过。

const fs = require('fs');
const path = require('path');

const REC_DIR = 'C:\\dsh\\ai-arena\\server-run\\config\\ai-arena-recordings';

// ── 从 index.html 里抄的同一套逻辑 ──────────────────────────────────────
function decodeRLE(arr, w, h) {
  const out = new Array(w * h).fill(null);
  let p = 0;
  for (let i = 0; i + 1 < arr.length; i += 2) {
    const name = arr[i], run = arr[i + 1];
    for (let k = 0; k < run && p < out.length; k++) out[p++] = name;
  }
  return out;
}

function applySnapTo(m, f) {
  for (const b of (f.builds || [])) m.set(b.x * 100000 + b.y, b);
  for (const [rx, ry] of (f.removed || [])) m.delete(rx * 100000 + ry);
}

function main() {
  const files = fs.readdirSync(REC_DIR).filter(f => f.endsWith('.jsonl'));
  if (!files.length) { console.log('没有录像'); return 1; }
  const newest = files
    .map(f => ({ f, t: fs.statSync(path.join(REC_DIR, f)).mtimeMs }))
    .sort((a, b) => b.t - a.t)[0].f;
  const p = path.join(REC_DIR, newest);
  console.log(`录像: ${newest}  ${fs.statSync(p).size.toLocaleString()} B\n`);

  const lines = fs.readFileSync(p, 'utf8').split('\n').filter(l => l.trim());
  let meta = null;
  const frames = [], events = [];
  for (const l of lines) {
    let j; try { j = JSON.parse(l); } catch { continue; }
    if (j.t === 'meta') meta = j;
    else if (j.t === 'snap') frames.push(j);
    else if (j.t === 'ev') events.push(j);
  }
  console.log(`meta=${meta ? 1 : 0}  frames=${frames.length}  events=${events.length}`);

  // ── 1. 地图 RLE 解码 ────────────────────────────────────────────────
  const md = meta.mapData || {};
  const w = md.w, h = md.h, cells = w * h;
  const floor = decodeRLE(md.floors || [], w, h);
  const ore   = decodeRLE(md.ores   || [], w, h);
  const wall  = decodeRLE(md.walls  || [], w, h);

  const count = a => a.filter(x => x != null).length;
  console.log(`\n== 地图 RLE 解码（${w}x${h} = ${cells} 格）==`);
  console.log(`  floors 段 ${(md.floors||[]).length/2}  解出非空 ${count(floor)} 格`);
  console.log(`  ores   段 ${(md.ores||[]).length/2}  解出矿格 ${count(ore)} 格`);
  console.log(`  walls  段 ${(md.walls||[]).length/2}  解出墙格 ${count(wall)} 格`);
  const okMap = count(floor) === cells;
  console.log(`  地板覆盖全部 ${cells} 格: ${okMap ? 'OK' : '!! 只解出 ' + count(floor)}`);

  // 矿的种类（顺便核对 RLE 之后种类有没有丢）
  const oreKinds = {};
  for (const o of ore) if (o) oreKinds[o] = (oreKinds[o] || 0) + 1;
  console.log(`  矿种类: ${JSON.stringify(oreKinds)}`);

  // ── 2. 增量重建 vs 独立算法 ─────────────────────────────────────────
  // 算法 A：播放器的做法 —— Map 覆盖 + removed 删除
  const A = new Map();
  for (const f of frames) applySnapTo(A, f);

  // 算法 B：独立做法 —— 先收集所有出现过的 key，再剔除所有 removed
  const appeared = new Set(), removedSet = new Set();
  for (const f of frames) {
    for (const b of (f.builds || [])) appeared.add(b.x * 100000 + b.y);
    for (const [rx, ry] of (f.removed || [])) removedSet.add(rx * 100000 + ry);
  }
  const B = [...appeared].filter(k => !removedSet.has(k));

  console.log(`\n== 增量重建 ==`);
  console.log(`  算法A（Map 覆盖+删除）最终 ${A.size} 个建筑`);
  console.log(`  算法B（集合差）      最终 ${B.length} 个建筑`);
  console.log(`  出现过的 key 共 ${appeared.size}，其中被拆 ${removedSet.size}`);
  const okBuild = A.size === B.length;
  console.log(`  两套算法一致: ${okBuild ? 'OK' : '!! 不一致'}`);

  // ── 3. checkpoint 重建正确性 ────────────────────────────────────────
  // 播放器每 100 帧存一份快照，拖动时从最近的 checkpoint 重放。
  // 关键验证：用 checkpoint 路径重建出的状态，必须和「从头重放」完全一样。
  const CKPT = 100;
  const cps = [];
  const cur = new Map();
  frames.forEach((f, i) => {
    if (i % CKPT === 0) cps.push({ frame: i, snapshot: new Map(cur) });
    applySnapTo(cur, f);
  });
  console.log(`\n== checkpoint（每 ${CKPT} 帧）==`);
  console.log(`  存了 ${cps.length} 份`);

  let mismatch = 0, checked = 0;
  for (const target of [0, 1, 99, 100, 101, 250, frames.length - 1]) {
    if (target < 0 || target >= frames.length) continue;
    // 从头重放
    const straight = new Map();
    for (let k = 0; k <= target; k++) applySnapTo(straight, frames[k]);
    // 走 checkpoint
    let cp = cps[0];
    for (const c of cps) { if (c.frame <= target) cp = c; else break; }
    const via = new Map(cp.snapshot);
    for (let k = cp.frame; k <= target; k++) applySnapTo(via, frames[k]);
    checked++;
    const same = straight.size === via.size &&
      [...straight.keys()].every(k2 => via.has(k2));
    if (!same) { mismatch++; console.log(`  帧 ${target}: !! 不一致（${straight.size} vs ${via.size}）`); }
  }
  console.log(`  抽查 ${checked} 个位置，不一致 ${mismatch} 个  ${mismatch ? '!!' : 'OK'}`);

  // ── 4. rot 覆盖率 ───────────────────────────────────────────────────
  let withRot = 0, total = 0;
  for (const f of frames) for (const b of (f.builds || [])) { total++; if (b.rot != null) withRot++; }
  console.log(`\n== rot 覆盖 ==`);
  console.log(`  ${withRot}/${total} 条建筑记录带 rot  ${total && withRot === total ? 'OK' : '(无变化或缺失)'}`);

  const allOk = okMap && okBuild && mismatch === 0;
  console.log(`\n⇒ ${allOk ? '播放器核心逻辑自洽' : '有问题，见上'}`);
  return allOk ? 0 : 1;
}

process.exit(main());
