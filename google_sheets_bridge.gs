// Код для привязанного к таблице проекта Google Apps Script.
// В свойствах скрипта задайте SYNC_SECRET. Токен Telegram сюда НЕ нужен.
const FILE_ID = PropertiesService.getScriptProperties().getProperty('SPREADSHEET_ID');
const TAB_NAME = PropertiesService.getScriptProperties().getProperty('TAB_NAME') || 'Октябрь 2026';
const HEADERS = ['Число','Имя','ЗП','Выручка','Наличка','Б/Н','Перевод','Остаток в кассе','Списание','Закупка','Прочие расходы'];

function doPost(e) {
  const result = value => ContentService.createTextOutput(JSON.stringify(value)).setMimeType(ContentService.MimeType.JSON);
  const lock = LockService.getScriptLock();
  try {
    const data = JSON.parse(e.postData.contents);
    const secret = PropertiesService.getScriptProperties().getProperty('SYNC_SECRET');
    if (!secret || data.secret !== secret) return result({ok:false,message:'Нет доступа'});
    lock.waitLock(20000);
    const sheet = SpreadsheetApp.openById(FILE_ID).getSheetByName(TAB_NAME);
    if (!sheet || JSON.stringify(sheet.getRange(1,1,1,11).getValues()[0]) !== JSON.stringify(HEADERS)) {
      return result({ok:false,message:'Лист или заголовки изменились. Запись остановлена.'});
    }
    const props = PropertiesService.getScriptProperties();
    if (!/^[a-f0-9]{64}$/.test(data.report_id || '')) return result({ok:false,message:'Нет id отчёта'});
    const doneKey = 'done_' + data.report_id;
    if (props.getProperty(doneKey)) return result({ok:true,message:'Уже записано'});
    const values = data.values;
    if (!/^\d{2}\/10$/.test(values['Число'] || '')) return result({ok:false,message:'Неверная дата'});
    const day = Number(values['Число'].slice(0,2));
    if (day < 1 || day > 31) return result({ok:false,message:'Неверная дата'});
    const dates = sheet.getRange(2,1,Math.min(sheet.getLastRow()-1,100),1).getValues();
    const matches = [];
    dates.forEach((r,i) => {
      const v = r[0];
      if (v instanceof Date) {
        if (v.getFullYear() === 2026 && v.getMonth() === 9 && v.getDate() === day) matches.push(i+2);
      } else if (String(v).trim().replace(/^'/,'') === values['Число']) matches.push(i+2);
    });
    if (matches.length !== 1) return result({ok:false,message:'Не найдена единственная строка даты. Таблица не изменена.'});
    const row = matches[0];
    const range = sheet.getRange(row,2,1,10);
    const current = range.getValues()[0];
    const formulas = range.getFormulas()[0];
    const incoming = HEADERS.slice(1).map(k => values[k] === undefined ? '' : values[k]);
    for (let i=0;i<incoming.length;i++) {
      if (incoming[i] === '') continue;
      if ((i !== 0 && (typeof incoming[i] !== 'number' || !Number.isFinite(incoming[i]) || incoming[i]<0)) ||
          (i === 0 && typeof incoming[i] !== 'string')) return result({ok:false,message:'Некорректный тип суммы или имени'});
      if (current[i] !== '' && current[i] !== incoming[i]) return result({ok:false,message:'В строке уже есть другая сумма или имя. Нужна проверка.'});
      if (formulas[i]) return result({ok:false,message:'В ячейке формула. Нужна проверка перед изменением.'});
    }
    const final = current.map((v,i) => incoming[i] === '' ? (formulas[i] || v) : incoming[i]);
    // Буквальный текст имени не должен интерпретироваться как формула.
    if (typeof final[0] === 'string' && /^[=+\-@]/.test(final[0])) final[0] = "'" + final[0];
    range.setValues([final]);
    SpreadsheetApp.flush();
    const check = range.getValues()[0];
    for(let i=0;i<incoming.length;i++) {
      if(incoming[i] !== '' && check[i] !== incoming[i]) return result({ok:false,message:'Проверка записи не прошла'});
    }
    props.setProperty(doneKey,'1');
    return result({ok:true,message:'Записал в Google-таблицу',row:row});
  } catch(error) {
    return result({ok:false,message:'Ошибка подключения к таблице. Отчёт сохранён у бота.'});
  } finally {
    if(lock.hasLock()) lock.releaseLock();
  }
}
