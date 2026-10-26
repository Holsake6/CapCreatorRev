// Shared helpers for every page. No build step, no framework.
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const fmt = (n) => Number(n || 0).toLocaleString('ja-JP');
const SLUG = (location.pathname.match(/^\/c\/([a-z0-9-]+)/) || [])[1] || null;

async function api(path, options = {}) {
  const opts = {...options};
  if (opts.body && !(opts.body instanceof FormData) && typeof opts.body !== 'string') {
    opts.body = JSON.stringify(opts.body);
    opts.headers = {'Content-Type': 'application/json', ...(opts.headers || {})};
  }
  const response = await fetch(path, opts);
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (_) { data = text; }
  if (!response.ok) throw new Error((data && data.error) || text || response.statusText);
  return data;
}

function toast(message, bad = false) {
  let box = $('#toast');
  if (!box) { box = document.createElement('div'); box.id = 'toast'; box.className = 'toast'; document.body.append(box); }
  box.textContent = message;
  box.className = 'toast show' + (bad ? ' bad' : '');
  clearTimeout(box._t);
  box._t = setTimeout(() => { box.className = 'toast'; }, bad ? 6000 : 2600);
}

async function pollJob(id, {onLog, onDone, logBox} = {}) {
  while (true) {
    const job = await api('/api/jobs/' + id);
    if (logBox) { logBox.hidden = false; logBox.textContent = job.log.join('\n'); logBox.scrollTop = logBox.scrollHeight; }
    if (onLog) onLog(job);
    if (job.status !== 'running') { if (onDone) onDone(job); return job; }
    await new Promise((r) => setTimeout(r, 1500));
  }
}

function styleColor(p) {
  if (p == null) return 'background:#f0f2f7;color:#8a90a5';
  if (p >= 70) return 'background:#dff7ea;color:#087142';
  if (p >= 45) return 'background:#fff0b8;color:#765800';
  return 'background:#ffe4e8;color:#a62f42';
}

function mediaTag(item, {autoplay = false, controls = true} = {}) {
  const src = item.media || item.video_url || '';
  const poster = item.cover_url || '';
  if (src) {
    return `<video src="${esc(src)}" ${poster ? `poster="${esc(poster)}"` : ''} ${controls ? 'controls' : ''} muted playsinline loop preload="${autoplay ? 'auto' : 'none'}" ${autoplay ? 'autoplay' : ''}></video>`;
  }
  return poster ? `<img class="thumb" src="${esc(poster)}" loading="lazy" alt="封面">` : '<div class="thumb empty">无预览</div>';
}

async function renderTopbar(active) {
  const bar = $('#topbar');
  if (!bar) return null;
  let cat = null;
  if (SLUG) {
    try { cat = await api('/api/c/' + SLUG); } catch (e) { toast(e.message, true); }
  }
  const tabs = SLUG ? `<nav class="tabs">
      <a href="/c/${SLUG}" class="${active === 'review' ? 'on' : ''}">审核作者</a>
      <a href="/c/${SLUG}/train" class="${active === 'train' ? 'on' : ''}">风格训练</a>
      <a href="/c/${SLUG}/examples" class="${active === 'examples' ? 'on' : ''}">示例与设置</a>
      <a href="/c/${SLUG}/profile" class="${active === 'profile' ? 'on' : ''}">风格档案</a></nav>` : '';
  const s = cat && cat.summary;
  bar.innerHTML = `<a class="brand" href="/"><i>C</i>CapCut 创作者雷达</a>
    ${cat ? `<span class="pill"><b>${esc(cat.config.name)}</b></span>` : ''}${tabs}<span class="spacer"></span>
    ${s && s.model_code ? `<span class="pill">风格档案 <span class="code" style="font-size:12px;padding:1px 6px">${esc(s.model_code)}</span> 置信 <b>${Math.round(s.confidence * 100)}%</b></span>` : ''}
    <a class="pill" href="/doctor">网络检查</a>`;
  return cat;
}
