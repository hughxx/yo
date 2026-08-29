const $ = (id) => document.getElementById(id);
let selectedFolder = "";
let folders = [];
let messages = [];
let messagePage = 1;
const selectedMessageIds = new Set();
const MESSAGE_PAGE_SIZE = 30;
let testToken = 0;
let bridgeBootstrapped = false;
let resultItems = [];
let mailItems = [];
let mailPage = 1;
const selectedMailIds = new Set();
const MAIL_PAGE_SIZE = 20;
const selectedResource = () => document.querySelector('input[name="resource"]:checked')?.value || "public";

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
function hideTestPanel() { testToken++; }
async function loadMinerConfig() {
  const result = await call("get_miner_config");
  if (!result.ok) return toast(result.error || "配置读取失败");
  const resource = result.resource || "public";
  const radio = document.querySelector(`input[name="resource"][value="${resource}"]`);
  if (radio) radio.checked = true;
  $("prompt-editor").value = result.prompt || "";
}
async function saveMinerConfig(prompt) {
  const result = await call("save_miner_config", prompt, selectedResource());
  if (result.ok) toast("配置已保存"); else toast(result.error || "配置保存失败");
  return result;
}

async function loadFolders() {
  status(true);
  $("folder-select").innerHTML = '<option value="">正在读取文件夹…</option>';
  const result = await call("list_folders");
  status(false);
  if (!result.ok) { $("folder-select").innerHTML = '<option value="">文件夹读取失败</option>'; toast(result.error); return; }
  folders = result.items || [];
  const select = $("folder-select");
  select.innerHTML = folders.length ? folders.map((x) => `<option value="${esc(x)}">${esc(x)}</option>`).join("") : '<option value="">没有找到 Outlook 文件夹</option>';
  // Outlook folder names are localized; the default inbox may be Inbox or 收件箱.
  selectedFolder = folders.find((x) => /[\\/](Inbox|收件箱)$/i.test(x)) || folders[0] || "";
  if (selectedFolder) select.value = selectedFolder;
  if (selectedFolder) await loadMails();
}
async function loadMails() {
  status(true);
  $("mail-list").innerHTML = '<div class="loading">正在加载邮件列表…</div>';
  const result = await call("list_emails", selectedFolder ? [selectedFolder] : [], $("mail-search").value);
  status(false);
  if (!result.ok) { $("mail-list").innerHTML = ""; toast(result.error); return; }
  mailItems = result.items || [];
  selectedMailIds.clear();
  mailPage = 1;
  renderMailPage();
}
function renderMailPage() {
  const items = mailItems.slice((mailPage - 1) * MAIL_PAGE_SIZE, mailPage * MAIL_PAGE_SIZE);
  $("mail-list").innerHTML = items.length ? items.map((x) =>
    `<label class="mail"><input type="checkbox" data-mail="${esc(x.item_id)}" ${selectedMailIds.has(String(x.item_id)) ? "checked" : ""}><span><b>${esc(x.subject || "（无主题）")}</b><small>${esc(x.sender_name || x.sender_email || "")} · ${esc(x.received_time || "")}</small></span></label>`
  ).join("") : '<div class="empty">没有匹配的邮件</div>';
  const pages = Math.max(1, Math.ceil(mailItems.length / MAIL_PAGE_SIZE));
  $("mail-page-info").textContent = `${mailPage} / ${pages}`;
  $("mail-page-prev").disabled = mailPage <= 1;
  $("mail-page-next").disabled = mailPage >= pages;
  updateMailCount();
}
function updateMailCount() { $("mail-selected-count").textContent = `已选择 ${selectedMailIds.size} 封邮件`; }
async function loadMessages() {
  const id = $("group-id").value.trim();
  if (!id) { toast("请输入群组 ID"); return; }
  status(true);
  const loadButton = $("welink-load");
  loadButton.disabled = true;
  $("message-list").innerHTML = '<div class="loading loading-large"><span class="spinner"></span><b>正在加载聊天记录</b><small>正在分页读取历史消息，请稍候…</small></div>';
  const result = await call("fetch_welink", id, $("group-name").value, $("start-time").value, $("end-time").value);
  status(false);
  loadButton.disabled = false;
  if (!result.ok) { $("message-list").innerHTML = ""; toast(result.error); return; }
  messages = result.items || [];
  selectedMessageIds.clear();
  messages.forEach((x) => selectedMessageIds.add(String(x.id)));
  messagePage = 1;
  renderMessagePage();
}
function renderMessagePage() {
  const pageItems = messages.slice((messagePage - 1) * MESSAGE_PAGE_SIZE, messagePage * MESSAGE_PAGE_SIZE);
  $("message-list").innerHTML = pageItems.length ? pageItems.map((x) =>
    `<label class="message"><input type="checkbox" data-msg="${esc(x.id)}" ${selectedMessageIds.has(String(x.id)) ? "checked" : ""}><span class="content"><small>${esc(x.time || "")} · ${esc(x.sender || "")}</small><br>${esc(x.displayContent || x.content || "")}</span></label>`
  ).join("") : '<div class="empty">没有消息</div>';
  const pages = Math.max(1, Math.ceil(messages.length / MESSAGE_PAGE_SIZE));
  $("msg-count").textContent = `消息列表 · 已选择 ${selectedMessageIds.size} / 共 ${messages.length} 条`;
  $("msg-page-info").textContent = `${messagePage} / ${pages}`;
  $("msg-page-prev").disabled = messagePage <= 1;
  $("msg-page-next").disabled = messagePage >= pages;
}
async function loadResults() {
  const result = await call("list_results");
  if (!result.ok) { toast(result.error); return; }
  resultItems = result.items || [];
  $("result-list").innerHTML = resultItems.length ? resultItems.map((x, index) =>
    `<div class="result"><div class="result-head"><div><h3>${esc(x.title)}</h3><small>${x.kind === "outlook" ? "邮件" : "聊天记录"} · ${esc(x.updatedAt)}</small></div><span>${x.hasExperience ? "已提取经验" : "仅 Markdown"}</span></div><div class="result-actions"><button data-result-action="open-markdown" data-result-index="${index}">打开 Markdown</button>${x.hasExperience ? `<button data-result-action="open-experience" data-result-index="${index}">打开经验</button>` : `<button class="primary" data-result-action="extract" data-result-index="${index}">提取经验</button>`}</div></div>`
  ).join("") : '<div class="empty">还没有导出结果</div>';
}
async function openResultsDir() {
  const result = await call("open_results_dir");
  if (!result.ok) toast(result.error || "无法打开结果目录");
}
async function extractResult(path, button) {
  if (!path) return toast("没有找到 Markdown 文件");
  status(true);
  if (button) button.disabled = true;
  try {
    finish(await call("extract_experience_resource", path, selectedResource()));
    await loadResults();
  } finally {
    status(false);
    if (button) button.disabled = false;
  }
}
function openFile(path) { call("open_file", path).then((r) => { if (!r.ok) toast(r.error); }); }

document.addEventListener("DOMContentLoaded", () => {
  const pages = { outlook: ["邮件萃取", "选择邮件，导出 Markdown 或提取经验"], welink: ["聊天记录萃取", "选择群聊消息，导出 Markdown 或提取经验"], results: ["萃取结果", "查看已保存的 Markdown 和经验文件"], model: ["配置", "模型配置和提示词配置"] };
  document.querySelectorAll(".nav").forEach((button) => button.onclick = () => {
    document.querySelectorAll(".nav").forEach((x) => x.classList.remove("active"));
    button.classList.add("active");
    document.querySelectorAll(".page").forEach((x) => x.classList.add("hidden"));
    $(button.dataset.page).classList.remove("hidden");
    $("page-title").textContent = pages[button.dataset.page][0];
    $("page-desc").textContent = pages[button.dataset.page][1];
    if (button.dataset.page === "results") loadResults();
    if (button.dataset.page === "model") loadMinerConfig();
  });
  $("folders").onclick = loadFolders;
  $("folder-select").onchange = async () => { selectedFolder = $("folder-select").value; await loadMails(); };
  $("mails").onclick = loadMails;
  $("mail-search").onkeydown = (e) => { if (e.key === "Enter") loadMails(); };
  $("mail-list").onchange = (event) => { const box = event.target.closest("[data-mail]"); if (box) { const id = String(box.dataset.mail); box.checked ? selectedMailIds.add(id) : selectedMailIds.delete(id); updateMailCount(); } };
  $("mail-page-prev").onclick = () => { if (mailPage > 1) { mailPage--; renderMailPage(); } };
  $("mail-page-next").onclick = () => { if (mailPage < Math.ceil(mailItems.length / MAIL_PAGE_SIZE)) { mailPage++; renderMailPage(); } };
  $("mail-all").onclick = () => { mailItems.forEach((x) => selectedMailIds.add(String(x.item_id))); renderMailPage(); };
  $("mail-reverse").onclick = () => { mailItems.forEach((x) => { const id = String(x.item_id); selectedMailIds.has(id) ? selectedMailIds.delete(id) : selectedMailIds.add(id); }); renderMailPage(); };
  $("welink-load").onclick = loadMessages;
  $("message-list").onchange = (event) => { const box = event.target.closest("[data-msg]"); if (box) { const id = String(box.dataset.msg); box.checked ? selectedMessageIds.add(id) : selectedMessageIds.delete(id); renderMessagePage(); } };
  $("msg-page-prev").onclick = () => { if (messagePage > 1) { messagePage--; renderMessagePage(); } };
  $("msg-page-next").onclick = () => { if (messagePage < Math.ceil(messages.length / MESSAGE_PAGE_SIZE)) { messagePage++; renderMessagePage(); } };
  $("msg-all").onclick = () => { messages.forEach((x) => selectedMessageIds.add(String(x.id))); renderMessagePage(); };
  $("msg-reverse").onclick = () => { messages.forEach((x) => { const id = String(x.id); selectedMessageIds.has(id) ? selectedMessageIds.delete(id) : selectedMessageIds.add(id); }); renderMessagePage(); };
  $("mail-md").onclick = async () => { const ids = [...selectedMailIds]; if (!ids.length) return toast("请先选择邮件"); finish(await call("export_outlook", ids, selectedFolder ? [selectedFolder] : [])); };
  $("mail-ai").onclick = async () => { const ids = [...selectedMailIds]; if (!ids.length) return toast("请先选择邮件"); const r = await call("export_outlook", ids, selectedFolder ? [selectedFolder] : []); finish(r.ok ? await call("extract_experience_resource", r.path, selectedResource()) : r); };
  $("welink-md").onclick = async () => finish(await call("export_welink", $("group-id").value, $("group-name").value, $("start-time").value, $("end-time").value, [...selectedMessageIds]));
  $("welink-ai").onclick = async () => { const r = await call("export_welink", $("group-id").value, $("group-name").value, $("start-time").value, $("end-time").value, [...selectedMessageIds]); finish(r.ok ? await call("extract_experience_resource", r.path, selectedResource()) : r); };
  document.querySelectorAll(".config-tab").forEach((tab) => tab.onclick = () => {
    document.querySelectorAll(".config-tab").forEach((x) => x.classList.remove("active"));
    tab.classList.add("active");
    document.querySelectorAll(".config-tab-panel").forEach((x) => x.classList.add("hidden"));
    $(tab.dataset.tab).classList.remove("hidden");
  });
  document.querySelectorAll('input[name="resource"]').forEach((radio) => radio.onchange = () => saveMinerConfig($("prompt-editor").value));
  $("prompt-save").onclick = () => saveMinerConfig($("prompt-editor").value);
  $("prompt-reset").onclick = async () => {
    const result = await call("get_miner_config");
    if (result.ok) $("prompt-editor").value = result.default_prompt || result.prompt || "";
  };
  $("model-test").onclick = async () => {
    const button = $("model-test");
    const output = $("model-test-output");
    const token = ++testToken;
    button.disabled = true;
    output.className = "testing";
    output.textContent = "正在测试连接…";
    const r = await call("test_model", selectedResource(), $("model-test-input").value.trim() || "你好");
    if (token === testToken) {
      output.className = r.ok ? "success" : "failure";
      output.textContent = r.ok
        ? `连接成功\n\n模型返回：\n${r.output || "（模型未返回文本）"}`
        : `连接失败\n\n${r.error || "未知错误"}`;
      button.disabled = false;
    }
  };
  $("open-dir").onclick = openResultsDir;
  $("refresh-results").onclick = loadResults;
  $("result-list").onclick = (event) => {
    const button = event.target.closest("[data-result-action]");
    if (!button) return;
    const item = resultItems[Number(button.dataset.resultIndex)];
    if (!item) return;
    const action = button.dataset.resultAction;
    if (action === "open-markdown") openFile(item.markdown);
    else if (action === "open-experience") openFile(item.experience);
    else if (action === "extract") void extractResult(item.markdown, button);
  };
});
function bootstrapBridge() {
  if (bridgeBootstrapped) return;
  if (!window.pywebview || !window.pywebview.api) { setTimeout(bootstrapBridge, 500); return; }
  bridgeBootstrapped = true;
  loadFolders(); loadResults(); loadMinerConfig();
}
window.addEventListener("pywebviewready", bootstrapBridge);
setTimeout(bootstrapBridge, 100);
