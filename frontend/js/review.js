import { api, apiUrl, escapeHtml as e, showNotice } from "./api.js";

const VIEWS = ["pending", "approved", "aesthetic_only", "rejected", "all"];
const SAVED_MESSAGES = {
  rejected: "已保存，原因已加入反向提示词",
  aesthetic_only: "已保存为审美达标、数据不足，并更新审美档案",
  approved: "已保存并更新舞蹈审美档案",
  pending: "已改回待审",
};

const $ = (selector) => document.querySelector(selector);
let currentView = new URLSearchParams(location.search).get("view");
if (!VIEWS.includes(currentView)) currentView = "pending";
let refreshTimer = null;

function setMessage(text) {
  $("#msg").textContent = text;
}

// --- summary ------------------------------------------------------------------

async function loadOverview() {
  const data = await api.get("/api/overview");
  for (const [status, count] of Object.entries(data.counts)) {
    const badge = document.querySelector(`[data-count="${status}"]`);
    if (badge) badge.textContent = count;
  }
  const scan = data.latest_scan;
  const parts = [
    "每次刷新都会替换整批待审作者；未审核作者可能再次出现，只有人工排除的作者不会再次进入队列。",
    `${data.stale_rule}。已完成审核记录会保留。`,
    `匹配度已结合 ${data.reference_case_count} 条正面案例，按审美70%和数据质量30%计算。`,
  ];
  if (scan) {
    if (scan.trend_terms.length) parts.push(`本轮日本 TikTok 热歌入口：${scan.trend_terms.slice(0, 5).join("、")}。`);
    parts.push(`最近一次扫描（${scan.finished_at}）从实时专题页首次索引 ${scan.new_live_templates} 条模板，`
      + `本批 ${scan.new_candidates} 位，其中高匹配 ${scan.ranked_candidates} 位、随机探索 ${scan.random_candidates} 位；`
      + `跳过已排除作者 ${scan.skipped_rejected} 位。`);
  }
  parts.push(`当前队列共 ${data.total_in_queue} 位。`);
  $("#summary").textContent = parts.join("");
}

// --- creator rows ---------------------------------------------------------------

function workPreview(work) {
  const media = work.video_url
    ? `<video class="preview-video" src="${e(work.video_url)}" poster="${e(work.cover_url)}" muted playsinline
         preload="none" tabindex="0" role="button" aria-label="播放或暂停作品预览"></video>`
    : work.cover_url ? `<img class="preview-image" src="${e(work.cover_url)}" loading="lazy" alt="作品封面">` : "";
  const dance = work.dance_seed || work.dance_signal ? " 💃舞蹈" : "";
  const ai = work.likely_ai ? " ⚠AI?" : "";
  return `<div class="preview-item">${media}<div>
    <a target="_blank" rel="noopener noreferrer" href="${e(work.url)}">${e(work.title.slice(0, 45) || work.template_id)}</a>
    — ${Number(work.uses).toLocaleString()} uses${dance}${ai}</div></div>`;
}

function creatorRow(c, index) {
  const r = c.review;
  const explore = c.recommendation_type === "随机探索";
  const vp = c.video_content_profile || {};
  const videoEvidence = vp.video_count
    ? `<br><small>视频内容复核：已分析 ${vp.video_count} 条；负面视觉相似扣分 ${c.negative_video_penalty}`
      + (c.negative_video_penalty && c.negative_video_reason ? `；对应提示：${e(c.negative_video_reason)}` : "") + "</small>"
    : "";
  const evidence = (c.reference_match_evidence || []).join("、") || "仅结构代理，待人工审核";
  const value = (v) => e(v ?? "");
  return `<tr data-key="${e(c.key)}" data-status="${e(r.status)}">
    <td><span class="rank">${index + 1}</span></td>
    <td><strong class="creator-name">${e(c.name)}</strong><br>
      <span class="badge ${explore ? "explore" : "match"}">${e(c.recommendation_type || "高匹配")}</span>
      <span class="score">综合 ${c.score} · 审美 ${c.reference_match_score} · 数据 ${c.quality_data_score}</span><br>
      <small>正面案例依据：${e(evidence)}</small>${videoEvidence}<br><small>${e((c.bio || "").slice(0, 180))}</small></td>
    <td>${e(c.japanese_signal)}<br>已索引舞蹈：${c.dance_non_ai_indexed} 条；舞蹈/非AI且≥3k：${c.high_use_non_ai_indexed} 条<br>
      满7天且 uses&lt;1000 已排除：${c.stale_low_use_excluded_count} 条<br>主页总投稿：${c.total_posts ?? "待核"}</td>
    <td>${c.works.map(workPreview).join("")}</td>
    <td>
      <input data-field="cc_id" aria-label="CC ID" placeholder="主页显示的 CapCut ID（不是昵称）" value="${value(r.cc_id)}">
      <input data-field="cc_link" aria-label="CC主页" placeholder="粘贴主页分享链接，自动提取ID" value="${value(r.cc_link)}">
      <button class="btn" type="button" data-action="lookup">从主页链接读取 ID 和投稿数</button>
      <input data-field="tt_link" aria-label="TT主页" placeholder="TT主页链接（可空）" value="${value(r.tt_link)}">
      <label>主页投稿总数（仅供参考）<input data-field="total_posts" type="number" min="0" value="${value(r.total_posts)}"></label>
      <label>≥3000 uses 的非AI舞蹈模板数（仅供排序参考）<input data-field="high_use_posts" type="number" min="0" value="${value(r.high_use_posts)}"></label>
      <label><input data-field="non_ai_confirmed" type="checkbox" ${r.non_ai_confirmed ? "checked" : ""}> 已确认以非AI模板为主</label><br>
      <label><input data-field="dance_confirmed" type="checkbox" ${r.dance_confirmed ? "checked" : ""}> 已确认主要产出优质舞蹈模板</label><br>
      <label>内部优先级 <select data-field="priority">
        <option value="P0" ${r.priority === "P0" ? "selected" : ""}>P0 高审美/稳定舞蹈型</option>
        <option value="P1" ${r.priority !== "P0" ? "selected" : ""}>P1 热点/专长舞蹈型</option></select></label>
      <textarea data-field="specialty" placeholder="舞蹈类型与素材：单人/双人/群舞、手势舞、偶像舞等">${e(r.specialty)}</textarea>
      <textarea data-field="aesthetic_notes" placeholder="包装、节奏、构图、替换性和做得好的case">${e(r.aesthetic_notes)}</textarea>
      <textarea data-field="rejection_reason" placeholder="不通过原因（会自动加入反向提示词）">${e(r.rejection_reason)}</textarea>
      <div class="review-actions">
        <button class="btn approve" type="button" data-action="save" data-status="approved">通过</button>
        <button class="btn potential" type="button" data-action="save" data-status="aesthetic_only">审美达标·数据不足</button>
        <button class="btn reject" type="button" data-action="save" data-status="rejected">排除</button>
        <button class="btn" type="button" data-action="save" data-status="pending">待审</button>
      </div>
    </td></tr>`;
}

async function loadCreators() {
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === currentView);
  });
  const data = await api.get(`/api/creators?view=${currentView}`);
  $("#rows").innerHTML = data.items.map(creatorRow).join("");
  $("#emptyState").hidden = data.items.length > 0;
}

async function reloadAll() {
  try {
    await Promise.all([loadOverview(), loadCreators()]);
    showNotice($("#error"), "");
  } catch (error) {
    showNotice($("#error"), error.message, false);
  }
}

function readForm(row) {
  const body = { key: row.dataset.key };
  row.querySelectorAll("[data-field]").forEach((input) => {
    body[input.dataset.field] = input.type === "checkbox" ? input.checked : input.value;
  });
  return body;
}

async function saveReview(row, status) {
  try {
    await api.post("/api/reviews", { ...readForm(row), status });
    row.dataset.status = status;
    setMessage(SAVED_MESSAGES[status]);
    loadOverview().catch(() => {});
    return true;
  } catch (error) {
    alert(error.message);
    return false;
  }
}

async function lookupProfile(row, button) {
  const field = (name) => row.querySelector(`[data-field="${name}"]`);
  const link = field("cc_link").value.trim();
  if (!link) {
    alert("先粘贴主页分享链接");
    return;
  }
  button.disabled = true;
  button.textContent = "正在读取…";
  try {
    const profile = await api.post("/api/profiles/resolve", { link });
    if (!field("cc_id").value.trim()) field("cc_id").value = profile.cc_id || "";
    if (!field("tt_link").value.trim()) field("tt_link").value = profile.tt_link || "";
    field("total_posts").value = profile.total_posts ?? "";
    if (await saveReview(row, row.dataset.status)) {
      setMessage(`主页：${profile.name}；投稿数已保存。已有 CC ID 保持原值。`);
    }
  } catch (error) {
    alert(`读取失败：${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = "从主页链接读取 ID 和投稿数";
  }
}

// --- video previews --------------------------------------------------------------

function closePreview(video) {
  video.pause();
  video.classList.remove("expanded");
}

async function togglePreview(video) {
  if (!video.paused) {
    video.pause();
    return;
  }
  document.querySelectorAll(".preview-video.expanded").forEach((other) => other !== video && closePreview(other));
  video.classList.add("expanded");
  try {
    await video.play();
  } catch {
    closePreview(video);
  }
}

// --- refresh job -------------------------------------------------------------------

function renderLog(state) {
  const logs = state.logs || [];
  const entries = $("#logEntries");
  $("#logPanel").hidden = logs.length === 0;
  const atBottom = entries.scrollTop + entries.clientHeight >= entries.scrollHeight - 20;
  entries.innerHTML = logs.map((item) =>
    `<div class="log-entry"><time>${e(item.time)}</time><strong>${e(item.stage)}</strong><span>${e(item.message)}</span></div>`).join("");
  if (atBottom) entries.scrollTop = entries.scrollHeight;
}

function setRefreshButton(running, stopping = false) {
  const button = $("#refreshBtn");
  button.dataset.running = running ? "true" : "false";
  button.disabled = stopping;
  button.textContent = running ? (stopping ? "正在停止…" : "■ 停止刷新") : "↻ 手动刷新候选";
}

async function pollRefresh(reloadOnFinish = true) {
  clearTimeout(refreshTimer);
  const status = $("#refreshStatus");
  try {
    const state = await api.get("/api/refresh");
    renderLog(state);
    status.textContent = state.message + (state.running && state.elapsed_seconds !== undefined ? ` · ${state.elapsed_seconds} 秒` : "");
    if (state.running) {
      setRefreshButton(true, Boolean(state.cancel_requested));
      refreshTimer = setTimeout(() => pollRefresh(true), 1000);
      return;
    }
    setRefreshButton(false);
    if (state.finished && reloadOnFinish) {
      status.textContent = `${state.message} 正在载入…`;
      await reloadAll();
    }
  } catch (error) {
    setRefreshButton(false);
    status.textContent = `状态读取失败：${error.message}`;
  }
}

async function toggleRefresh() {
  const button = $("#refreshBtn");
  const status = $("#refreshStatus");
  button.disabled = true;
  try {
    if (button.dataset.running === "true") {
      status.textContent = "正在请求停止刷新…";
      await api.post("/api/refresh/cancel");
      pollRefresh(false);
    } else {
      status.textContent = "正在启动大范围扫描…";
      await api.post("/api/refresh");
      setRefreshButton(true);
      pollRefresh();
    }
  } catch (error) {
    button.disabled = false;
    status.textContent = `操作失败：${error.message}`;
  }
}

// --- exclusions ---------------------------------------------------------------------

async function loadExclusions() {
  const data = await api.get("/api/exclusions");
  $("#exclusionText").value = data.terms.join("\n");
}

async function saveExclusions() {
  try {
    const terms = $("#exclusionText").value.split("\n");
    const data = await api.put("/api/exclusions", { terms });
    $("#exclusionText").value = data.terms.join("\n");
    $("#exclusionMsg").textContent = `已保存 ${data.terms.length} 条，下次扫描生效。`;
  } catch (error) {
    $("#exclusionMsg").textContent = `保存失败：${error.message}`;
  }
}

// --- wiring ---------------------------------------------------------------------------

document.addEventListener("click", (event) => {
  const video = event.target.closest(".preview-video");
  if (video) {
    togglePreview(video);
    return;
  }
  document.querySelectorAll(".preview-video.expanded").forEach(closePreview);

  const viewButton = event.target.closest("[data-view]");
  if (viewButton) {
    currentView = viewButton.dataset.view;
    history.replaceState(null, "", `?view=${currentView}`);
    loadCreators().catch((error) => showNotice($("#error"), error.message, false));
    return;
  }
  const action = event.target.closest("[data-action]");
  if (!action) return;
  const row = action.closest("tr");
  if (action.dataset.action === "save") saveReview(row, action.dataset.status);
  if (action.dataset.action === "lookup") lookupProfile(row, action);
});

document.addEventListener("keydown", (event) => {
  if (event.target.matches(".preview-video") && (event.key === "Enter" || event.key === " ")) {
    event.preventDefault();
    togglePreview(event.target);
  }
});

$("#refreshBtn").addEventListener("click", toggleRefresh);
$("#saveExclusions").addEventListener("click", saveExclusions);
$("#exportLink").href = apiUrl("/api/export/approved.csv");
$("#exclusionPanel").addEventListener("toggle", () => {
  if ($("#exclusionPanel").open) loadExclusions().catch((error) => { $("#exclusionMsg").textContent = error.message; });
});

reloadAll();
pollRefresh(false);
