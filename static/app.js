'use strict';
const EXPECTED_API_VERSION=3;
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const state = {token:'', projects:[], project:null, files:[], file:null, revision:null, dirty:false, loading:false, saving:null, compiling:false, syncing:false, switching:false, build:null, gitStatus:null, environment:{}, editVersion:0, pdfViewer:null, sourceHighlight:null};
let saveTimer, autoTimer, toastTimer;
const themeOrder=['light','dark','sepia','ocean'];
const themeNames={zh:{light:'浅色',dark:'深色',sepia:'暖纸',ocean:'海蓝'},en:{light:'Light',dark:'Dark',sepia:'Sepia',ocean:'Ocean'}};
const translations={
  zh:{localOffline:'本地 · 离线可用',exportProject:'导出项目',projectFiles:'项目文件',documentOutline:'文档大纲',history:'历史版本',userGuide:'使用指南',localOnly:'文件仅保存在这台电脑',source:'源码',find:'查找',pdfPreview:'PDF 预览',doubleClickSource:'双击正文跳转源码',fitWidth:'适合宽度',openPdf:'打开 PDF',compileAgain:'重新编译',autoCompile:'自动编译',makeIdeaPaper:'让想法成为论文',emptyHint:'在左侧编辑 LaTeX，点击「重新编译」即可在这里查看 PDF。',compileFirst:'编译第一份论文'},
  en:{localOffline:'Local · Offline',exportProject:'Export project',projectFiles:'Project files',documentOutline:'Document outline',history:'History',userGuide:'User guide',localOnly:'Files stay on this Mac',source:'Source',find:'Find',pdfPreview:'PDF preview',doubleClickSource:'Double-click text to jump to source',fitWidth:'Fit width',openPdf:'Open PDF',compileAgain:'Compile again',autoCompile:'Auto compile',makeIdeaPaper:'Turn ideas into papers',emptyHint:'Edit LaTeX on the left, then click “Compile again” to preview the PDF here.',compileFirst:'Compile your first paper'}
};
function applyLanguage(language){
  state.language=language==='en'?'en':'zh';
  const dict=translations[state.language];
  document.documentElement.lang=state.language==='en'?'en':'zh-CN';
  document.querySelectorAll('[data-i18n]').forEach(el=>{if(dict[el.dataset.i18n])el.textContent=dict[el.dataset.i18n];});
  $('language-toggle').textContent=state.language==='en'?'中文':'EN';
  $('language-toggle').title=state.language==='en'?'Switch to Chinese':'切换为英文';
  $('language-toggle').setAttribute('aria-label',$('language-toggle').title);
  $('theme-toggle').title=(state.language==='en'?'Color theme: ':'配色：')+themeNames[state.language][state.theme]+' · '+(state.language==='en'?'click to change':'点击切换');
  $('theme-toggle').setAttribute('aria-label',$('theme-toggle').title);
  if($('compile-label')&&!state.compiling)$('compile-label').textContent=dict.compileAgain;
  if($('git-sync-label')&&!state.syncing)$('git-sync-label').textContent=state.gitStatus?.configured?(state.language==='en'?'Sync Overleaf':'同步 Overleaf'):(state.language==='en'?'Connect Overleaf':'连接 Overleaf');
  if(state.project)renderFiles();
  if(state.gitStatus?.configured)updateGitButton(state.gitStatus);
  document.title=(state.project?.name||'LocalLeaf')+' · '+(state.language==='en'?'Offline paper workspace':'离线论文工作台');
  localStorage.setItem('localleaf-language',state.language);
}
function applyTheme(theme){
  state.theme=themeOrder.includes(theme)?theme:'light';
  document.documentElement.dataset.theme=state.theme;
  $('theme-toggle').textContent={light:'☾',dark:'☼',sepia:'◐',ocean:'◈'}[state.theme];
  if(state.language)applyLanguage(state.language); else localStorage.setItem('localleaf-theme',state.theme);
  localStorage.setItem('localleaf-theme',state.theme);
}
state.language=localStorage.getItem('localleaf-language')||'en';
state.theme=localStorage.getItem('localleaf-theme')||'light';
applyTheme(state.theme);applyLanguage(state.language);
const editor = CodeMirror.fromTextArea($('source'), {
  mode:'stex', lineNumbers:true, lineWrapping:true, indentUnit:2, tabSize:2,
  extraKeys:{'Cmd-S':()=>guard(save), 'Ctrl-S':()=>guard(save), 'Cmd-Enter':()=>compile(), 'Ctrl-Enter':()=>compile(),
    'Cmd-F':()=>toggleSearch(true), 'Ctrl-F':()=>toggleSearch(true), 'Tab':cm=>cm.replaceSelection('  '),
    'Cmd-/':()=>toggleComment(), 'Ctrl-/':()=>toggleComment()}
});
editor.setOption('readOnly', true);
const rememberedSize = Number(localStorage.getItem('localleaf-font')) || 13;
editor.getWrapperElement().style.fontSize = rememberedSize + 'px';

async function api(path, body) {
  const response = await fetch('/api/' + path, body === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json','X-LocalLeaf-Token':state.token}, body:JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '操作失败');
  return result;
}
function query(extra={}) { return new URLSearchParams({id:state.project.id,...extra}).toString(); }
function toast(message, error=false) {
  $('toast').textContent=message; $('toast').className='toast'+(error?' error':''); $('toast').hidden=false;
  clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('toast').hidden=true,error?10000:3500);
}
function savedLabel(text, error=false) { $('save-status').textContent=text; $('save-status').classList.toggle('error',error); $('dirty-dot').hidden=!state.dirty; }
function draftKey(pid=state.project?.id, file=state.file) { return 'localleaf-draft:'+pid+':'+file; }
function keepDraft() {
  if (!state.file || !state.dirty) return;
  try {localStorage.setItem(draftKey(), JSON.stringify({content:editor.getValue(), time:Date.now()}));} catch (_) {savedLabel('本地草稿缓存已满，请立即保存',true);}
}
async function save() {
  clearTimeout(saveTimer);
  if (state.saving) { await state.saving; if (state.dirty) return save(); return; }
  if (!state.dirty || !state.file || state.loading) return;
  const pid=state.project.id, file=state.file, content=editor.getValue(), version=state.editVersion;
  savedLabel('正在保存…');
  state.saving=(async()=>{
    const result=await api('save',{id:pid,path:file,content,revision:state.revision});
    if(state.project.id===pid && state.file===file) {
      state.revision=result.revision;
      if(state.editVersion===version) {state.dirty=false;localStorage.removeItem(draftKey(pid,file)); savedLabel('✓ 所有更改已保存');}
      else savedLabel('正在编辑…');
    }
  })();
  try {await state.saving;} catch(e) {savedLabel('保存失败 · 内容已保留',true);keepDraft();throw e;} finally {state.saving=null;}
  if(state.dirty) return save();
}
editor.on('change',()=>{
  if(state.loading || !state.file) return;
  state.dirty=true;state.editVersion++;savedLabel('正在编辑…');keepDraft();updateOutline();updateCursor();
  clearTimeout(saveTimer);saveTimer=setTimeout(()=>save().catch(e=>toast(e.message,true)),650);
  clearTimeout(autoTimer);if($('auto-compile').checked) autoTimer=setTimeout(()=>compile(),2200);
});
editor.on('cursorActivity',updateCursor);
function updateCursor(){const c=editor.getCursor();$('cursor-position').textContent=`行 ${c.line+1}，列 ${c.ch+1}`;$('word-count').textContent=editor.getValue().length.toLocaleString()+' 字符';}
function updateOutline(){
  const list=[];
  editor.getValue().split('\n').forEach((line,i)=>{
    const m=line.match(/^\s*\\(subsubsection|subsection|section|chapter|title)\*?(?:\[[^\]]*\])?\{([^}]+)\}/);
    if(m) list.push({line:i, title:m[2], depth:m[1]==='subsection'?1:m[1]==='subsubsection'?2:0});
  });
  $('outline').innerHTML=list.length?list.map(x=>`<button data-line="${x.line}" style="padding-left:${12+x.depth*12}px">${esc(x.title)}</button>`).join(''):'<div class="outline-empty">当前文件中的章节会显示在这里。</div>';
  $('outline').querySelectorAll('button').forEach(b=>b.onclick=()=>{editor.setCursor(Number(b.dataset.line),0);editor.focus();});
}
function formatFileTime(timestamp){
  if(!timestamp)return '';
  return new Date(timestamp*1000).toLocaleString(state.language==='en'?'en-US':'zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'});
}
function renderFiles(){
  let folder='';
  $('file-tree').innerHTML=state.files.map(f=>{
    const parts=f.path.split('/'), parent=parts.slice(0,-1).join('/');
    let html='';if(parent && parent!==folder) html=`<div class="folder">▾ &nbsp;${esc(parent)}</div>`;folder=parent;
    const ext=f.path.split('.').pop().toLowerCase(), icon=ext==='tex'?'TᴇX':ext==='bib'?'[1]':['png','jpg','jpeg','pdf','svg'].includes(ext)?'▧':'≡';
    const filename=parts.pop(), updated=formatFileTime(f.updated), fullUpdated=f.updated?new Date(f.updated*1000).toLocaleString(state.language==='en'?'en-US':'zh-CN'):'';
    return html+`<button class="file-row${state.file===f.path?' selected':''}" data-path="${esc(f.path)}" title="${esc(f.path)} · ${esc(fullUpdated)}" style="padding-left:${parent?22:10}px"><span class="file-type">${icon}</span><span class="file-name">${esc(filename)}</span><span class="file-updated">${esc(updated)}</span>${state.project.main===f.path?'<span class="file-main">主</span>':''}</button>`;
  }).join('');
  $('file-tree').querySelectorAll('button').forEach(b=>b.onclick=()=>guard(()=>openFile(b.dataset.path)));
}
async function openFile(path) {
  if(state.switching) return;
  state.switching=true;
  const previousReadOnly=editor.getOption('readOnly');
  editor.setOption('readOnly',true);
  try {
    await save();
    const data=await api('file?'+query({path}));
    state.loading=true;state.file=path;state.revision=data.revision;state.dirty=false;
    $('file-tab').textContent=path;$('binary-view').hidden=!data.binary;editor.getWrapperElement().hidden=!!data.binary;
    if(data.binary) {
      editor.setValue('');editor.setOption('readOnly',true);
      const url='/api/raw?'+query({path}), ext=path.split('.').pop().toLowerCase();
      $('binary-view').innerHTML=`<p class="binary-title">${esc(path)}</p>`+(['png','jpg','jpeg','gif','webp'].includes(ext)?`<img src="${url}" alt="${esc(path)}">`:ext==='pdf'?`<iframe src="${url}" title="${esc(path)}"></iframe>`:'<p class="hint">此文件已保存到项目中，可在 LaTeX 中引用。</p>')+`<p><a href="${url}" download>下载文件</a></p>`;
    } else {
      editor.setOption('readOnly',false);editor.setOption('mode',path.endsWith('.tex')?'stex':'text/plain');editor.setValue(data.content);editor.clearHistory();
      const draft=localStorage.getItem(draftKey());
      if(draft) {try{const d=JSON.parse(draft);if(d.content!==data.content){editor.setValue(d.content);state.dirty=true;state.editVersion++;toast('已恢复上次未保存的草稿，请检查后保存。');}}catch(_){}}
      editor.refresh();
    }
    savedLabel(state.dirty?'已恢复未保存草稿':'✓ 所有更改已保存');updateOutline();updateCursor();renderFiles();
    localStorage.setItem('localleaf-file:'+state.project.id,path);
  } catch(e) {editor.setOption('readOnly',previousReadOnly);throw e;}
  finally {state.loading=false;state.switching=false;}
}
async function refreshProject(){const data=await api('project?'+query());state.project=data.project;state.files=data.files;state.build=data.build;$('project-name').textContent=data.project.name;renderFiles();}
async function openProject(pid){
  if(state.compiling) throw new Error('请等待当前编译结束后再切换项目');
  if(state.switching) return;
  state.switching=true;
  const previousReadOnly=editor.getOption('readOnly');editor.setOption('readOnly',true);
  try {
  await save();clearTimeout(autoTimer);
  const data=await api('project?id='+encodeURIComponent(pid));
  state.project=data.project;state.files=data.files;state.build=data.build;state.file=null;state.dirty=false;
  $('project-name').textContent=data.project.name;$('projects-button').title=data.project.path||'';document.title=data.project.name+' · '+(state.language==='en'?'Offline paper workspace':'离线论文工作台');localStorage.setItem('localleaf-project',pid);
  const previous=localStorage.getItem('localleaf-file:'+pid);
  const selected=state.files.some(f=>f.path===previous)?previous:state.project.main||state.files[0]?.path;
  renderFiles();showBuild(data.build);
  state.switching=false;
  if(selected) await openFile(selected);
  else {state.loading=true;editor.setValue('');editor.setOption('readOnly',true);state.loading=false;$('file-tab').textContent='新建一个文件';updateOutline();updateCursor();}
  await refreshGitStatus();
  $('modal').close();
  } catch(e) {editor.setOption('readOnly',previousReadOnly);throw e;}
  finally {state.switching=false;}
}
function showBuild(build) {
  state.build=build;
  $('build-log').textContent=build?.log||'编译后将在这里显示 LaTeX 的完整输出。';
  $('build-summary').textContent=build?(build.ok?`编译成功 · ${build.duration} 秒`:'编译失败 · 查看日志'):'尚未编译';
  $('build-dot').className='status-dot'+(!build?' neutral':!build.ok?' error':'');
  const hasPdf=!!build?.hasPdf;
  $('pdf-viewer').hidden=!hasPdf;$('empty-preview').hidden=hasPdf;
  $('download-pdf').disabled=!hasPdf;$('pdf-open').disabled=!hasPdf;
  $('pdf-zoom-out').disabled=!hasPdf;$('pdf-zoom-in').disabled=!hasPdf;
  if(hasPdf) loadPdfPreview(build).catch(e=>toast('PDF 预览载入失败：'+e.message,true));
  else {state.pdfViewer?.clear();$('pdf-zoom-label').textContent='适合宽度';}
  if(build&&!build.ok) { $('build-log').hidden=false;if(hasPdf)$('build-summary').textContent='编译失败 · 显示上次成功的 PDF'; }
}
async function ensurePdfViewer(){
  if(state.pdfViewer)return state.pdfViewer;
  const {LocalLeafPDFViewer}=await import('/static/pdf-viewer.mjs');
  state.pdfViewer=new LocalLeafPDFViewer($('pdf-viewer'),navigateFromPdf,(zoom,pages)=>{
    $('pdf-zoom-label').textContent=typeof zoom==='number'?`${Math.round(zoom*100)}% · ${pages} 页`:zoom;
  });
  return state.pdfViewer;
}
async function loadPdfPreview(build){
  const viewer=await ensurePdfViewer();
  if(state.build!==build)return;
  $('synctex-hint').classList.toggle('unavailable',build.hasSyncTex===false);
  $('synctex-hint').textContent=build.hasSyncTex===false?'重新编译后可定位源码':'双击正文跳转源码';
  await viewer.load('/api/pdf?'+query({v:build.time}));
}
async function navigateFromPdf(point){
  point.canvas.classList.add('locating');
  try{
    const hit=await api('synctex?'+query({page:point.page,x:point.x.toFixed(3),y:point.y.toFixed(3)}));
    await openFile(hit.path);
    const line=Math.max(0,Math.min(editor.lineCount()-1,hit.line-1));
    const column=Math.max(0,Math.min(editor.getLine(line).length,hit.column||0));
    editor.setCursor({line,ch:column});editor.scrollIntoView({line,ch:column},120);editor.focus();
    if(state.sourceHighlight)editor.removeLineClass(state.sourceHighlight,'background','synctex-source-line');
    state.sourceHighlight=editor.addLineClass(line,'background','synctex-source-line');
    setTimeout(()=>{if(state.sourceHighlight){editor.removeLineClass(state.sourceHighlight,'background','synctex-source-line');state.sourceHighlight=null;}},1800);
    toast(`已定位到 ${hit.path} 第 ${hit.line} 行`);
  }catch(e){toast(e.message,true);}
  finally{point.canvas.classList.remove('locating');}
}
async function compile(){
  if(state.compiling || !state.project || state.switching) return;
  state.compiling=true;clearTimeout(autoTimer);
  $('compile-button').disabled=true;$('first-compile').disabled=true;$('compile-button').classList.add('busy');$('compile-label').textContent='编译中…';
  try{
    await save();const version=state.editVersion;
    const result=await api('compile',{id:state.project.id});showBuild(result);
    if(!result.ok) toast('编译未成功，请查看下方日志。',true);
    else if(version!==state.editVersion) { $('build-summary').textContent+=' · 有新修改待编译';if($('auto-compile').checked)autoTimer=setTimeout(()=>compile(),800); }
  }catch(e){toast(e.message,true);$('build-summary').textContent='编译未完成';$('build-log').textContent=e.message;$('build-log').hidden=false;$('build-dot').className='status-dot error';}
  finally{state.compiling=false;$('compile-button').disabled=false;$('first-compile').disabled=false;$('compile-button').classList.remove('busy');$('compile-label').textContent=state.language==='en'?'Compile again':'重新编译';}
}
function modal(title,html){$('modal-title').textContent=title;$('modal-body').innerHTML=html;if(!$('modal').open)$('modal').showModal();}
async function guard(fn){try{await fn();}catch(e){toast(e.message,true);}}
function bind(id,fn){$(id).onclick=()=>guard(fn);}
function formSubmit(fn){$('modal-form').onsubmit=e=>{e.preventDefault();const b=$('modal-form').querySelector('[type=submit]');b.disabled=true;guard(fn).finally(()=>{if(b.isConnected)b.disabled=false;});};}
bind('language-toggle',()=>applyLanguage(state.language==='en'?'zh':'en'));
bind('theme-toggle',()=>applyTheme(themeOrder[(themeOrder.indexOf(state.theme)+1)%themeOrder.length]));
bind('modal-close',()=> $('modal').close());
$('modal').addEventListener('click',e=>{if(e.target===$('modal')) {const r=$('modal').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$('modal').close();}});
bind('compile-button',compile);bind('first-compile',compile);
function updateGitButton(status){
  state.gitStatus=status;const button=$('git-sync-button'),label=$('git-sync-label');
  button.classList.toggle('connected',!!status?.configured);
  button.classList.toggle('needs-update',!!status?.needsPull);
  const alert=$('git-update-alert');
  if(alert){
    alert.hidden=!status?.needsPull;
    if(status?.needsPull)alert.textContent=state.language==='en'?`⚠ ${status.behind} remote update${status.behind===1?'':'s'} available`:`⚠ 远端有 ${status.behind} 个更新待同步`;
  }
  if(state.syncing){label.textContent='正在同步…';button.classList.add('busy');button.disabled=true;return;}
  button.classList.remove('busy');button.disabled=!status?.available;
  label.textContent=status?.configured?(status?.needsPull?(state.language==='en'?`⚠ Sync (${status.behind})`:`⚠ 同步 (${status.behind})`):(state.language==='en'?'Sync Overleaf':'同步 Overleaf')):(state.language==='en'?'Connect Overleaf':'连接 Overleaf');
  button.title=status?.configured?`一键拉取并推送 · ${status.remote}`:'连接 Overleaf Git 项目';
}
async function refreshGitStatus(){
  if(!state.project)return;
  try{const status=await api('git-status?'+query());updateGitButton(status);if(status.needsPull){const key=state.project.id+':'+status.behind;if(state.gitAlertKey!==key){state.gitAlertKey=key;toast(state.language==='en'?`${status.behind} remote update${status.behind===1?'':'s'} available. Click Sync Overleaf.`:`远端有 ${status.behind} 个更新，请点击“同步 Overleaf”。`,true);}}else state.gitAlertKey='';}
  catch(_){updateGitButton({configured:false,available:state.environment.git});}
}
function gitSetupDialog(){
  const remote=state.gitStatus?.remote||'';
  const saved=!!state.gitStatus?.savedToken;
  modal('连接 Overleaf Git',`<form id="modal-form"><div class="git-connection-card"><strong>${saved?'Token 已保存在 macOS 钥匙串':'首次连接'}</strong>${saved?'连接新项目时可直接复用，无需再次输入 Token。':'在 Overleaf 项目中打开“集成 → Git”，复制 Git 地址或整条 git clone 命令；然后在账户设置中生成 Git authentication token。此功能需要 Overleaf 高级账户或机构权限。'}</div><label class="field">Overleaf Git 地址或 clone 命令<input id="git-remote" type="text" value="${esc(remote)}" placeholder="git clone https://git@git.overleaf.com/项目ID" required spellcheck="false"></label><label class="field">Authentication token<input id="git-token" type="password" ${saved?'':'required'} autocomplete="new-password" spellcheck="false" placeholder="${saved?'留空使用钥匙串中已保存的 Token':'粘贴新生成的 Token'}"></label><label class="field">首次连接方式<select id="git-setup-mode"><option value="pull">采用 Overleaf 最新版本（推荐）</option><option value="upload">保留本地版本并上传到 Overleaf</option></select></label><p class="hint">${saved?'如需更换 Token，在此输入新的值即可覆盖钥匙串记录。':'请粘贴新生成的原始 Token，不要包含空格或 Markdown 格式。'}选择“采用 Overleaf”时，当前本地文件会先存入历史版本，再拉取远端内容，并且首次连接不会推送。<br><a class="git-help-link" href="https://www.overleaf.com/user/settings" target="_blank" rel="noopener">打开 Overleaf 账户设置 ↗</a></p><div class="modal-actions"><button type="submit" class="primary">连接项目</button></div></form>`);
  formSubmit(async()=>{
    await save();state.syncing=true;updateGitButton(state.gitStatus||{available:true});
    try{
      const result=await api('git-setup',{id:state.project.id,remote:$('git-remote').value,token:$('git-token').value,mode:$('git-setup-mode').value});
      updateGitButton(result);$('modal').close();await reloadAfterGitSync();toast(result.message||'已连接 Overleaf');
    }finally{state.syncing=false;updateGitButton(state.gitStatus||{available:true});}
  });
}
async function reloadAfterGitSync(){
  const current=state.file,data=await api('project?'+query());
  state.project=data.project;state.files=data.files;state.build=data.build;
  $('project-name').textContent=data.project.name;renderFiles();showBuild(data.build);
  const selected=state.files.some(f=>f.path===current)?current:(state.files.some(f=>f.path===state.project.main)?state.project.main:state.files[0]?.path);
  if(selected)await openFile(selected);
  await refreshGitStatus();
}
async function syncOverleaf(){
  if(state.syncing)return;await save();state.syncing=true;updateGitButton(state.gitStatus);
  const readOnly=editor.getOption('readOnly');editor.setOption('readOnly',true);
  try{const result=await api('git-sync',{id:state.project.id});updateGitButton(result);await reloadAfterGitSync();toast('Overleaf 同步完成');}
  finally{state.syncing=false;editor.setOption('readOnly',readOnly);updateGitButton(state.gitStatus||{available:true});}
}
bind('git-sync-button',()=>state.gitStatus?.configured?syncOverleaf():gitSetupDialog());
bind('projects-button',async()=>{
  await save();const data=await api('bootstrap');state.projects=data.projects;
  modal('我的项目',`<div>${data.projects.map(p=>`<button class="project-card${p.id===state.project.id?' active':''}" data-project="${p.id}" title="${esc(p.path||'')}"><span class="project-symbol">${p.overleafGit?'⇅':p.localProject?'⌂':'▤'}</span><span><strong>${esc(p.name)}</strong><small>${new Date(p.updated*1000).toLocaleString('zh-CN')} · ${esc(p.engine)}${p.localProject?`<span class="project-git-badge local-project-badge">Local</span><em class="project-path">${esc(p.path)}</em>`:''}${p.overleafGit?`<span class="project-git-badge">Overleaf · ${esc(p.gitBranch||'Git')}</span>`:''}</small></span></button>`).join('')}</div><div class="modal-actions"><button id="import-project" class="secondary">导入 ZIP</button><button id="import-local-project" class="secondary">打开本地文件夹</button><button id="import-git-project" class="secondary">从 Overleaf Git 导入</button><button id="new-project" class="primary">＋ 新建项目</button></div>`);
  $('modal-body').querySelectorAll('[data-project]').forEach(b=>b.onclick=()=>guard(()=>openProject(b.dataset.project)));
  bind('import-project',()=>$('zip-upload').click());bind('import-local-project',localProjectDialog);bind('import-git-project',gitImportDialog);bind('new-project',newProjectDialog);
});
function localProjectDialog(){
  const english=state.language==='en';
  modal(english?'Open local folder':'打开本地文件夹',`<form id="modal-form"><label class="field">${english?'Project name':'项目名称'}<input id="local-project-name" placeholder="${english?'Defaults to the folder name':'默认使用文件夹名称'}" maxlength="100"></label><label class="field">${english?'Folder path':'文件夹路径'}<div class="path-picker"><input id="local-project-path" placeholder="/Users/you/Documents/paper" required spellcheck="false"><button id="pick-local-folder" type="button" class="secondary">${english?'Choose…':'选择…'}</button></div></label><p class="hint">${english?'Files stay in the selected folder. LocalLeaf only saves project settings and history alongside its project record.':'文件会继续保存在所选文件夹中。LocalLeaf 不会复制文件，只保存项目设置和历史记录。'}</p><div class="modal-actions"><button type="submit" class="primary">${english?'Add local project':'添加本地项目'}</button></div></form>`);
  bind('pick-local-folder',async()=>{const picked=await api('pick-local-folder',{});$('local-project-path').value=picked.path;if(!$('local-project-name').value)$('local-project-name').value=picked.path.split('/').filter(Boolean).pop()||'';});
  formSubmit(async()=>{const project=await api('local-import',{name:$('local-project-name').value,path:$('local-project-path').value});await openProject(project.id);toast(english?'Local project added':'本地项目已添加');});
}
function gitImportDialog(){
  const saved=!!state.gitStatus?.savedToken;
  modal('从 Overleaf Git 导入',`<form id="modal-form"><label class="field">Overleaf 项目名称<input id="git-import-name" placeholder="例如 ICRA 2027 Paper" required maxlength="100"></label><label class="field">Git 地址或 clone 命令<input id="git-import-remote" placeholder="git clone https://git@git.overleaf.com/项目ID" required spellcheck="false"></label><label class="field">Authentication token<input id="git-import-token" type="password" ${saved?'':'required'} autocomplete="new-password" placeholder="${saved?'留空使用钥匙串中已保存的 Token':'粘贴新生成的 Token'}"></label><p class="hint">将创建同名本地项目并采用 Overleaf 最新文件。${saved?'当前已有 Token 保存在 macOS 钥匙串。':'首次成功后 Token 会保存在 macOS 钥匙串，后续项目无需再输入。'}</p><div class="modal-actions"><button type="submit" class="primary">导入项目</button></div></form>`);
  formSubmit(async()=>{const project=await api('git-import',{name:$('git-import-name').value,remote:$('git-import-remote').value,token:$('git-import-token').value});await openProject(project.id);toast('Overleaf 项目已导入');});
}
function newProjectDialog(){
  modal('新建论文项目','<form id="modal-form"><label class="field">项目名称<input id="new-project-name" required value="Untitled Paper" maxlength="100"></label><label class="field">起始模板<select id="project-template"><option value="english">英文研究论文 · Article</option><option value="chinese">中文研究论文 · CTeX</option></select></label><p class="hint">包含主文件、引言章节和 BibTeX 参考文献。所有文件保存在本机。</p><div class="modal-actions"><button class="primary" type="submit">创建项目</button></div></form>');
  formSubmit(async()=>{await save();const p=await api('create',{name:$('new-project-name').value,template:$('project-template').value});await openProject(p.id);});
}
bind('new-file-button',()=>{
  modal('新建文件','<form id="modal-form"><label class="field">文件路径<input id="new-path" placeholder="sections/methods.tex" required></label><p class="hint">使用 / 创建文件夹，如 figures/notes.txt。</p><div class="modal-actions"><button type="submit" class="primary">创建文件</button></div></form>');
  formSubmit(async()=>{await save();const path=$('new-path').value.trim();await api('new-file',{id:state.project.id,path});await refreshProject();await openFile(path);$('modal').close();});
});
bind('file-menu-button',()=>{
  if(!state.file)return;
  modal('文件操作',`<form id="modal-form"><label class="field">重命名 / 移动文件<input id="rename-path" value="${esc(state.file)}" required></label><p class="hint">重命名后，请同步修改 LaTeX 中的 input、include 或图片引用路径。</p><div class="modal-actions"><button id="delete-file" class="danger" type="button">删除文件</button><button id="download-draft" type="button" class="secondary">下载编辑副本</button><button type="submit" class="primary">重命名</button></div></form>`);
  bind('download-draft',()=>{const blob=new Blob([editor.getValue()],{type:'text/plain;charset=utf-8'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=state.file.split('/').pop();a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);});
  formSubmit(async()=>{await save();const path=$('rename-path').value.trim();await api('rename',{id:state.project.id,path:state.file,newPath:path});await refreshProject();await openFile(path);$('modal').close();});
  bind('delete-file',()=>{const path=state.file;modal('删除文件',`<p>删除 <strong>${esc(path)}</strong>？可从历史版本恢复。</p><div class="modal-actions"><button id="confirm-delete" class="danger">删除</button></div>`);bind('confirm-delete',async()=>{await save();await api('delete',{id:state.project.id,path});state.file=null;await refreshProject();await openFile(state.project.main||state.files[0].path);$('modal').close();});});
});
bind('settings-button',()=>{
  modal('项目设置',`<form id="modal-form"><label class="field">项目名称<input id="setting-name" value="${esc(state.project.name)}" required></label><label class="field">主文件<select id="setting-main">${state.files.filter(f=>f.path.endsWith('.tex')).map(f=>`<option${f.path===state.project.main?' selected':''}>${esc(f.path)}</option>`).join('')}</select></label><label class="field">编译器<select id="setting-engine">${['xelatex','pdflatex','lualatex'].map(x=>`<option value="${x}"${x===state.project.engine?' selected':''}>${x}${state.environment.engines?.[x]?'':'（未安装）'}</option>`).join('')}</select></label><p class="hint">项目文件夹会使用这里的项目名称。中文论文请选择 XeLaTeX。编译自动处理 BibTeX / Biber 和交叉引用。</p><div class="modal-actions"><button id="git-settings-button" type="button" class="secondary">Overleaf Git 设置</button><button type="submit" class="primary">保存设置</button></div></form>`);
  bind('git-settings-button',gitSetupDialog);
  formSubmit(async()=>{await save();state.project=await api('settings',{id:state.project.id,name:$('setting-name').value,main:$('setting-main').value,engine:$('setting-engine').value});localStorage.setItem('localleaf-project',state.project.id);$('project-name').textContent=state.project.name;document.title=state.project.name+' · '+(state.language==='en'?'Offline paper workspace':'离线论文工作台');renderFiles();await refreshGitStatus();$('modal').close();toast('设置已保存');});
});
bind('history-button',async()=>{
  await save();const rows=await api('history?'+query());
  modal('历史版本',`<p class="hint">自动保留本项目最近 200 次文件修改前的内容，也可恢复已删除文件。</p>${rows.length?rows.map(r=>`<div class="history-row"><div><strong>${esc(r.path)}</strong><small>${new Date(r.time*1000).toLocaleString('zh-CN')} · ${r.size} 字节</small></div><button data-restore="${r.id}">恢复</button></div>`).join(''):'<p>开始编辑并保存后，历史版本会出现在这里。</p>'}`);
  $('modal-body').querySelectorAll('[data-restore]').forEach(b=>b.onclick=()=>{const hid=b.dataset.restore;modal('恢复此版本？','<p>当前已保存的内容也会保留到历史版本中。</p><div class="modal-actions"><button id="confirm-restore" class="primary">恢复版本</button></div>');bind('confirm-restore',async()=>{await save();const r=await api('restore',{id:state.project.id,historyId:hid});await refreshProject();await openFile(r.path);$('modal').close();toast('历史版本已恢复');});});
});
bind('help-button',()=>modal('在本机安心写作',`<div class="help-content"><ul><li>直接编辑源码，停止输入后自动保存。<strong>⌘S</strong> 立即保存，<strong>⌘Enter</strong> 编译。</li><li>在「项目」菜单导入 Overleaf 下载的 ZIP，选择对应主文件和编译器即可继续写作。</li><li>顶部“同步 Overleaf”会先拉取合作者的更新，再提交并推送本地文件；首次使用需填写 Git 地址和 authentication token。</li><li>图片与参考文献可以通过左上角上传按钮添加。已有同名文件不会被覆盖。</li><li><strong>双击 PDF 正文</strong>可打开对应 LaTeX 文件并定位到相关行；修改后需重新编译以更新位置映射。</li><li><strong>⌘F</strong> 查找与替换，<strong>⌘/</strong> 切换注释。拖动中间分隔条调整宽度。</li><li>PDF 来自本机真实的 LaTeX 编译。失败时日志会保留，预览显示上次成功的 PDF。</li><li>退出浏览器前等待「所有更改已保存」。下次双击 <code>LocalLeaf.app</code>。</li></ul><p class="hint">项目文件夹：${esc(state.dataPath||'')}<br>离线编译需要模板所用的宏包已在本机安装。Overleaf 同步需要联网。</p></div>`));
bind('export-button',async()=>{await save();window.location.href='/api/export?'+query();});
bind('download-pdf',()=>{window.location.href='/api/pdf?'+query({download:'1'});});
bind('pdf-open',()=>window.open('/api/pdf?'+query(),'_blank','noopener'));
bind('pdf-zoom-out',()=>state.pdfViewer?.setZoom(-.15));bind('pdf-zoom-in',()=>state.pdfViewer?.setZoom(.15));
bind('log-toggle',()=>{$('build-log').hidden=!$('build-log').hidden;editor.refresh();});
bind('upload-button',()=>$('file-upload').click());
function toBase64(file){return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=()=>reject(new Error('读取文件失败'));r.readAsDataURL(file);});}
$('file-upload').onchange=()=>guard(async()=>{
  await save();for(const file of $('file-upload').files){if(file.size>20*1024*1024)throw new Error('单个文件不能超过 20 MB');await api('upload',{id:state.project.id,path:file.name,data:await toBase64(file)});}
  await refreshProject();$('file-upload').value='';toast('文件已上传到本地项目');
});
$('zip-upload').onchange=()=>guard(async()=>{
  const file=$('zip-upload').files[0];if(!file)return;if(file.size>80*1024*1024)throw new Error('ZIP 不能超过 80 MB');await save();toast('正在导入项目…');
  const p=await api('import',{name:file.name.replace(/\.zip$/i,''),data:await toBase64(file)});await openProject(p.id);$('zip-upload').value='';toast('项目导入完成');
});
function toggleSearch(open=!$('search-bar').hidden){$('search-bar').hidden=!open;editor.refresh();if(open)$('find-input').focus();}
bind('search-button',()=>toggleSearch($('search-bar').hidden));bind('close-search',()=>toggleSearch(false));
function findNext(){const needle=$('find-input').value;if(!needle)return;const text=editor.getValue(),start=editor.indexFromPos(editor.getCursor('to'));let i=text.indexOf(needle,start);if(i<0)i=text.indexOf(needle);if(i<0){toast('没有找到匹配文本');return;}editor.setSelection(editor.posFromIndex(i),editor.posFromIndex(i+needle.length));editor.scrollIntoView({from:editor.posFromIndex(i),to:editor.posFromIndex(i+needle.length)},60);}
bind('find-next',findNext);$('find-input').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();findNext();}};
bind('replace-one',()=>{if(editor.getOption('readOnly'))return;if(editor.getSelection()===$('find-input').value && $('find-input').value)editor.replaceSelection($('replace-input').value);findNext();});
bind('replace-all',()=>{if(editor.getOption('readOnly'))return;const needle=$('find-input').value;if(!needle)return;const text=editor.getValue(),n=text.split(needle).length-1;if(n){editor.replaceRange(text.split(needle).join($('replace-input').value),{line:0,ch:0},editor.posFromIndex(text.length));toast(`已替换 ${n} 处`);}else toast('没有找到匹配文本');});
function toggleComment(){if(editor.getOption('readOnly'))return;const a=editor.getCursor('from').line,b=editor.getCursor('to').line;const uncomment=Array.from({length:b-a+1},(_,i)=>editor.getLine(a+i)).every(l=>l.startsWith('% '));editor.operation(()=>{for(let i=a;i<=b;i++)editor.replaceRange(uncomment?'':'% ',{line:i,ch:0},{line:i,ch:uncomment?2:0});});}
document.querySelectorAll('[data-insert]').forEach(b=>b.onclick=()=>{
  if(editor.getOption('readOnly'))return;const text=editor.getSelection();const snippets={bold:`\\textbf{${text||'text'}}`,italic:`\\textit{${text||'text'}}`,equation:`\n\\begin{equation}\n  ${text||'E = mc^2'}\n\\end{equation}\n`,cite:`\\cite{${text||'lamport1994'}}`};editor.replaceSelection(snippets[b.dataset.insert]);editor.focus();
});
$('auto-compile').checked=localStorage.getItem('localleaf-auto')==='true';
$('auto-compile').onchange=()=>{localStorage.setItem('localleaf-auto',$('auto-compile').checked);if(!$('auto-compile').checked)clearTimeout(autoTimer);};
bind('font-size-button',()=>{let size=parseInt(editor.getWrapperElement().style.fontSize)||13;size=size>=18?12:size+1;editor.getWrapperElement().style.fontSize=size+'px';localStorage.setItem('localleaf-font',size);editor.refresh();toast('编辑字号：'+size+'px');});
const splitter=$('splitter');let dragging=false;
function setSplit(ratio){ratio=Math.min(.72,Math.max(.28,ratio));document.documentElement.style.setProperty('--editor-fraction',ratio);splitter.setAttribute('aria-valuenow',Math.round(ratio*100));editor.refresh();}
setSplit(Number(localStorage.getItem('localleaf-split'))||.5);
splitter.onpointerdown=e=>{dragging=true;splitter.setPointerCapture(e.pointerId);$('pdf-viewer').style.pointerEvents='none';};
splitter.onpointermove=e=>{if(!dragging)return;const side=document.querySelector('.sidebar').getBoundingClientRect().right;setSplit((e.clientX-side)/(window.innerWidth-side));};
function endDrag(){dragging=false;$('pdf-viewer').style.pointerEvents='';localStorage.setItem('localleaf-split',parseFloat(document.documentElement.style.getPropertyValue('--editor-fraction')));}
splitter.onpointerup=endDrag;splitter.onpointercancel=endDrag;
splitter.onkeydown=e=>{if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();setSplit(Number(splitter.getAttribute('aria-valuenow'))/100+(e.key==='ArrowLeft'?-.03:.03));endDrag();}};
window.addEventListener('beforeunload',e=>{if(state.dirty){keepDraft();e.preventDefault();e.returnValue='';}});
document.addEventListener('visibilitychange',()=>{if(document.hidden&&state.dirty){keepDraft();save().catch(()=>{});}});
document.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key==='Enter'){e.preventDefault();compile();}if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='s'){e.preventDefault();guard(save);}});
async function init(){
  const data=await api('bootstrap');
  if(data.apiVersion!==EXPECTED_API_VERSION)throw new Error(state.language==='en'?'The LocalLeaf background service is outdated. Quit LocalLeaf and open LocalLeaf.app again.':'LocalLeaf 后台版本过旧，请退出后重新打开 LocalLeaf.app。');
  state.token=data.token;state.projects=data.projects;state.environment=data.environment;state.dataPath=data.dataPath;
  const ready=data.environment.engines.xelatex && data.environment.latexmk;$('engine-note').textContent=ready?'XeLaTeX 已就绪 · 无需联网':'本地编译器未就绪 · 查看使用说明';
  const previous=localStorage.getItem('localleaf-project');await openProject(data.projects.some(p=>p.id===previous)?previous:data.projects[0].id);
}
init().catch(e=>{savedLabel('无法连接本地服务',true);toast(e.message,true);});

// Optional browser-native tool surface; ordinary offline browsers need no support.
if(document.modelContext?.registerTool){
  const lifecycle=new AbortController();
  const tool={name:'read_localleaf_workspace',title:'读取本地论文工作台',description:'读取当前项目、文件和编译状态。返回当前未保存的编辑内容，不修改文件。',
    inputSchema:{type:'object',properties:{},additionalProperties:false},annotations:{readOnlyHint:true,untrustedContentHint:true},
    execute(input){if(input===null||typeof input!=='object'||Array.isArray(input)||Object.keys(input).length)throw new Error('Expected an empty object');return {project:state.project?.name,file:state.file,content:editor.getValue(),unsaved:state.dirty,compiled:state.build?.ok??null};}};
  try{Promise.resolve(document.modelContext.registerTool(tool,{signal:lifecycle.signal})).catch(()=>{});}catch(_){}
  window.addEventListener('pagehide',()=>lifecycle.abort(),{once:true});
}
