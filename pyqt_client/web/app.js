const state={settings:{},emails:[],selected:new Set(),filter:'all',search:'',page:1,pageSize:50,rules:[],blacklist:[],ruleKind:'rules',welinkRules:[],emailTimer:null,monitorCursor:0,monitorPoll:null};
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const esc=v=>String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));

function toast(message,error=false){const el=$('#toast');el.textContent=message;el.className=`toast${error?' error':''}`;setTimeout(()=>el.classList.add('hidden'),3200)}
function busy(on,text='处理中…'){ $('#progress').classList.toggle('hidden',!on); if(text) log(text); $$('button').forEach(b=>{if(b.dataset.close===undefined&&on)b.dataset.wasDisabled=b.disabled?'1':'0'}); }
function log(text){$('#email-log').textContent=`[${new Date().toLocaleTimeString()}] ${text}`}
async function call(name,...args){
  try{const fn=window.pywebview?.api?.[name];if(!fn)throw new Error('JS Bridge 尚未就绪');const result=await fn(...args);if(!result?.ok)throw new Error(result?.error||'未知错误');return result}
  catch(e){toast(e.message||String(e),true);throw e}
}

function showPage(name){$$('.page').forEach(x=>x.classList.toggle('active',x.id===`page-${name}`));$$('.nav[data-page]').forEach(x=>x.classList.toggle('active',x.dataset.page===name))}
function openModal(id){$(`#${id}`).classList.remove('hidden')}
function closeModal(id){$(`#${id}`).classList.add('hidden')}

function filteredEmails(){
  const q=state.search.trim().toLowerCase();
  return state.emails.filter(x=>(state.filter==='all'||x.matched_rule)&&(!q||`${x.subject} ${x.sender_name} ${x.sender_email} ${x.conversation_topic}`.toLowerCase().includes(q)));
}
function renderEmails(){
  const filtered=filteredEmails(),pages=Math.max(1,Math.ceil(filtered.length/state.pageSize));state.page=Math.min(state.page,pages);
  const rows=filtered.slice((state.page-1)*state.pageSize,state.page*state.pageSize);
  $('#email-body').innerHTML=rows.length?rows.map(x=>`<tr title="${esc(x.subject)}"><td><input class="email-check" type="checkbox" data-id="${esc(x.item_id)}" ${state.selected.has(x.item_id)?'checked':''}></td><td><span class="badge ${x.matched_rule?'':'none'}">${esc(x.matched_rule||x.parseStatus||'-')}</span></td><td>${esc((x.received_time||'').replace('T',' '))}</td><td title="${esc(x.sender_email)}">${esc(x.sender_name||x.sender_email)}</td><td>${esc(x.subject)}</td><td>${esc(x.conversation_topic)}</td></tr>`).join(''):`<tr><td colspan="6" class="empty">没有符合条件的邮件</td></tr>`;
  $('#all-count').textContent=state.emails.length;$('#matched-count').textContent=state.emails.filter(x=>x.matched_rule).length;
  $('#page-info').textContent=`第 ${state.page} / ${pages} 页`;$('#total-info').textContent=`共 ${filtered.length} 封`;
  $('#prev-page').disabled=state.page<=1;$('#next-page').disabled=state.page>=pages;
  $('#process-selected').disabled=!state.selected.size;$('#process-selected').textContent=`处理选中 (${state.selected.size})`;
  $('#check-all').checked=rows.length>0&&rows.every(x=>state.selected.has(x.item_id));
  $$('.email-check').forEach(box=>box.onchange=()=>{box.checked?state.selected.add(box.dataset.id):state.selected.delete(box.dataset.id);renderEmails()});
}

async function refreshEmails(){
  busy(true,'正在读取 Outlook 并计算规则匹配…');$('#refresh-emails').disabled=true;
  try{const r=await call('list_emails');state.emails=r.items;state.selected.clear();state.page=1;renderEmails();log(`读取 ${r.items.length} 封邮件${r.errors.length?'；'+r.errors.join('；'):''}`);await refreshStatus()}
  finally{busy(false);$('#refresh-emails').disabled=false}
}
async function refreshStatus(){
  if((state.settings.backendUrl||'').toLowerCase()==='offline')return;
  const topics=[...new Set(state.emails.map(x=>x.conversation_topic).filter(Boolean))].slice(0,500);
  if(!topics.length)return;
  try{const r=await call('parse_status',topics),map=r.items||{};state.emails.forEach(x=>{const raw=map[x.conversation_topic];if(raw)x.parseStatus={done:'已解析',failed:'失败',pending:'解析中'}[raw]||raw});renderEmails()}catch(_){/* status is optional */}
}
async function processSelected(){
  if(!confirm(`将选中的 ${state.selected.size} 封邮件推送处理，确定继续？`))return;
  busy(true,`正在处理 ${state.selected.size} 封邮件…`);$('#process-selected').disabled=true;
  try{const r=await call('process_emails',[...state.selected],true);toast(`完成：成功 ${r.success}，失败 ${r.failed}`,!!r.failed);log(`处理完成：成功 ${r.success}，失败 ${r.failed}`);await refreshEmails()}
  finally{busy(false)}
}
function toggleEmailTimer(){
  const button=$('#toggle-email-timer');
  if(state.emailTimer){clearInterval(state.emailTimer);state.emailTimer=null;button.textContent='启动定时';button.classList.remove('danger');log('定时同步已停止');return}
  const minutes=Math.max(1,Number(state.settings.scanIntervalMinutes||60));
  state.emailTimer=setInterval(async()=>{await refreshEmails();const matched=state.emails.filter(x=>x.matched_rule).map(x=>x.item_id);if(matched.length){try{await call('process_emails',matched,false);log(`定时同步完成：${matched.length} 封`)}catch(_){}}},minutes*60*1000);
  button.textContent='停止定时';button.classList.add('danger');log(`定时同步已启动：每 ${minutes} 分钟`)
}

async function refreshFolders(){
  $('#folder-list').innerHTML='<div class="empty small">正在读取 Outlook…</div>';
  try{const r=await call('list_folders'),selected=new Set(state.settings.scanFolders||[]);$('#folder-list').innerHTML=r.items.map(path=>`<label class="folder"><input type="checkbox" value="${esc(path)}" ${selected.has(path)?'checked':''}><span>${esc(path)}</span></label>`).join('')||'<div class="empty small">未发现文件夹</div>';$$('#folder-list input').forEach(x=>x.onchange=saveFolderSelection)}catch(e){$('#folder-list').innerHTML=`<div class="empty small">${esc(e.message)}</div>`}
}
async function saveFolderSelection(){state.settings.scanFolders=$$('#folder-list input:checked').map(x=>x.value);try{const r=await call('save_settings',state.settings);state.settings=r.settings;log('扫描文件夹已更新')}catch(_){}}

function fillSettings(){
  $('#set-backend').value=state.settings.backendUrl||'';$('#set-user').value=state.settings.userId||'';$('#set-interval').value=state.settings.scanIntervalMinutes||60;$('#set-welink-user').value=state.settings.welinkUserId||'';$('#set-output').value=state.settings.outputDir||'';$('#set-json').value=state.settings.customJsonConfig||'{}';
  const ns=$('#set-namespace'),value=state.settings.namespace||'';ns.innerHTML=`<option value="${esc(value)}">${esc(value||'请选择')}</option>`;
}
function readSettings(){return {...state.settings,backendUrl:$('#set-backend').value.trim(),userId:$('#set-user').value.trim(),namespace:$('#set-namespace').value,scanIntervalMinutes:Number($('#set-interval').value||60),welinkUserId:$('#set-welink-user').value.trim(),outputDir:$('#set-output').value.trim(),customJsonConfig:$('#set-json').value.trim()||'{}'}}
async function loadNamespaces(){const r=await call('get_namespaces',$('#set-backend').value.trim()),current=state.settings.namespace||'';$('#set-namespace').innerHTML='<option value="">请选择</option>'+r.items.map(x=>{const value=typeof x==='string'?x:(x.value||x.name||x.namespace||'');return `<option value="${esc(value)}" ${value===current?'selected':''}>${esc(value)}</option>`}).join('')}
async function saveSettings(){try{JSON.parse($('#set-json').value||'{}')}catch(_){toast('自定义 JSON 格式不正确',true);return}const r=await call('save_settings',readSettings());state.settings=r.settings;closeModal('settings-modal');toast('设置已保存')}

function ruleData(){return state[state.ruleKind]}
function renderRules(){
  $('#email-rules').innerHTML=ruleData().map((r,i)=>`<div class="email-rule" data-index="${i}"><input data-key="name" value="${esc(r.name)}" placeholder="规则名称"><input data-key="keywords" value="${esc((r.keywords||[]).join(', '))}" placeholder="主题关键词"><input data-key="body_keywords" value="${esc((r.body_keywords||[]).join(', '))}" placeholder="正文关键词"><input data-key="senders" value="${esc((r.senders||[]).join(', '))}" placeholder="发件人"><select data-key="logic"><option ${r.logic!=='AND'?'selected':''}>OR</option><option ${r.logic==='AND'?'selected':''}>AND</option></select><button class="remove danger" data-remove-rule="${i}">×</button></div>`).join('')||'<div class="empty small">暂无规则</div>';
  $$('[data-remove-rule]').forEach(b=>b.onclick=()=>{ruleData().splice(Number(b.dataset.removeRule),1);renderRules()});
}
function collectRules(){$$('.email-rule').forEach(row=>{const r=ruleData()[Number(row.dataset.index)];row.querySelectorAll('[data-key]').forEach(el=>{const k=el.dataset.key;r[k]=['keywords','body_keywords','senders'].includes(k)?el.value.split(/[,，\n]/).map(x=>x.trim()).filter(Boolean):el.value})})}
async function saveRules(){collectRules();const r=await call('save_rules',state.ruleKind,ruleData());state[state.ruleKind]=r.items;closeModal('rules-modal');toast('规则已保存')}

function renderWelinkRules(){
  $('#welink-rules').innerHTML=state.welinkRules.map((r,i)=>`<div class="rule-row"><input data-wl="id" data-index="${i}" value="${esc(r.group_id)}" placeholder="群组 ID"><input data-wl="name" data-index="${i}" value="${esc(r.group_name)}" placeholder="群组名称"><button class="danger" data-wl-remove="${i}">删除</button></div>`).join('')||'<div class="empty small">暂无监听群组</div>';
  $$('[data-wl]').forEach(x=>x.onchange=saveWelinkRules);$$('[data-wl-remove]').forEach(x=>x.onclick=()=>{state.welinkRules.splice(Number(x.dataset.wlRemove),1);saveWelinkRules()})
}
async function saveWelinkRules(){
  $$('[data-wl]').forEach(x=>{const r=state.welinkRules[Number(x.dataset.index)];r[x.dataset.wl==='id'?'group_id':'group_name']=x.value.trim()});
  const r=await call('save_welink_rules',state.welinkRules);state.welinkRules=r.items;renderWelinkRules();toast('群组规则已保存')
}
async function toggleMonitor(){
  const running=$('#toggle-monitor').dataset.running==='1';
  const r=await call('toggle_welink_monitor',!running);setMonitorState(r.running)
}
function setMonitorState(running){const b=$('#toggle-monitor');b.dataset.running=running?'1':'0';b.textContent=running?'停止监听':'开始监听';b.classList.toggle('danger',running);b.classList.toggle('primary',!running);$('#monitor-status').textContent=running?'监听中':'未运行'}
async function pollMonitor(){try{const r=await call('welink_monitor_status',state.monitorCursor);state.monitorCursor=r.cursor;setMonitorState(r.running);if(r.events.length){const el=$('#monitor-log');el.textContent=(el.textContent==='监听日志…'?'':el.textContent+'\n')+r.events.join('\n');el.scrollTop=el.scrollHeight}}catch(_){}}

function bind(){
  $$('.nav[data-page]').forEach(x=>x.onclick=()=>showPage(x.dataset.page));$$('[data-close]').forEach(x=>x.onclick=()=>closeModal(x.dataset.close));
  $('#open-settings').onclick=()=>{fillSettings();openModal('settings-modal')};$('#save-settings').onclick=saveSettings;
  $('#test-server').onclick=async()=>{const s=$('#settings-status');s.textContent='测试中…';try{const r=await call('test_server',$('#set-backend').value.trim());s.textContent=r.reachable?'连接成功':'连接失败';if(r.reachable)await loadNamespaces()}catch(e){s.textContent=e.message}};
  $('#choose-output').onclick=async()=>{const r=await call('choose_output_dir');if(r.path)$('#set-output').value=r.path};
  $('#refresh-emails').onclick=refreshEmails;$('#process-selected').onclick=processSelected;$('#refresh-folders').onclick=refreshFolders;$('#toggle-email-timer').onclick=toggleEmailTimer;
  $('#email-search').oninput=e=>{state.search=e.target.value;state.page=1;renderEmails()};$$('.segment').forEach(x=>x.onclick=()=>{$$('.segment').forEach(y=>y.classList.toggle('active',y===x));state.filter=x.dataset.filter;state.page=1;renderEmails()});
  $('#check-all').onchange=e=>{const filtered=filteredEmails().slice((state.page-1)*state.pageSize,state.page*state.pageSize);filtered.forEach(x=>e.target.checked?state.selected.add(x.item_id):state.selected.delete(x.item_id));renderEmails()};
  $('#prev-page').onclick=()=>{state.page--;renderEmails()};$('#next-page').onclick=()=>{state.page++;renderEmails()};
  $('#open-rules').onclick=()=>{state.ruleKind='rules';$$('[data-rule-kind]').forEach(x=>x.classList.toggle('active',x.dataset.ruleKind==='rules'));renderRules();openModal('rules-modal')};
  $$('[data-rule-kind]').forEach(x=>x.onclick=()=>{collectRules();state.ruleKind=x.dataset.ruleKind;$$('[data-rule-kind]').forEach(y=>y.classList.toggle('active',y===x));renderRules()});
  $('#add-email-rule').onclick=()=>{collectRules();ruleData().push({id:'',name:'',keywords:[],body_keywords:[],senders:[],logic:'OR',enabled:true});renderRules()};$('#save-rules').onclick=saveRules;
  $('#add-welink-rule').onclick=()=>{state.welinkRules.push({id:'',group_id:'',group_name:''});renderWelinkRules()};
  $('#toggle-monitor').onclick=toggleMonitor;
  $('#choose-zip').onclick=async()=>{const r=await call('choose_zip');if(r.path)$('#zip-path').value=r.path};
  $('#import-welink').onclick=async()=>{const path=$('#zip-path').value;if(!path)return toast('请先选择 ZIP 文件',true);const out=$('#welink-log');out.textContent='正在解析并上传…';try{const r=await call('import_welink',path,$('#group-name').value);out.textContent=`导入完成\n消息：${r.count} 条\n模式：${r.offline?'本地离线':'服务端'}\n${r.duplicate?'服务端已存在，已跳过':''}\n${r.summary||''}`}catch(e){out.textContent=`导入失败：${e.message}`}};
}

async function init(){
  bind();const r=await call('bootstrap');state.settings=r.settings;state.rules=r.rules;state.blacklist=r.blacklist;state.welinkRules=r.welinkRules;$('#version').textContent=`v${r.version}`;renderEmails();renderWelinkRules();$('#app').classList.remove('loading');state.monitorPoll=setInterval(pollMonitor,1500);pollMonitor();
  if(!state.settings.backendUrl||!state.settings.userId||!state.settings.namespace){fillSettings();openModal('settings-modal')}
}
window.addEventListener('pywebviewready',()=>init().catch(e=>toast(e.message,true)));
