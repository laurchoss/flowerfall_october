"""Исправление сохранённых отчётов в отдельной пробной копии SQLite."""
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from daily_reports import BUSINESS_HEADERS, business_values, parse_report
from report_wizard import STEPS, validate

EDIT_FIELDS = [key for key in BUSINESS_HEADERS if key not in ('Число', 'Выручка')]


def init_tables(db):
    db.executescript('''
        CREATE TABLE IF NOT EXISTS test_reports(date TEXT PRIMARY KEY,data TEXT NOT NULL,version INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS correction_drafts(chat INTEGER PRIMARY KEY,data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS test_report_history(id INTEGER PRIMARY KEY, date TEXT, field TEXT,
            old_value TEXT,new_value TEXT,actor TEXT,changed_at TEXT,old_revenue TEXT,new_revenue TEXT);
    ''')


def seed_test_reports(db, directory):
    if db.execute("SELECT value FROM settings WHERE key='test_seeded'").fetchone():
        return
    baseline = Path(directory)/'october_sheet_baseline.json'
    reports = Path(directory)/'daily_reports_october_2026.json'
    rows = {}
    if baseline.exists():
        for item in json.loads(baseline.read_text()):
            row = dict.fromkeys(BUSINESS_HEADERS, '')
            row.update(item)
            rows[item['Число']] = row
    if reports.exists():
        for entry in json.loads(reports.read_text()):
            item = business_values(entry,'Б/Н')
            rows.setdefault(item['Число'],dict.fromkeys(BUSINESS_HEADERS,''))
            rows[item['Число']].update({k:v for k,v in item.items() if v!=''})
    for row in rows.values():
        row = {k:str(v) for k,v in row.items()}
        db.execute('INSERT OR IGNORE INTO test_reports(date,data) VALUES(?,?)', (row['Число'],json.dumps(row,ensure_ascii=False)))
    db.execute("INSERT OR REPLACE INTO settings VALUES('test_seeded','1')")


def save_test_report(db, text):
    entry = parse_report(text)
    row = business_values(entry,'Б/Н')
    key = row['Число']
    existing = db.execute('SELECT data FROM test_reports WHERE date=?',(key,)).fetchone()
    if existing:
        if json.loads(existing[0]) != row:
            raise ValueError('В пробной копии уже есть отчёт за эту дату. Используйте «Исправить отчёт».')
    else:
        db.execute('INSERT INTO test_reports(date,data) VALUES(?,?)',(key,json.dumps(row,ensure_ascii=False)))
    return 'Тестовый отчёт сохранён в пробной копии. В рабочие таблицы НЕ записан.\nДля проверки правок нажмите «Исправить отчёт».'


def get_correction(db,chat):
    row=db.execute('SELECT data FROM correction_drafts WHERE chat=?',(chat,)).fetchone()
    return json.loads(row[0]) if row else None


def put_correction(db,chat,draft):
    db.execute('INSERT OR REPLACE INTO correction_drafts VALUES(?,?)',(chat,json.dumps(draft,ensure_ascii=False)))


def amount_equal(a,b):
    try:
        return Decimal(a)==Decimal(b)
    except Exception:
        return a==b


def change_preview(draft):
    text = ('ПРОБНАЯ КОПИЯ\n' + draft['date'] + '\n' + draft['field'] + '\n'
            + 'Было: ' + (draft['old'] or 'не указано') + '\nСтанет: ' + (draft['new'] or 'не указано'))
    if draft['field'] in ('Наличка','Б/Н','Перевод'):
        text += '\nВыручка: ' + draft['old_revenue'] + ' → ' + draft['new_revenue']
    return text + '\n\nПодтвердить изменение только в пробной копии?'


def advance_correction(db,chat,text,actor):
    draft=get_correction(db,chat)
    if text in ('Исправить отчёт','/editreport'):
        draft={'step':'date'}
        put_correction(db,chat,draft)
        return 'ПРОБНАЯ КОПИЯ\nВыберите дату отчёта.'
    if not draft:
        return None
    if text in ('Отмена','/cancel'):
        db.execute('DELETE FROM correction_drafts WHERE chat=?',(chat,))
        return 'Исправление отменено. Ничего не изменено.'
    if text=='Назад':
        draft['step']={'field':'date','value':'field','confirm':'value'}.get(draft['step'],'date')
    elif draft['step']=='date':
        try:
            key=validate(0,text).replace('.','/')
        except ValueError as error:
            return str(error)
        row=db.execute('SELECT data,version FROM test_reports WHERE date=?',(key,)).fetchone()
        if not row:
            return 'За эту дату нет отчёта в пробной копии. Выберите другую дату.'
        draft.update(step='field',date=key,original=json.loads(row[0]),version=row[1])
    elif draft['step']=='field':
        if text=='История исправлений':
            changes=db.execute('SELECT field,old_value,new_value,changed_at FROM test_report_history WHERE date=? ORDER BY id DESC LIMIT 10',(draft['date'],)).fetchall()
            if not changes: return 'В пробной копии за '+draft['date']+' пока нет исправлений.'
            return 'История пробных исправлений за '+draft['date']+':\n'+'\n'.join(f'{field}: {old or "пусто"} → {new or "пусто"}' for field,old,new,at in changes)
        if text not in EDIT_FIELDS:
            return 'Выберите поле кнопкой. Выручка пересчитывается при изменении оплат.'
        draft.update(step='value',field=text,old=str(draft['original'].get(text,'')))
    elif draft['step']=='value':
        field=draft['field']
        try:
            index=[key for key,_ in STEPS].index(field)
            new=validate(index,text)
        except ValueError as error:
            return str(error)
        if amount_equal(draft['old'],new):
            return 'Это значение уже записано. Введите другое или нажмите «Отмена».'
        changed=dict(draft['original'])
        changed[field]=new
        old_revenue=str(changed.get('Выручка',''))
        if field in ('Наличка','Б/Н','Перевод'):
            changed['Выручка']=format(sum((Decimal(changed.get(k) or 0) for k in ('Наличка','Б/Н','Перевод')),Decimal(0)),'.2f')
        draft.update(step='confirm',new=new,changed=changed,old_revenue=old_revenue,new_revenue=str(changed.get('Выручка','')))
    elif draft['step']=='confirm':
        if text!='Подтвердить':
            return change_preview(draft)
        current=db.execute('SELECT version FROM test_reports WHERE date=?',(draft['date'],)).fetchone()
        if not current or current[0]!=draft['version']:
            db.execute('DELETE FROM correction_drafts WHERE chat=?',(chat,))
            return 'Отчёт уже изменился. Выберите дату заново — правка не применена.'
        db.execute('UPDATE test_reports SET data=?,version=version+1 WHERE date=?',
                   (json.dumps(draft['changed'],ensure_ascii=False),draft['date']))
        db.execute('INSERT INTO test_report_history(date,field,old_value,new_value,actor,changed_at,old_revenue,new_revenue) VALUES(?,?,?,?,?,?,?,?)',
                   (draft['date'],draft['field'],draft['old'],draft['new'],str(actor),datetime.now(timezone.utc).isoformat(),draft['old_revenue'],draft['new_revenue']))
        db.execute('DELETE FROM correction_drafts WHERE chat=?',(chat,))
        return 'Изменено только в пробной копии. История сохранена, дубль отчёта не создан.\nРабочие таблицы не изменены.'
    put_correction(db,chat,draft)
    if draft['step']=='date': return 'Выберите дату отчёта.'
    if draft['step']=='field': return 'Дата: '+draft['date']+'\nЧто исправить?'
    if draft['step']=='value': return draft['field']+'\nСейчас: '+(draft['old'] or 'не указано')+'\nВведите новое значение.'
    return change_preview(draft)


def correction_keyboard(db,chat):
    draft=get_correction(db,chat)
    if not draft: return None
    step=draft['step']
    if step=='date':
        keys=[r[0] for r in db.execute('SELECT date FROM test_reports ORDER BY date')]
        buttons=[keys[i:i+4] for i in range(0,len(keys),4)]+[['Отмена']]
    elif step=='field':
        buttons=[EDIT_FIELDS[i:i+2] for i in range(0,len(EDIT_FIELDS),2)]+[['История исправлений'],['Назад','Отмена']]
    elif step=='value':
        from report_wizard import EMPLOYEE_NAMES
        buttons=[EMPLOYEE_NAMES] if draft['field']=='Имя' else [['0']]
        buttons += [['Назад','Отмена']]
    else:
        buttons=[['Подтвердить'],['Назад','Отмена']]
    return {'keyboard':[[{'text':t} for t in row] for row in buttons],'resize_keyboard':True}
