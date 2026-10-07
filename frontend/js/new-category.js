import { api, escapeHtml as e, showNotice } from "./api.js";

const $ = (selector) => document.querySelector(selector);

function render(state) {
  $("#categoryTitle").textContent = state.category_name;
  document.title = `${state.category_name} · 正面学习`;
  if (!$("#categoryName").value) $("#categoryName").value = state.category_name;
  $("#caseCount").textContent = state.case_count;
  $("#revision").textContent = `v${state.revision}`;
  $("#updatedAt").textContent = state.updated_at;
  const terms = Object.entries(state.positive_terms).slice(0, 40);
  $("#terms").innerHTML = terms.length
    ? terms.map(([term, weight]) => `<span class="tag">${e(term)} <b>${weight}</b></span>`).join("")
    : '<div class="empty">等待你导入第一批正面案例后开始学习。</div>';
  const fields = Object.entries(state.source_fields).slice(0, 20);
  $("#fields").innerHTML = fields.length
    ? fields.map(([field, count]) => `<span class="field">${e(field)} · ${count}</span>`).join("")
    : '<span class="muted">暂无结构字段</span>';
  const cases = state.case_summaries.slice(-12);
  $("#cases").innerHTML = cases.length
    ? cases.map((item) => `<li><b>案例 ${item.index}</b><span>${e(item.text)}</span></li>`).join("")
    : '<li class="empty">尚未导入案例</li>';
}

$("#jsonFile").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (file) $("#jsonPayload").value = await file.text();
});

$("#feed").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  try {
    const result = await api.post("/api/categories/new/cases", {
      category_name: $("#categoryName").value.trim(),
      cases: $("#jsonPayload").value,
    });
    render(result.state);
    $("#jsonPayload").value = "";
    showNotice($("#notice"), `已加入 ${result.added} 条新正面案例，并完成自动解析。`);
  } catch (error) {
    showNotice($("#notice"), error.message, false);
  } finally {
    button.disabled = false;
  }
});

api.get("/api/categories/new").then(render).catch((error) => showNotice($("#notice"), error.message, false));
