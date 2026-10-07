import { api, escapeHtml as e, showNotice } from "./api.js";

const $ = (selector) => document.querySelector(selector);

function list(items, emptyText) {
  return items.length ? items.map((text) => `<li>${e(text)}</li>`).join("") : `<li>${emptyText}</li>`;
}

function render(data) {
  const positive = Object.keys(data.positive_terms).length;
  const negative = Object.keys(data.negative_terms).length;
  $("#updatedAt").textContent = data.updated_at;
  $("#referenceCount").textContent = `${data.reference_case_count}/26`;
  $("#absorbed").textContent = data.positive_feedback.length + data.negative_feedback.length;
  $("#absorbedDetail").textContent = `${data.positive_feedback.length} 条正向 · ${data.negative_feedback.length} 条反向原文完整保留`;
  $("#ruleCount").textContent = positive + negative;
  $("#ruleDetail").textContent = `${positive} 条加分 · ${negative} 条扣分`;
  $("#revision").textContent = `v${data.revision}`;
  const v = data.visual;
  $("#visualSummary").innerHTML = `<b>${v.profile_count}</b> 份负面视觉档案 · <b>${v.video_count}</b> 条模板视频 · `
    + `<b>${v.scoring_count}</b> 条理由会影响视频内容扣分`;
  $("#visualLabels").innerHTML = v.top_labels.length
    ? v.top_labels.map((label) => `<span class="tag">${e(label)}</span>`).join("")
    : "尚未完成视频内容分析";
  $("#positiveText").value = data.positive_terms_text;
  $("#negativeText").value = data.negative_terms_text;
  $("#positiveFeedback").innerHTML = list(data.positive_feedback, "暂无有效正向描述");
  $("#negativeFeedback").innerHTML = list(data.negative_feedback, "暂无反向原因");
  $("#history").innerHTML = data.edit_history.length
    ? data.edit_history.map((item) => `<li><time>${e(item.at)}</time>${e(item.summary)}</li>`).join("")
    : "<li>尚无手动修改记录</li>";
}

$("#termsForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.submitter;
  button.disabled = true;
  try {
    const data = await api.put("/api/aesthetic/terms", {
      positive_text: $("#positiveText").value,
      negative_text: $("#negativeText").value,
    });
    render(data);
    showNotice($("#notice"), "已保存，所有候选人匹配度已重新计算。");
  } catch (error) {
    showNotice($("#notice"), error.message, false);
  } finally {
    button.disabled = false;
  }
});

api.get("/api/aesthetic").then(render).catch((error) => showNotice($("#notice"), error.message, false));
