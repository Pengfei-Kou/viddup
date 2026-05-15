"""HTML report generation for VidDup scan results."""
from __future__ import annotations

import json
from pathlib import Path

from viddup.core.comparator import DuplicateGroup

# ── Helpers ───────────────────────────────────────────────────────────────────

def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} PB"


def _fmt_dur(s: float | None) -> str:
    if s is None:
        return "?"
    h, rem = divmod(int(s), 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


# ── CSS (separate string so no {{ }} escaping needed in the f-string) ─────────

_CSS = """
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#090914;--surface:rgba(255,255,255,.05);--surface2:rgba(255,255,255,.08);
  --border:rgba(255,255,255,.09);--accent:#7c3aed;--accent2:#06b6d4;
  --text:#e2e8f0;--muted:#94a3b8;--green:#10b981;--red:#ef4444;--yellow:#f59e0b;
  font-family:'Inter',system-ui,sans-serif;
}
body{background:var(--bg);color:var(--text);min-height:100vh;padding-bottom:90px}
/* ── Header ── */
.hdr{
  padding:28px 32px 22px;
  background:linear-gradient(135deg,rgba(124,58,237,.18) 0%,rgba(6,182,212,.10) 100%);
  border-bottom:1px solid var(--border);
}
.hdr h1{font-size:1.6rem;font-weight:700;letter-spacing:-.02em;
  background:linear-gradient(90deg,#a78bfa,#22d3ee);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.hdr .sub{color:var(--muted);font-size:.85rem;margin-top:6px}
.stats-row{display:flex;gap:20px;flex-wrap:wrap;margin-top:18px}
.stat-pill{
  background:var(--surface);border:1px solid var(--border);border-radius:8px;
  padding:8px 16px;display:flex;flex-direction:column;gap:2px;
}
.stat-pill .val{font-size:1.25rem;font-weight:700;color:#a78bfa}
.stat-pill .lbl{font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
/* ── Toolbar ── */
.toolbar{
  position:sticky;top:0;z-index:100;
  display:flex;align-items:center;gap:10px;flex-wrap:wrap;
  padding:10px 32px;
  background:rgba(9,9,20,.85);backdrop-filter:blur(12px);
  border-bottom:1px solid var(--border);
}
.btn{
  padding:7px 16px;border-radius:8px;font-size:.83rem;font-weight:500;
  cursor:pointer;border:none;transition:all .15s;
}
.btn-primary{background:linear-gradient(135deg,var(--accent),#4f46e5);color:#fff}
.btn-primary:hover{opacity:.85}
.btn-ghost{background:var(--surface);color:var(--text);border:1px solid var(--border)}
.btn-ghost:hover{background:var(--surface2)}
.btn-danger{background:rgba(239,68,68,.15);color:var(--red);border:1px solid rgba(239,68,68,.3)}
.btn-danger:hover{background:rgba(239,68,68,.25)}
#sel-count{color:var(--muted);font-size:.83rem;margin-left:auto}
/* ── Main content ── */
main{max-width:1100px;margin:0 auto;padding:28px 32px}
.section-title{
  font-size:1rem;font-weight:600;color:var(--muted);letter-spacing:.06em;
  text-transform:uppercase;margin:0 0 16px;padding-bottom:8px;
  border-bottom:1px solid var(--border);
}
/* ── Group card ── */
.group-card{
  background:var(--surface);border:1px solid var(--border);border-radius:14px;
  margin-bottom:18px;overflow:hidden;transition:border-color .2s;
}
.group-card:hover{border-color:rgba(124,58,237,.4)}
.group-hdr{
  display:flex;align-items:center;gap:10px;flex-wrap:wrap;
  padding:12px 18px;border-bottom:1px solid var(--border);
  background:rgba(255,255,255,.02);
}
.group-num{font-weight:700;font-size:.9rem}
.sim-badge{
  padding:2px 10px;border-radius:20px;font-size:.75rem;font-weight:600;
  background:rgba(124,58,237,.2);color:#a78bfa;border:1px solid rgba(124,58,237,.3);
}
.exact-badge{background:rgba(6,182,212,.15);color:#22d3ee;border-color:rgba(6,182,212,.3)}
.reclaim{margin-left:auto;font-size:.78rem;color:var(--yellow)}
/* ── File grid ── */
.file-grid{display:flex;gap:0;flex-wrap:wrap}
.file-card{
  flex:1;min-width:200px;
  display:flex;flex-direction:column;
  border-right:1px solid var(--border);transition:background .15s;cursor:pointer;
}
.file-card:last-child{border-right:none}
.file-card:hover{background:var(--surface2)}
.file-card.marked{background:rgba(239,68,68,.06)}
.file-card.marked:hover{background:rgba(239,68,68,.10)}
/* thumbnail area */
.thumb-wrap{
  position:relative;background:#111;overflow:hidden;
  aspect-ratio:16/9;
}
.thumb-wrap img{width:100%;height:100%;object-fit:cover;display:block}
.thumb-placeholder{
  width:100%;height:100%;display:flex;align-items:center;justify-content:center;
  color:var(--border);font-size:2rem;
}
.badge{
  position:absolute;bottom:8px;left:8px;
  padding:2px 8px;border-radius:6px;font-size:.7rem;font-weight:600;
}
.badge-keep{background:rgba(16,185,129,.9);color:#fff}
.badge-del{background:rgba(239,68,68,.85);color:#fff}
/* file info */
.file-info{padding:10px 14px 12px;flex:1;display:flex;flex-direction:column;gap:4px}
.file-name{font-size:.82rem;font-weight:600;word-break:break-all;line-height:1.3}
.file-meta{font-size:.73rem;color:var(--muted)}
/* checkbox row */
.cb-row{
  padding:8px 14px;border-top:1px solid var(--border);
  display:flex;align-items:center;gap:8px;
}
.cb-row input[type=checkbox]{
  width:16px;height:16px;accent-color:var(--red);cursor:pointer;
}
.cb-label{font-size:.75rem;color:var(--muted)}
/* ── Modal ── */
.modal-overlay{
  position:fixed;inset:0;background:rgba(0,0,0,.7);backdrop-filter:blur(4px);
  z-index:200;display:flex;align-items:center;justify-content:center;
}
.modal-overlay.hidden{display:none}
.modal{
  background:#13131f;border:1px solid var(--border);border-radius:16px;
  width:min(700px,90vw);max-height:80vh;display:flex;flex-direction:column;overflow:hidden;
}
.modal-hdr{
  padding:16px 20px;border-bottom:1px solid var(--border);
  display:flex;align-items:center;justify-content:space-between;
}
.modal-hdr h3{font-size:1rem;font-weight:600}
.modal-body{padding:20px;overflow-y:auto;flex:1}
pre{
  background:#0a0a14;border:1px solid var(--border);border-radius:8px;
  padding:16px;font-size:.8rem;line-height:1.6;color:#86efac;
  white-space:pre-wrap;word-break:break-all;
}
.modal-footer{padding:14px 20px;border-top:1px solid var(--border);display:flex;gap:10px;justify-content:flex-end}
/* ── Sticky bottom bar ── */
.bottom-bar{
  position:fixed;bottom:0;left:0;right:0;z-index:150;
  padding:12px 32px;
  background:rgba(9,9,20,.9);backdrop-filter:blur(16px);
  border-top:1px solid var(--border);
  display:flex;align-items:center;gap:12px;
}
.bottom-bar .tip{font-size:.78rem;color:var(--muted);margin-right:auto}
"""

# ── JavaScript ────────────────────────────────────────────────────────────────

_JS = """
const marked = new Set();

function init() {
  // Auto-mark all non-suggested files
  document.querySelectorAll('.file-card:not(.suggested)').forEach(card => {
    setMark(card, true);
  });
  updateCount();
}

function setMark(card, on) {
  const cb = card.querySelector('input[type=checkbox]');
  if (!cb) return;
  cb.checked = on;
  card.classList.toggle('marked', on);
  const lbl = card.querySelector('.cb-label');
  if (lbl) lbl.textContent = on ? '已选中删除' : '保留';
  if (on) marked.add(cb.dataset.path);
  else marked.delete(cb.dataset.path);
}

function toggleCard(card) {
  const cb = card.querySelector('input[type=checkbox]');
  if (!cb) return;
  setMark(card, !cb.checked);
  updateCount();
}

function toggleCb(cb) {
  const card = cb.closest('.file-card');
  card.classList.toggle('marked', cb.checked);
  const lbl = card.querySelector('.cb-label');
  if (lbl) lbl.textContent = cb.checked ? '已选中删除' : '保留';
  if (cb.checked) marked.add(cb.dataset.path);
  else marked.delete(cb.dataset.path);
  updateCount();
}

function autoSelect() {
  document.querySelectorAll('.file-card').forEach(card => {
    setMark(card, !card.classList.contains('suggested'));
  });
  updateCount();
}

function clearAll() {
  document.querySelectorAll('.file-card').forEach(card => setMark(card, false));
  updateCount();
}

function updateCount() {
  const n = marked.size;
  document.getElementById('sel-count').textContent =
    n > 0 ? `已选 ${n} 个文件` : '';
  document.getElementById('gen-btn').disabled = n === 0;
}

function generateScript() {
  if (marked.size === 0) return;
  const lines = [
    '#!/bin/bash',
    '# VidDup 自动生成的删除脚本',
    '# ⚠️  请仔细确认每一行后再执行！',
    '',
    ...Array.from(marked).map(p => `rm -v "${p}"`),
  ];
  document.getElementById('script-pre').textContent = lines.join('\\n');
  document.getElementById('modal').classList.remove('hidden');
}

function copyScript() {
  const text = document.getElementById('script-pre').textContent;
  navigator.clipboard.writeText(text).then(() => {
    const btn = document.getElementById('copy-btn');
    const orig = btn.textContent;
    btn.textContent = '✓ 已复制！';
    setTimeout(() => { btn.textContent = orig; }, 2000);
  });
}

function closeModal() {
  document.getElementById('modal').classList.add('hidden');
}

document.addEventListener('DOMContentLoaded', init);
"""


# ── HTML builder ──────────────────────────────────────────────────────────────

def _thumb_img(thumb_b64: str | None) -> str:
    if thumb_b64:
        return f'<img src="data:image/jpeg;base64,{thumb_b64}" alt="frame" loading="lazy">'
    return '<div class="thumb-placeholder">🎬</div>'


def _file_card_html(rec, is_suggested: bool, thumb_b64: str | None) -> str:
    name = Path(rec.path).name
    meta = f"{_human_size(rec.file_size)} · {rec.resolution} · {rec.codec or '?'} · {_fmt_dur(rec.duration)}"
    keep_badge = '<span class="badge badge-keep">★ 建议保留</span>' if is_suggested else '<span class="badge badge-del">待删除</span>'
    suggested_cls = " suggested" if is_suggested else ""
    cb_label = "保留" if is_suggested else "已选中删除"
    path_esc = rec.path.replace('"', '\\"')
    return f"""
<div class="file-card{suggested_cls}" onclick="toggleCard(this)">
  <div class="thumb-wrap">
    {_thumb_img(thumb_b64)}
    {keep_badge}
  </div>
  <div class="file-info">
    <div class="file-name" title="{rec.path}">{name}</div>
    <div class="file-meta">{meta}</div>
  </div>
  <div class="cb-row">
    <input type="checkbox" data-path="{path_esc}"
      {"" if is_suggested else "checked"}
      onclick="event.stopPropagation();toggleCb(this)">
    <span class="cb-label">{cb_label}</span>
  </div>
</div>"""


def _group_card_html(group: DuplicateGroup, is_exact: bool) -> str:
    from viddup.utils.ffmpeg_utils import extract_thumbnail_base64

    sim_cls = "exact-badge" if is_exact else ""
    sim_text = "精确副本" if is_exact else f"{group.similarity * 100:.1f}% 相似"

    files_html = ""
    for rec in group.records:
        is_suggested = rec.path == group.suggested_keep.path
        mid = (rec.duration or 60.0) / 2
        thumb = extract_thumbnail_base64(Path(rec.path), mid) if Path(rec.path).exists() else None
        files_html += _file_card_html(rec, is_suggested, thumb)

    return f"""
<div class="group-card">
  <div class="group-hdr">
    <span class="group-num">组 #{group.group_id}</span>
    <span class="sim-badge {sim_cls}">{sim_text}</span>
    <span class="reclaim">可释放 {_human_size(group.reclaimable_size)}</span>
  </div>
  <div class="file-grid">{files_html}</div>
</div>"""


def write_html_report(
    scan_paths: tuple[Path, ...],
    total_videos: int,
    exact_groups: list[DuplicateGroup],
    similar_groups: list[DuplicateGroup],
    output_dir: Path,
) -> Path:
    """
    Generate a self-contained HTML report with embedded thumbnails.

    The report is fully offline — no external requests except Google Fonts.
    Returns the path to the generated HTML file.
    """
    from datetime import datetime, timezone
    scan_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    paths_str = ", ".join(str(p) for p in scan_paths)

    exact_reclaim = sum(g.reclaimable_size for g in exact_groups)
    sim_reclaim = sum(g.reclaimable_size for g in similar_groups)
    total_reclaim = exact_reclaim + sim_reclaim

    # Build group sections
    exact_html = "".join(_group_card_html(g, True) for g in exact_groups)
    sim_html = "".join(_group_card_html(g, False) for g in similar_groups)

    exact_section = f"""
<section style="margin-bottom:36px">
  <p class="section-title">⚡ 精确重复 — {len(exact_groups)} 组</p>
  {exact_html or '<p style="color:var(--muted);font-size:.85rem">未发现精确重复</p>'}
</section>""" if exact_groups else ""

    sim_section = f"""
<section style="margin-bottom:36px">
  <p class="section-title">🎯 近似重复 — {len(similar_groups)} 组</p>
  {sim_html or '<p style="color:var(--muted);font-size:.85rem">未发现近似重复</p>'}
</section>""" if similar_groups else ""

    no_dup = ""
    if not exact_groups and not similar_groups:
        no_dup = '<p style="color:var(--muted);text-align:center;padding:60px 0;font-size:1.1rem">🎉 未发现重复视频</p>'

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VidDup 扫描报告</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>{_CSS}</style>
</head>
<body>

<header class="hdr">
  <h1>🔍 VidDup 扫描报告</h1>
  <div class="sub">扫描时间: {scan_time} · 目录: {paths_str}</div>
  <div class="stats-row">
    <div class="stat-pill"><span class="val">{total_videos}</span><span class="lbl">视频总数</span></div>
    <div class="stat-pill"><span class="val">{len(exact_groups)}</span><span class="lbl">精确重复组</span></div>
    <div class="stat-pill"><span class="val">{len(similar_groups)}</span><span class="lbl">近似重复组</span></div>
    <div class="stat-pill"><span class="val">{_human_size(total_reclaim)}</span><span class="lbl">可释放空间</span></div>
  </div>
</header>

<div class="toolbar">
  <button class="btn btn-ghost" onclick="autoSelect()">自动选择（标记非建议文件）</button>
  <button class="btn btn-ghost" onclick="clearAll()">清除选择</button>
  <span id="sel-count"></span>
</div>

<main>
  {exact_section}
  {sim_section}
  {no_dup}
</main>

<div class="bottom-bar">
  <span class="tip">勾选要删除的文件 → 生成删除命令 → 在终端执行</span>
  <span id="sel-count-2"></span>
  <button id="gen-btn" class="btn btn-danger" onclick="generateScript()" disabled>
    🗑 生成删除命令
  </button>
</div>

<!-- Modal -->
<div id="modal" class="modal-overlay hidden" onclick="if(event.target===this)closeModal()">
  <div class="modal">
    <div class="modal-hdr">
      <h3>删除命令（Shell 脚本）</h3>
      <button class="btn btn-ghost" style="padding:4px 10px" onclick="closeModal()">✕</button>
    </div>
    <div class="modal-body">
      <p style="font-size:.8rem;color:var(--muted);margin-bottom:12px">
        ⚠️ 请在终端中执行以下命令。删除操作不可撤销，请确认后再执行。
      </p>
      <pre id="script-pre"></pre>
    </div>
    <div class="modal-footer">
      <button id="copy-btn" class="btn btn-primary" onclick="copyScript()">复制到剪贴板</button>
      <button class="btn btn-ghost" onclick="closeModal()">关闭</button>
    </div>
  </div>
</div>

<script>
{_JS}
// sync second count badge
setInterval(() => {{
  const a = document.getElementById('sel-count');
  const b = document.getElementById('sel-count-2');
  if (b) b.textContent = a ? a.textContent : '';
}}, 200);
</script>
</body>
</html>"""

    output_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = output_dir / f"viddup_report_{ts}.html"
    report_path.write_text(html, encoding="utf-8")
    return report_path
