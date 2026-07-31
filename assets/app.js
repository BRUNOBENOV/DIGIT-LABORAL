(() => {
  const $ = (s, r=document) => r.querySelector(s);
  const $$ = (s, r=document) => [...r.querySelectorAll(s)];
  const fmt = n => 'Gs. ' + Math.round(Number(n||0)).toLocaleString('es-PY');
  const today = () => new Date().toLocaleDateString('es-PY');
  const uid = () => Math.random().toString(36).slice(2,10);
  const defaults = {
    companies: [
      {id:'c1',legalName:"Victor's Contabilidad S.A.",ruc:'80012345-6',city:'Ciudad del Este',responsible:'Bruno Benítez',status:'Activa'},
      {id:'c2',legalName:'Comercial Paraná S.A.',ruc:'80123456-7',city:'Ciudad del Este',responsible:'María López',status:'Activa'},
      {id:'c3',legalName:'Servicios del Este S.R.L.',ruc:'80076543-2',city:'Hernandarias',responsible:'Equipo Laboral',status:'Pendiente'}
    ],
    employees: [
      {id:'e1',company:'c1',name:'Juan Pérez González',document:'3.450.123',position:'Auxiliar administrativo',admission:'2024-02-01',salary:3044000,ips:true},
      {id:'e2',company:'c1',name:'María López Benítez',document:'4.120.987',position:'Encargada',admission:'2023-08-15',salary:4500000,ips:true},
      {id:'e3',company:'c2',name:'Pedro Benítez',document:'5.600.320',position:'Vendedor',admission:'2025-03-10',salary:3250000,ips:true}
    ],
    requests: [
      {id:'r1',date:'30/07/2026',company:'Comercial Paraná S.A.',type:'Alta',subject:'Ingreso de nuevo vendedor',priority:'Alta',status:'Pendiente',owner:'María López'},
      {id:'r2',date:'29/07/2026',company:'Servicios del Este S.R.L.',type:'Cambio salarial',subject:'Propuesta de aumento',priority:'Normal',status:'En revisión',owner:'Bruno Benítez'},
      {id:'r3',date:'28/07/2026',company:"Victor's Contabilidad S.A.",type:'Documento',subject:'Constancia laboral',priority:'Normal',status:'Resuelta',owner:'Equipo Laboral'}
    ],
    audit: [
      {date:'31/07/2026 14:25',user:'admin@digitlaboral.com.py',action:'Inicio de sesión',entity:'Usuario',detail:'Acceso de demostración'},
      {date:'31/07/2026 13:48',user:'maria@demo.com.py',action:'Actualización',entity:'Funcionario',detail:'Cambio de cargo'},
      {date:'30/07/2026 17:12',user:'admin@digitlaboral.com.py',action:'Creación',entity:'Empresa',detail:'Servicios del Este S.R.L.'}
    ]
  };
  const state = {
    companies: JSON.parse(localStorage.getItem('digit_companies')||'null') || defaults.companies,
    employees: JSON.parse(localStorage.getItem('digit_employees')||'null') || defaults.employees,
    requests: JSON.parse(localStorage.getItem('digit_requests')||'null') || defaults.requests,
    audit: JSON.parse(localStorage.getItem('digit_audit')||'null') || defaults.audit,
    requestFilter:'all', legalQuery:''
  };
  const legal = [
    {article:'Art. 9',category:'Principios',title:'Irrenunciabilidad',text:'Referencia orientativa sobre la protección de los derechos reconocidos al trabajador y los límites de su renuncia.'},
    {article:'Art. 39',category:'Contrato',title:'Contrato de trabajo',text:'Referencia general para identificar la relación laboral y las obligaciones que nacen del contrato.'},
    {article:'Art. 62',category:'Empleador',title:'Obligaciones del empleador',text:'Resumen demostrativo de deberes relacionados con pago, trato, seguridad, medios de trabajo y constancias.'},
    {article:'Art. 67',category:'Trabajador',title:'Obligaciones del trabajador',text:'Referencia orientativa sobre cumplimiento, diligencia, cuidado y conducta en la relación de trabajo.'},
    {article:'Art. 91',category:'Terminación',title:'Terminación del contrato',text:'Índice temático para localizar reglas relacionadas con la finalización del vínculo laboral.'},
    {article:'Art. 243',category:'Salarios',title:'Salario mínimo',text:'Referencia orientativa sobre la finalidad protectora del salario mínimo y su determinación.'},
    {article:'Art. 250',category:'Salarios',title:'Pago del salario',text:'Índice temático sobre forma, oportunidad y comprobación del pago de remuneraciones.'},
    {article:'Art. 256',category:'Salarios',title:'Protección salarial',text:'Referencia temática sobre protección, descuentos y límites aplicables a la remuneración.'},
    {article:'Art. 259',category:'Aguinaldo',title:'Remuneración anual complementaria',text:'Ubicación temática para revisar el cálculo y pago del aguinaldo en el texto vigente.'},
    {article:'Art. 275',category:'Vacaciones',title:'Vacaciones anuales',text:'Referencia temática sobre descanso anual remunerado, antigüedad y oportunidad de goce.'}
  ];
  function save(){
    localStorage.setItem('digit_companies',JSON.stringify(state.companies));
    localStorage.setItem('digit_employees',JSON.stringify(state.employees));
    localStorage.setItem('digit_requests',JSON.stringify(state.requests));
    localStorage.setItem('digit_audit',JSON.stringify(state.audit.slice(0,30)));
  }
  function toast(msg){const t=$('#toast');t.textContent=msg;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2400)}
  function audit(action,entity,detail){state.audit.unshift({date:new Date().toLocaleString('es-PY'),user:'admin@digitlaboral.com.py',action,entity,detail});save();renderAudit()}
  function showView(id){
    $$('.app-view').forEach(v=>v.classList.toggle('active',v.id===id));
    $$('.app-nav button').forEach(b=>b.classList.toggle('active',b.dataset.view===id));
    if($('#mobileView')) $('#mobileView').value=['inicio','tramites','calculadoras','codigo','consulta','admin'].includes(id)?id:'inicio';
    window.scrollTo({top:0,behavior:'smooth'});
    history.replaceState(null,'','#'+id);
  }
  $$('[data-view]').forEach(el=>el.addEventListener('click',()=>showView(el.dataset.view)));
  $('#mobileView')?.addEventListener('change',e=>showView(e.target.value));
  if(location.hash && $(location.hash)) showView(location.hash.slice(1));

  function renderCompanies(filter=''){
    const q=filter.toLowerCase();
    $('#companyRows').innerHTML=state.companies.filter(c=>!q||`${c.legalName} ${c.ruc} ${c.city}`.toLowerCase().includes(q)).map(c=>`<tr><td><b>${esc(c.legalName)}</b></td><td>${esc(c.ruc)}</td><td>${esc(c.city)}</td><td>${esc(c.responsible||'—')}</td><td><span class="status ${c.status==='Pendiente'?'warn':''}">${esc(c.status)}</span></td><td class="actions-cell"><button class="icon-btn" data-edit-company="${c.id}" title="Editar">✎</button><button class="icon-btn" data-delete-company="${c.id}" title="Eliminar">🗑</button></td></tr>`).join('') || '<tr><td colspan="6">No se encontraron empresas.</td></tr>';
    $('#employeeCompany').innerHTML=state.companies.map(c=>`<option value="${c.id}">${esc(c.legalName)}</option>`).join('');
    $('#docCompany').innerHTML=state.companies.map(c=>`<option value="${c.id}">${esc(c.legalName)}</option>`).join('');
    $('#metricCompanies').textContent=state.companies.length;
    bindCompanyActions();
  }
  function renderEmployees(filter=''){
    const q=filter.toLowerCase();
    $('#employeeRows').innerHTML=state.employees.filter(e=>!q||`${e.name} ${e.document} ${e.position}`.toLowerCase().includes(q)).map(e=>{const c=state.companies.find(x=>x.id===e.company);return `<tr><td><b>${esc(e.name)}</b></td><td>${esc(e.document)}</td><td>${esc(c?.legalName||'—')}</td><td>${esc(e.position||'—')}</td><td>${fmt(e.salary)}</td><td>${e.ips?'Sí':'No'}</td><td class="actions-cell"><button class="icon-btn" data-edit-employee="${e.id}">✎</button><button class="icon-btn" data-delete-employee="${e.id}">🗑</button></td></tr>`}).join('') || '<tr><td colspan="7">No se encontraron funcionarios.</td></tr>';
    $('#docEmployee').innerHTML=state.employees.map(e=>`<option value="${e.id}">${esc(e.name)}</option>`).join('');
    $('#metricEmployees').textContent=Math.max(146,state.employees.length);
    bindEmployeeActions();
  }
  function renderRequests(){
    const list=state.requests.filter(r=>state.requestFilter==='all'||r.status===state.requestFilter);
    $('#requestRows').innerHTML=list.map(r=>`<tr><td>${r.date}</td><td><b>${esc(r.company)}</b></td><td>${esc(r.type)}</td><td>${esc(r.subject)}</td><td><span class="status ${r.priority==='Alta'?'red':'blue'}">${esc(r.priority)}</span></td><td><span class="status ${r.status==='Pendiente'?'warn':r.status==='Resuelta'?'':'blue'}">${esc(r.status)}</span></td><td>${esc(r.owner)}</td></tr>`).join('') || '<tr><td colspan="7">No hay solicitudes en este estado.</td></tr>';
    $('#metricRequests').textContent=state.requests.filter(r=>r.status!=='Resuelta').length;
  }
  function renderAudit(){if(!$('#auditRows'))return;$('#auditRows').innerHTML=state.audit.map(a=>`<tr><td>${esc(a.date)}</td><td>${esc(a.user)}</td><td>${esc(a.action)}</td><td>${esc(a.entity)}</td><td>${esc(a.detail)}</td></tr>`).join('')}
  function renderLegal(){
    const q=state.legalQuery.toLowerCase();
    $('#legalList').innerHTML=legal.filter(x=>!q||`${x.article} ${x.category} ${x.title} ${x.text}`.toLowerCase().includes(q)).map(x=>`<article class="legal-item"><div class="legal-num">${x.article}</div><div class="legal-copy"><small>${x.category.toUpperCase()}</small><h3>${x.title}</h3><p>${x.text}</p></div></article>`).join('') || '<div class="panel">No se encontraron coincidencias.</div>';
  }
  function esc(s){return String(s??'').replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]))}
  function bindCompanyActions(){
    $$('[data-delete-company]').forEach(b=>b.onclick=()=>{const id=b.dataset.deleteCompany;const c=state.companies.find(x=>x.id===id);if(!confirm(`¿Eliminar ${c?.legalName}?`))return;state.companies=state.companies.filter(x=>x.id!==id);state.employees=state.employees.filter(x=>x.company!==id);audit('Eliminación','Empresa',c?.legalName||id);save();renderAll();toast('Empresa eliminada')});
    $$('[data-edit-company]').forEach(b=>b.onclick=()=>{const c=state.companies.find(x=>x.id===b.dataset.editCompany);openSimpleModal('Editar empresa',`<div class="form-grid"><div class="field"><label>Razón social</label><input id="mLegal" value="${esc(c.legalName)}"></div><div class="form-row"><div class="field"><label>RUC</label><input id="mRuc" value="${esc(c.ruc)}"></div><div class="field"><label>Ciudad</label><input id="mCity" value="${esc(c.city)}"></div></div></div>`,()=>{c.legalName=$('#mLegal').value;c.ruc=$('#mRuc').value;c.city=$('#mCity').value;audit('Actualización','Empresa',c.legalName);save();renderAll();toast('Empresa actualizada')})});
  }
  function bindEmployeeActions(){
    $$('[data-delete-employee]').forEach(b=>b.onclick=()=>{const id=b.dataset.deleteEmployee;const e=state.employees.find(x=>x.id===id);if(!confirm(`¿Eliminar ${e?.name}?`))return;state.employees=state.employees.filter(x=>x.id!==id);audit('Eliminación','Funcionario',e?.name||id);save();renderEmployees();toast('Funcionario eliminado')});
    $$('[data-edit-employee]').forEach(b=>b.onclick=()=>{const e=state.employees.find(x=>x.id===b.dataset.editEmployee);openSimpleModal('Editar funcionario',`<div class="form-grid"><div class="field"><label>Nombre</label><input id="mName" value="${esc(e.name)}"></div><div class="form-row"><div class="field"><label>Cargo</label><input id="mPosition" value="${esc(e.position)}"></div><div class="field"><label>Salario</label><input id="mSalary" type="number" value="${e.salary}"></div></div></div>`,()=>{e.name=$('#mName').value;e.position=$('#mPosition').value;e.salary=Number($('#mSalary').value);audit('Actualización','Funcionario',e.name);save();renderEmployees();toast('Funcionario actualizado')})});
  }
  $('#companyForm')?.addEventListener('submit',e=>{e.preventDefault();const f=new FormData(e.currentTarget);const c={id:uid(),legalName:f.get('legalName').trim(),ruc:f.get('ruc').trim(),city:f.get('city').trim(),responsible:f.get('responsible').trim(),status:'Activa'};state.companies.push(c);audit('Creación','Empresa',c.legalName);save();e.currentTarget.reset();renderAll();toast('Empresa guardada')});
  $('#employeeForm')?.addEventListener('submit',e=>{e.preventDefault();const f=new FormData(e.currentTarget);const emp={id:uid(),company:f.get('company'),name:f.get('name').trim(),document:f.get('document').trim(),position:f.get('position').trim(),admission:f.get('admission'),salary:Number(f.get('salary')||0),ips:f.get('ips')==='on'};state.employees.push(emp);audit('Creación','Funcionario',emp.name);save();e.currentTarget.reset();renderEmployees();toast('Funcionario guardado')});
  $('#companySearch')?.addEventListener('input',e=>renderCompanies(e.target.value));
  $('#employeeSearch')?.addEventListener('input',e=>renderEmployees(e.target.value));
  $$('[data-maint]').forEach(b=>b.onclick=()=>{$$('[data-maint]').forEach(x=>x.classList.toggle('active',x===b));$$('.maint-panel').forEach(x=>x.classList.add('hidden'));$('#maint'+b.dataset.maint[0].toUpperCase()+b.dataset.maint.slice(1)).classList.remove('hidden');});
  $$('[data-request-filter]').forEach(b=>b.onclick=()=>{$$('[data-request-filter]').forEach(x=>x.classList.toggle('active',x===b));state.requestFilter=b.dataset.requestFilter;renderRequests()});
  $('#newRequestBtn')?.addEventListener('click',()=>openSimpleModal('Nueva solicitud',`<div class="form-grid"><div class="field"><label>Empresa</label><select id="mReqCompany">${state.companies.map(c=>`<option>${esc(c.legalName)}</option>`).join('')}</select></div><div class="form-row"><div class="field"><label>Tipo</label><select id="mReqType"><option>Alta</option><option>Baja</option><option>Cambio salarial</option><option>Documento</option><option>Vacaciones</option></select></div><div class="field"><label>Prioridad</label><select id="mReqPriority"><option>Normal</option><option>Alta</option></select></div></div><div class="field"><label>Asunto</label><input id="mReqSubject" placeholder="Describí brevemente la solicitud"></div></div>`,()=>{const r={id:uid(),date:today(),company:$('#mReqCompany').value,type:$('#mReqType').value,subject:$('#mReqSubject').value||'Nueva solicitud',priority:$('#mReqPriority').value,status:'Pendiente',owner:'Sin asignar'};state.requests.unshift(r);audit('Creación','Solicitud',r.subject);save();renderRequests();toast('Solicitud registrada')}));
  $('#newCompanyBtn')?.addEventListener('click',()=>{showView('mantenimientos');$('#companyForm input')?.focus()});
  $('#newSectionBtn')?.addEventListener('click',()=>toast('Formulario de sección preparado para la versión con base de datos'));
  $('#newUserBtn')?.addEventListener('click',()=>openSimpleModal('Nuevo usuario',`<div class="form-grid"><div class="field"><label>Nombre completo</label><input id="mUserName"></div><div class="field"><label>Correo</label><input id="mUserEmail" type="email"></div><div class="field"><label>Rol</label><select id="mUserRole"><option>Administrador</option><option>Contador</option><option>Auxiliar</option><option>Empresa vinculada</option></select></div></div>`,()=>{audit('Creación','Usuario',$('#mUserEmail').value);toast('Usuario agregado a la demostración')}));

  function calculate(){const gross=Number($('#grossSalary').value||0)+Number($('#otherIncome').value||0);const ips=$('#calcIps').checked?gross*.09:0;const net=gross-ips-Number($('#otherDiscount').value||0);$('#grossResult').textContent=fmt(gross);$('#ipsResult').textContent=fmt(ips);$('#netResult').textContent=fmt(net)}
  $('#quickCalc')?.addEventListener('submit',e=>{e.preventDefault();calculate();audit('Cálculo','Salario','Simulación rápida');toast('Cálculo actualizado')});
  ['grossSalary','otherIncome','otherDiscount','calcIps'].forEach(id=>$('#'+id)?.addEventListener('input',calculate));
  $('#annualIncome')?.addEventListener('input',e=>$('#aguinaldoResult').textContent=fmt(Number(e.target.value||0)/12));
  $$('[data-calc]').forEach(c=>c.onclick=()=>{const type=c.dataset.calc;if(type==='salary'||type==='aguinaldo'){showView('calculadoras');return}openSimpleModal(c.querySelector('h3').textContent,`<div class="notice">Este módulo ya está definido dentro de la arquitectura del sistema. La demostración muestra el flujo; el cierre definitivo requiere la base de datos productiva y parámetros jurídicos verificados.</div><div class="form-grid" style="margin-top:15px"><div class="field"><label>Empresa</label><select>${state.companies.map(x=>`<option>${esc(x.legalName)}</option>`).join('')}</select></div><div class="field"><label>Funcionario</label><select>${state.employees.map(x=>`<option>${esc(x.name)}</option>`).join('')}</select></div><div class="field"><label>Observación</label><textarea placeholder="Detalle del movimiento"></textarea></div></div>`,()=>toast('Borrador guardado en la demostración'))});
  $$('.report-btn').forEach(b=>b.onclick=()=>openReport(b.dataset.report));
  function openReport(name){const rows=state.employees.map(e=>{const c=state.companies.find(x=>x.id===e.company);return `<tr><td>${esc(e.name)}</td><td>${esc(c?.legalName||'')}</td><td>${esc(e.position)}</td><td>${fmt(e.salary)}</td></tr>`}).join('');openSimpleModal(name,`<div class="notice">Vista previa generada con los datos demostrativos del navegador.</div><div class="table-wrap" style="margin-top:14px"><table class="data-table"><thead><tr><th>Funcionario</th><th>Empresa</th><th>Cargo</th><th>Salario</th></tr></thead><tbody>${rows}</tbody></table></div>`,()=>{download(`${slug(name)}.csv`,'Funcionario,Empresa,Cargo,Salario\n'+state.employees.map(e=>{const c=state.companies.find(x=>x.id===e.company);return `"${e.name}","${c?.legalName||''}","${e.position}",${e.salary}`}).join('\n'),'text/csv');toast('Informe descargado')},'Descargar CSV')}
  $('#exportReportBtn')?.addEventListener('click',()=>openReport('Resumen general'));
  $$('.utility-btn').forEach(b=>b.onclick=()=>openSimpleModal(b.dataset.utility,`<div class="notice">Flujo preparado. En producción esta acción queda registrada y requiere permisos de administrador.</div><div class="field" style="margin-top:14px"><label>Observación</label><textarea placeholder="Motivo o detalle"></textarea></div>`,()=>{audit('Ejecución','Utilitario',b.dataset.utility);toast('Acción registrada')}));

  const docBodies={
    'Certificado de Trabajo':'Se expide el presente certificado a solicitud de la persona interesada, para los fines que estime convenientes.',
    'Constancia Laboral':'Se deja constancia de la relación laboral indicada y de los datos consignados en este documento.',
    'Contrato de Trabajo':'Las partes declaran celebrar el presente contrato de trabajo sujeto a las condiciones particulares consignadas y a la normativa aplicable.',
    'Ficha de Empleado':'La presente ficha resume los datos laborales registrados del funcionario.',
    'Solicitud de Vacaciones':'Por medio de la presente, la persona trabajadora solicita el usufructo de sus vacaciones en las fechas acordadas.',
    'Usufructo de Vacaciones':'Se deja constancia del periodo de vacaciones concedido y efectivamente usufructuado.',
    'Notificación de Preaviso':'Por medio de la presente se comunica formalmente el preaviso correspondiente, sujeto a la revisión del caso concreto.',
    'Renuncia':'La persona trabajadora comunica su decisión de dar por terminada la relación laboral en la fecha indicada.',
    'Comunicación de Despido':'La empresa comunica la terminación de la relación laboral, con sujeción a la revisión de causa, forma y efectos aplicables.'
  };
  function updateDocument(){
    const company=state.companies.find(c=>c.id===$('#docCompany').value)||state.companies[0];
    const emp=state.employees.find(e=>e.id===$('#docEmployee').value)||state.employees[0];
    const title=$('#docFormTitle').textContent;
    $('#paperTitle').textContent=title.toUpperCase();$('#paperCompany').textContent=company?.legalName||'Empresa';$('#paperCompany2').textContent=company?.legalName||'Empresa';$('#paperEmployee').textContent=emp?.name||'Funcionario';$('#paperDate').textContent=$('#docDate').value;$('#paperPosition').textContent=$('#docPosition').value||emp?.position||'—';$('#paperAdmission').textContent=$('#docAdmission').value||emp?.admission||'—';$('#paperSalary').textContent=$('#docSalary').value||fmt(emp?.salary);$('#paperBody').textContent=docBodies[title]||docBodies['Certificado de Trabajo'];$('#paperNotes').textContent=$('#docNotes').value;toast('Vista previa actualizada')
  }
  $('#certificateForm')?.addEventListener('submit',e=>{e.preventDefault();updateDocument();audit('Generación','Documento',$('#docFormTitle').textContent)});
  $$('#docMenu button').forEach(b=>b.onclick=()=>{$$('#docMenu button').forEach(x=>x.classList.toggle('active',x===b));$('#docFormTitle').textContent=b.dataset.doc;updateDocument()});
  $('#docCompany')?.addEventListener('change',updateDocument);$('#docEmployee')?.addEventListener('change',()=>{const e=state.employees.find(x=>x.id===$('#docEmployee').value);if(e){$('#docPosition').value=e.position;$('#docSalary').value=fmt(e.salary);$('#docAdmission').value=e.admission||''}updateDocument()});
  $('#downloadDocBtn')?.addEventListener('click',()=>download(slug($('#docFormTitle').textContent)+'.html','<!doctype html><meta charset="utf-8"><title>'+esc($('#docFormTitle').textContent)+'</title><style>body{font-family:Georgia,serif;max-width:760px;margin:50px auto;line-height:1.8}h2{text-align:center}.signature{text-align:center;margin-top:70px}</style>'+$('#paper').outerHTML,'text/html'));

  $('#legalSearchBtn')?.addEventListener('click',()=>{state.legalQuery=$('#legalInput').value;renderLegal()});
  $('#legalInput')?.addEventListener('input',e=>{state.legalQuery=e.target.value;renderLegal()});
  $('#chatForm')?.addEventListener('submit',e=>{e.preventDefault();const text=$('#chatText').value.trim();if(!text)return;chat(text);$('#chatText').value=''});
  $$('.chat-suggestion').forEach(b=>b.onclick=()=>chat(b.textContent));
  function chat(text){const box=$('#chatMessages');box.insertAdjacentHTML('beforeend',`<div class="bubble user">${esc(text)}</div>`);const q=text.toLowerCase();let answer='Puedo ayudarte a ubicar esa tarea dentro de Digit Laboral. Para una conclusión jurídica o un cálculo definitivo, revisá el caso y los parámetros vigentes.';if(q.includes('funcionario')||q.includes('empleado'))answer='Entrá a Inicio → Mantenimientos → Empleados. Allí podés elegir la empresa, cargar cédula, cargo, ingreso, salario e IPS.';else if(q.includes('salario')||q.includes('neto'))answer='Usá Calculadoras → Salario mensual. Cargá el bruto, otros ingresos y descuentos. El sistema muestra una estimación y permite luego registrar el cálculo formal.';else if(q.includes('constancia')||q.includes('certificado'))answer='Entrá a Inicio → Certificados. Elegí el modelo en la columna izquierda, completá los datos y revisá la vista previa antes de imprimir o descargar.';else if(q.includes('solicitud')||q.includes('trámite'))answer='Entrá a Trámites. Allí se ven las solicitudes de empresas vinculadas y sus estados: pendiente, en revisión o resuelta.';else if(q.includes('vacacion'))answer='La gestión se encuentra en Cálculo → Vacaciones; los documentos relacionados se emiten desde Certificados.';setTimeout(()=>{box.insertAdjacentHTML('beforeend',`<div class="bubble bot">${esc(answer)}</div>`);box.scrollTop=box.scrollHeight},300);box.scrollTop=box.scrollHeight}
  $('#globalSearch')?.addEventListener('keydown',e=>{if(e.key!=='Enter')return;const q=e.target.value.toLowerCase();const map=[['empresa','mantenimientos'],['funcionario','mantenimientos'],['empleado','mantenimientos'],['certificado','certificados'],['contrato','certificados'],['salario','calculadoras'],['aguinaldo','calculadoras'],['informe','informes'],['solicitud','tramites'],['código','codigo'],['artículo','codigo'],['usuario','admin']];const found=map.find(([k])=>q.includes(k));showView(found?found[1]:'inicio');toast(found?'Sección encontrada':'No se encontró una coincidencia exacta')});

  function openSimpleModal(title,body,onSave,saveLabel='Guardar'){$('#modalRoot').innerHTML=`<div class="modal-backdrop"><div class="modal"><div class="modal-head"><h2>${esc(title)}</h2><button class="modal-close" id="modalClose">×</button></div>${body}<div class="modal-actions"><button class="btn secondary" id="modalCancel">Cancelar</button><button class="btn primary" id="modalSave">${esc(saveLabel)}</button></div></div></div>`;$('#modalClose').onclick=closeModal;$('#modalCancel').onclick=closeModal;$('#modalSave').onclick=()=>{onSave?.();closeModal()};$('.modal-backdrop').onclick=e=>{if(e.target.classList.contains('modal-backdrop'))closeModal()}}
  function closeModal(){$('#modalRoot').innerHTML=''}
  function download(name,content,type){const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([content],{type:type||'text/plain'}));a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}
  function slug(s){return s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'')}
  function renderAll(){renderCompanies();renderEmployees();renderRequests();renderAudit();renderLegal();updateDocument()}
  renderAll();calculate();
})();
