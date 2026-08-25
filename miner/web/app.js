const $ = (id) => document.getElementById(id);
let selectedFolder = "";
let folders = [];
let messages = [];
let testToken = 0;
let bridgeBootstrapped = false;

async function call(name, ...args) {
  if (!window.pywebview || !window.pywebview.api || !window.pywebview.api[name]) {
    return { ok: false, error: "本地服务尚未就绪，请稍候再试" };
  }
  try { return await window.pywebview.api[name](...args); }
  catch (e) { return { ok: false, error: e && e.message ? e.message : String(e) }; }
}
function toast(message) {
  const el = $("toast");
  if (!el) return;
  el.textContent = message || "操作失败";
  el.style.display = "block";
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => { el.style.display = "none"; }, 3500);
}
function status(on) { $("status").textContent = on ? "处理中..." : ""; }
function esc(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}
function checked(selector, key) {
  return [...document.querySelectorAll(selector)].filter((x) => x.checked).map((x) => x.dataset[key]);
}
function finish(result) {
  status(false);
  if (result && result.ok) toast("处理完成");
  else if (result) toast(result.error || "处理失败");
  return result;
}
function hideTestPanel() { testToken++; $("model-test-panel").classList.add("hidden"); $("model-test-send").disabled = false; }

async function loadFolders() {
  status(true);
  const result = await call("list_folders");
  status(false);
  if (!result.ok) { $("folder-tree").innerHTML = ""; toast(result.error); return; }
  folders = result.items || [];
  $("folder-tree").innerHTML = folders.length
    ? folders.map((x) => `<div class="folder" data-path="${esc(x)}">${esc(x)}</div>`).join("")
    : '<div class="empty">没有找到 Outlook 文件夹</div>';
  document.querySelectorAll(".folder").forEach((el) => el.onclick = () => {
    document.querySelectorAll(".folder").forEach((x) => x.classList.remove("selected"));
    el.classList.add("selected"); selectedFolder = el.dataset.path;
  });
  const inbox = [...document.querySelectorAll(".folder")].find((el) => /\\Inbox$/i.test(el.dataset.path));
  if (inbox) { inbox.classList.add("selected"); selectedFolder = inbox.dataset.path; await loadMails(); }
}
async function loadMails() {
  status(true);
  const result = await call("list_emails", selectedFolder ? [selectedFolder] : [], $("mail-search").value);
  status(false);
  if (!result.ok) { $("mail-list").innerHTML = ""; toast(result.error); return; }
  const items = result.items || [];
  $("mail-list").innerHTML = items.length ? items.map((x) =>
    `<label class="mail"><input type="checkbox" data-mail="${esc(x.item_id)}"><span><b>${esc(x.subject || "（无主题）")}</b><small>${esc(x.sender_name || x.sender_email || "")} · ${esc(x.received_time || "")}</small></span></label>`
  ).join("") : '<div class="empty">没有匹配的邮件</div>';
}
async function loadMessages() {
  const id = $("group-id").value.trim();
  if (!id) { toast("请输入群组 ID"); return; }
  status(true);
  const result = await call("fetch_welink", id, $("group-name").value, $("start-time").value, $("end-time").value);
  status(false);
  if (!result.ok) { $("message-list").innerHTML = ""; toast(result.error); return; }
  messages = result.items || [];
  $("message-list").innerHTML = messages.length ? messages.map((x) =>
    `<label class="message"><input type="checkbox" data-msg="${esc(x.id)}" checked><span class="content"><small>${esc(x.time || "")} · ${esc(x.sender || "")}</small><br>${esc(x.displayContent || x.content || "")}</span></label>`
  ).join("") : '<div class="empty">没有消息</div>';
  $("msg-count").textContent = `共 ${messages.length} 条`;
}
async function loadResults() {
  const result = await call("list_results");
  if (!result.ok) { toast(result.error); return; }
  const items = result.items || [];
  $("result-list").innerHTML = items.length ? items.map((x) =>
    `<div class="result"><div class="result-head"><div><h3>${esc(x.title)}</h3><small>${x.kind === "outlook" ? "邮件" : "聊天记录"} · ${esc(x.updatedAt)}</small></div><span>${x.hasExperience ? "已提取经验" : "仅 Markdown"}</span></div><div class="result-actions"><button onclick="openFile('${esc(x.markdown)}')">打开 Markdown</button>${x.hasExperience ? `<button onclick="openFile('${esc(x.experience)}')">打开经验</button>` : `<button class="primary" onclick="extractResult('${esc(x.markdown)}')">提取经验</button>`}</div></div>`
  ).join("") : '<div class="empty">还没有导出结果</div>';
}
async function openResultsDir() {
  const result = await call("open_results_dir");
  if (!result.ok) toast(result.error || "无法打开结果目录");
}
async function extractResult(path) { finish(await call("extract_experience_resource", path, $("resource-mail").value)); await loadResults(); }
function openFile(path) { call("open_file", path).then((r) => { if (!r.ok) toast(r.error); }); }
window.openFile = openFile;
window.extractResult = extractResult;

document.addEventListener("DOMContentLoaded", () => {
  const pages = { outlook: ["邮件萃取", "选择邮件，导出 Markdown 或提取经验"], welink: ["聊天记录萃取", "选择群聊消息，导出 Markdown 或提取经验"], results: ["萃取结果", "查看已保存的 Markdown 和经验文件"], model: ["模型资源管理", "选择公共资源或个人资源，测试模型是否可用"] };
  document.querySelectorAll(".nav").forEach((button) => button.onclick = () => {
    document.querySelectorAll(".nav").forEach((x) => x.classList.remove("active"));
    button.classList.add("active");
    document.querySelectorAll(".page").forEach((x) => x.classList.add("hidden"));
    $(button.dataset.page).classList.remove("hidden");
    $("page-title").textContent = pages[button.dataset.page][0];
    $("page-desc").textContent = pages[button.dataset.page][1];
    if (button.dataset.page !== "model") hideTestPanel();
    if (button.dataset.page === "results") loadResults();
  });
  $("folders").onclick = loadFolders;
  $("mails").onclick = loadMails;
  $("mail-search").onkeydown = (e) => { if (e.key === "Enter") loadMails(); };
  $("welink-load").onclick = loadMessages;
  $("msg-all").onclick = () => document.querySelectorAll("[data-msg]").forEach((x) => x.checked = true);
  $("msg-reverse").onclick = () => document.querySelectorAll("[data-msg]").forEach((x) => x.checked = !x.checked);
  $("mail-md").onclick = async () => { const ids = checked("[data-mail]", "mail"); if (!ids.length) return toast("请先选择邮件"); finish(await call("export_outlook", ids, selectedFolder ? [selectedFolder] : [])); };
  $("mail-ai").onclick = async () => { const ids = checked("[data-mail]", "mail"); if (!ids.length) return toast("请先选择邮件"); const r = await call("export_outlook", ids, selectedFolder ? [selectedFolder] : []); finish(r.ok ? await call("extract_experience_resource", r.path, $("resource-mail").value) : r); };
  $("welink-md").onclick = async () => finish(await call("export_welink", $("group-id").value, $("group-name").value, $("start-time").value, $("end-time").value, checked("[data-msg]", "msg")));
  $("welink-ai").onclick = async () => { const r = await call("export_welink", $("group-id").value, $("group-name").value, $("start-time").value, $("end-time").value, checked("[data-msg]", "msg")); finish(r.ok ? await call("extract_experience_resource", r.path, $("resource-mail").value) : r); };
  $("model-test").onclick = () => { $("model-test-panel").classList.remove("hidden"); $("model-test-input").focus(); };
  $("model-panel-close").onclick = hideTestPanel;
  $("model-test-cancel").onclick = async () => { testToken++; const r = await call("cancel_model_test"); $("model-test-send").disabled = false; $("model-test-output").textContent = r.ok ? "已取消测试" : "已停止等待，可关闭此面板"; };
  $("model-test-send").onclick = async () => { const text = $("model-test-input").value.trim(); if (!text) return toast("请输入测试内容"); const token = ++testToken; $("model-test-send").disabled = true; $("model-test-output").textContent = "测试中..."; const r = await call("test_model", $("resource-mail").value, text); if (token === testToken) { $("model-test-output").textContent = r.ok ? (r.output || "模型已返回空结果") : (r.error || "测试失败"); $("model-test-send").disabled = false; } };
  $("open-dir").onclick = openResultsDir;
  $("refresh-results").onclick = loadResults;
});
function bootstrapBridge() {
  if (bridgeBootstrapped) return;
  if (!window.pywebview || !window.pywebview.api) { setTimeout(bootstrapBridge, 500); return; }
  bridgeBootstrapped = true;
  loadFolders(); loadResults();
}
window.addEventListener("pywebviewready", bootstrapBridge);
setTimeout(bootstrapBridge, 100);
