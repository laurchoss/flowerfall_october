'use strict';
(() => {
const KEY = 'flowerfall-october-2026-v1';
const $ = id => document.getElementById(id);
const fields = ['Число','Имя','ЗП','Выручка','Наличка','Б/Н','Перевод','Остаток в кассе','Списание','Закупка','Прочие расходы'];
const paymentFields = ['Наличка','Б/Н','QR','Перевод'];
const labels = {'зп':'ЗП','зарплата':'ЗП','выручка':'Выручка','нал':'Наличка','наличка':'Наличка','б/н':'Б/Н','безнал':'Б/Н','qr':'QR','qr-код':'QR','перевод':'Перевод','остаток в кассе':'Остаток в кассе','списание':'Списание','закупка':'Закупка','прочие расходы':'Прочие расходы'};
let state = {version:1,sales:[],reports:[]};
let view = 'sales', pendingDelete = null, timer;
const rub = cents => new Intl.NumberFormat('ru-RU',{style:'currency',currency:'RUB',maximumFractionDigits:2}).format(cents/100);
function notify(message,error=false){$('toast').textContent=message;$('toast').classList.toggle('error',error);$('toast').hidden=false;clearTimeout(timer);timer=setTimeout(()=>$('toast').hidden=true,9000);}
function amount(raw){const value=String(raw).trim().replace(/[ \u00a0]/g,'').replace(',','.');if(!/^\d+(?:\.\d{1,2})?$/.test(value))throw Error('Сумма должна быть положительным числом, максимум 2 знака после запятой.');const n=Math.round(Number(value)*100);if(!Number.isSafeInteger(n)||n>99999999900)throw Error('Сумма слишком большая.');return n;}
function validDate(date){if(!/^2026-10-\d{2}$/.test(date)||Number(date.slice(-2))<1||Number(date.slice(-2))>31)throw Error('Выберите дату с 1 по 31 октября 2026.');return date;}
function uuid(){return crypto.randomUUID();}
function validate(data){
 if(!data||data.version!==1||!Array.isArray(data.sales)||!Array.isArray(data.reports)||data.sales.length+data.reports.length>50000)throw Error('Неизвестный формат резервной копии.');
 const ids=new Set();const dates=new Set();
 const cents=v=>Number.isSafeInteger(v)&&v>=0&&v<=99999999900;
 for(const row of [...data.sales,...data.reports]){if(!row||typeof row.id!=='string'||row.id.length>100||ids.has(row.id))throw Error('Некорректные идентификаторы записей.');ids.add(row.id);validDate(row.date);}
 for(const row of data.sales){if(typeof row.item!=='string'||!row.item.trim()||row.item.length>160||!Number.isSafeInteger(row.quantity)||row.quantity<1||row.quantity>100000||!cents(row.amount)||!['сайт','офлайн','WhatsApp'].includes(row.channel)||typeof row.note!=='string'||row.note.length>500)throw Error('Некорректная продажа в копии.');}
 for(const row of data.reports){if(dates.has(row.date))throw Error('Дневная дата повторяется в копии.');dates.add(row.date);if(typeof row.name!=='string'||row.name.length>160||!row.values||!cents(row.values['Выручка'])||!paymentFields.some(k=>row.values[k]!=null)||Object.entries(row.values).some(([k,v])=>!['ЗП','Выручка',...paymentFields,'Остаток в кассе','Списание','Закупка','Прочие расходы'].includes(k)||!cents(v)))throw Error('Некорректный дневной отчёт в копии.');}
 return data;
}
function difference(row){return row.values['Выручка']-paymentFields.reduce((sum,k)=>sum+(row.values[k]||0),0);}
function save(next){validate(next);try{localStorage.setItem(KEY,JSON.stringify(next));}catch{throw Error('Не удалось сохранить: хранилище браузера недоступно или заполнено. Скачайте резервную копию.');}state=next;render();}
function nextState(){return JSON.parse(JSON.stringify(state));}
function parseReport(text){
 if(text.length>10000)throw Error('Отчёт слишком длинный.');
 const lines=text.trim().split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
 const match=(lines.shift()||'').match(/^(?:дата\s*[:\-–—]?\s*)?(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?$/i);
 if(!match||+match[2]!==10||(match[3]&&match[3]!=='2026'))throw Error('Начните отчёт с даты, например: Дата: 21.10');
 const date=validDate(`2026-10-${match[1].padStart(2,'0')}`);let name='';const values={};
 for(const line of lines){const m=line.match(/^(Выручка|Наличка|Нал|Безнал|Б\/Н|QR-код|QR|Перевод|ЗП|Зарплата|Списание|Закупка|Прочие расходы|Остаток в кассе|Имя|Сотрудник)\s*(?:[:\-–—]\s*|\s+)(.*)$/i);if(!m)throw Error('Не удалось разобрать строку: '+line);const label=m[1].trim().toLowerCase();if(['имя','сотрудник'].includes(label)){if(name)throw Error('Имя указано дважды.');name=m[2].trim();if(name.length>160)throw Error('Имя слишком длинное.');continue;}const field=labels[label];if(!field)throw Error('Неизвестное поле: '+m[1]);if(!m[2].trim())continue;if(values[field]!=null)throw Error('Поле повторяется: '+field);values[field]=amount(m[2].replace(/\s*(?:₽|руб\.?|рублей)\s*$/i,''));}
 if(values['Выручка']==null)throw Error('Укажите поле «Выручка».');if(!paymentFields.some(k=>values[k]!=null))throw Error('Укажите хотя бы один способ оплаты.');return {id:uuid(),date,name,values};
}
function cell(row,value){const td=document.createElement('td');td.textContent=value;row.append(td);return td;}
function render(){
 const approved=state.reports.filter(r=>difference(r)===0);
 $('revenue').textContent=rub(approved.reduce((s,r)=>s+r.values['Выручка'],0));
 $('days-count').textContent=`${approved.length} из 31 дней заполнено`;
 $('sales-total').textContent=rub(state.sales.reduce((s,r)=>s+r.amount,0));$('sales-count').textContent=`${state.sales.length} продаж`;
 $('expenses').textContent=rub(approved.reduce((s,r)=>s+['ЗП','Закупка','Прочие расходы'].reduce((a,k)=>a+(r.values[k]||0),0),0));$('pending').textContent=state.reports.length-approved.length;
 $('tab-sales').classList.toggle('selected',view==='sales');$('tab-reports').classList.toggle('selected',view==='reports');$('tab-sales').setAttribute('aria-pressed',view==='sales');$('tab-reports').setAttribute('aria-pressed',view==='reports');
 const headings=view==='sales'?['Дата','Букет / позиция','Кол-во','Сумма','Канал','']:['Дата','Сотрудник','Выручка','Проверка',''];
 $('table-head').replaceChildren();const head=document.createElement('tr');for(const h of headings){const th=document.createElement('th');th.scope='col';th.textContent=h;head.append(th);}$('table-head').append(head);$('table-body').replaceChildren();
 const rows=[...state[view]].sort((a,b)=>a.date.localeCompare(b.date));
 for(const item of rows){const row=document.createElement('tr');cell(row,item.date.slice(-2)+'.10');if(view==='sales'){const detail=cell(row,item.item);detail.title=item.note;cell(row,item.quantity);cell(row,rub(item.amount));cell(row,item.channel);}else{cell(row,item.name||'—');cell(row,rub(item.values['Выручка']));const td=cell(row,'');const badge=document.createElement('span');badge.className='badge'+(difference(item)!==0?' warn':'');badge.textContent=difference(item)===0?'Оплаты совпадают':'Разница '+rub(difference(item));td.append(badge);}const action=cell(row,'');const button=document.createElement('button');button.type='button';button.className='delete';button.textContent='Удалить';button.setAttribute('aria-label','Удалить запись за '+item.date);button.onclick=()=>{pendingDelete={view,id:item.id};$('delete-dialog').showModal();};action.append(button);$('table-body').append(row);}
 $('empty').hidden=rows.length>0;$('table-count').textContent=`${rows.length} записей`;
}
function download(content,name,type){const blob=new Blob([content],{type});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function csvCell(value){let s=String(value??'');if(/^[\s]*[=+\-@]/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"';}
function csv(rows){return '\uFEFF'+rows.map(r=>r.map(csvCell).join(';')).join('\r\n')+'\r\n';}
$('sale-form').onsubmit=e=>{e.preventDefault();try{const f=new FormData(e.target);const next=nextState();next.sales.push({id:uuid(),date:validDate(f.get('date')),item:f.get('item').trim(),quantity:Number(f.get('quantity')),amount:amount(f.get('amount')),channel:f.get('channel'),note:f.get('note').trim()});save(next);view='sales';render();e.target.elements.namedItem('item').value='';e.target.elements.namedItem('amount').value='';e.target.elements.namedItem('note').value='';notify('Продажа сохранена в этом браузере.');}catch(err){notify(err.message,true);}};
$('report-form').onsubmit=e=>{e.preventDefault();try{const report=parseReport($('report-text').value);if(state.reports.some(r=>r.date===report.date))throw Error('Отчёт за эту дату уже существует. Сначала проверьте и удалите старую запись.');const next=nextState();next.reports.push(report);save(next);view='reports';render();notify(difference(report)===0?'Отчёт сохранён. Сумма оплат совпадает с выручкой.':'Отчёт сохранён для проверки. Расхождение: '+rub(difference(report))+'. В сводку он не включён.',difference(report)!==0);$('report-text').value='';}catch(err){notify(err.message,true);}};
$('example').onclick=()=>{$('report-text').value='Дата: 21.10\nИмя: Демо\nВыручка: 5500\nНаличка: 1500\nБ/Н: 3000\nQR: 1000\nПеревод: 0\nЗП: 500\nСписание: 100\nЗакупка: 2000\nПрочие расходы: 0\nОстаток в кассе: 1500';$('report-text').focus();notify('Вставлен вымышленный пример. Сохранение происходит по кнопке ниже.');};
$('tab-sales').onclick=()=>{view='sales';render();};$('tab-reports').onclick=()=>{view='reports';render();};
$('cancel-delete').onclick=()=>{$('delete-dialog').close();pendingDelete=null;};
$('confirm-delete').onclick=()=>{try{if(pendingDelete){const next=nextState();next[pendingDelete.view]=next[pendingDelete.view].filter(r=>r.id!==pendingDelete.id);save(next);pendingDelete=null;$('delete-dialog').close();notify('Запись удалена.');}}catch(err){notify(err.message,true);}};
$('backup').onclick=()=>download(JSON.stringify(state,null,2),'flowerfall-october-2026-backup.json','application/json');
$('restore').onchange=async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>10000000)throw Error('Файл слишком большой.');const data=validate(JSON.parse(await file.text()));const next=nextState();let count=0;for(const key of ['sales','reports'])for(const item of data[key]){if(next[key].some(r=>r.id===item.id))continue;if(key==='reports'&&next.reports.some(r=>r.date===item.date))throw Error('Конфликт дневной даты '+item.date+'. Импорт целиком отменён.');next[key].push(item);count++;}save(next);notify('Восстановлено записей: '+count+'. Существующие записи сохранены.');}catch(err){notify('Импорт не выполнен: '+err.message,true);}finally{e.target.value='';}};
$('export-sales').onclick=()=>download(csv([['Дата','Позиция/букет','Количество','Цена','Сумма','Канал продажи','Примечание'],...[...state.sales].sort((a,b)=>a.date.localeCompare(b.date)).map(r=>[r.date.slice(-2)+'.10.2026',r.item,r.quantity,(r.amount/100/r.quantity).toFixed(2),(r.amount/100).toFixed(2),r.channel,r.note])]),'sales_october_2026.csv','text/csv;charset=utf-8');
$('export-finance').onclick=()=>{const rows=[fields];for(let d=1;d<=31;d++){const day=String(d).padStart(2,'0');const report=state.reports.find(r=>r.date===`2026-10-${day}`&&difference(r)===0);const values=report?{...report.values}:{};if(report&&values.QR!=null)values['Б/Н']=(values['Б/Н']||0)+values.QR;rows.push(fields.map(k=>k==='Число'?day+'/10':k==='Имя'?(report?.name||''):values[k]!=null?(values[k]/100).toFixed(2):''));}download(csv(rows),'finance_october_2026.csv','text/csv;charset=utf-8');notify('Выгружено 31 день. Отчёты с расхождениями исключены.');};
window.addEventListener('storage',e=>{if(e.key===KEY){try{state=e.newValue?validate(JSON.parse(e.newValue)):{version:1,sales:[],reports:[]};render();notify('Данные обновлены из другой вкладки.');}catch{notify('Не удалось прочитать изменения в другой вкладке.',true);}}});
try{const raw=localStorage.getItem(KEY);if(raw)state=validate(JSON.parse(raw));}catch{notify('Сохранённые данные не удалось прочитать. Не очищайте браузер: восстановите корректную копию.',true);}
render();
})();
