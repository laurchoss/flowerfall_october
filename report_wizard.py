"""Пошаговый дневной отчёт; черновик хранится в SQLite бота."""
import json
import re
from datetime import date
from decimal import Decimal

EMPLOYEE_NAMES = ['Бону', 'Саша', 'Ксюша']

STEPS = [
    ('Дата', 'За какое число отчёт? Например: 20.10'),
    ('Имя', 'Имя сотрудника?'),
    ('Наличка', 'Сколько получили наличными?'),
    ('Б/Н', 'Сколько по Б/Н?'),
    ('Перевод', 'Сколько получили переводами?'),
    ('ЗП', 'Какая зарплата за смену?'),
    ('Списание', 'На какую сумму списали цветы?'),
    ('Закупка', 'Сколько потратили на закупку?'),
    ('Прочие расходы', 'Какая сумма прочих расходов?'),
    ('Остаток в кассе', 'Сколько осталось в кассе в конце дня?'),
]


def get_draft(db, chat):
    row = db.execute('SELECT data FROM drafts WHERE chat=?', (chat,)).fetchone()
    return json.loads(row[0]) if row else None


def put_draft(db, chat, draft):
    db.execute('INSERT OR REPLACE INTO drafts VALUES(?,?)', (chat, json.dumps(draft, ensure_ascii=False)))


def revenue(values):
    return format(sum((Decimal(values.get(key) or 0) for key in ('Наличка', 'Б/Н', 'Перевод')), Decimal(0)), '.2f')


def report_text(draft):
    values = draft['values']
    return '\n'.join([f'Дата: {values["Дата"]}', f'Имя: {values["Имя"]}',
                      f'Выручка: {revenue(values)}'] +
                     [f'{key}: {values.get(key, "")}' for key, _ in STEPS[2:]])


def preview(draft):
    v = draft['values']
    lines = ['Проверьте отчёт:', f'Дата: {v["Дата"]}', f'Имя: {v["Имя"]}',
             f'ЗП: {v.get("ЗП") or "не указана"}', f'Выручка: {revenue(v)} ₽',
             f'Наличка: {v.get("Наличка")}', f'Б/Н: {v.get("Б/Н")}',
             f'Перевод: {v.get("Перевод")}']
    lines.extend(f'{key}: {v.get(key) or "не указано"}' for key in ('Остаток в кассе', 'Списание', 'Закупка', 'Прочие расходы'))
    return '\n'.join(lines) + '\n\nНажмите «Сохранить» или «Исправить». До сохранения это только черновик.'


def prompt(draft):
    if draft['step'] == 'review':
        return preview(draft)
    if draft['step'] == 'choose':
        return 'Что исправить? Нажмите название поля.'
    index = draft['step']
    label = STEPS[index][0]
    return f'Шаг {index+1} из {len(STEPS)}\n{label}'


def validate(index, text):
    if index == 0:
        match = re.fullmatch(r'(\d{1,2})(?:[./](\d{1,2}))?(?:[./](\d{4}))?', text)
        if not match:
            raise ValueError('Введите дату: 20.10 или просто 20.')
        day, month, year = match.groups()
        date(int(year or 2026), int(month or 10), int(day))
        if int(month or 10) != 10 or int(year or 2026) != 2026:
            raise ValueError('Этот отчёт — за октябрь 2026. Введите дату октября.')
        return f'{int(day):02d}.10'
    if index == 1:
        if not text or len(text) > 80 or '\n' in text or text.startswith('/'):
            raise ValueError('Введите имя одной строкой.')
        return text
    if text == 'Пропустить' and index >= 5:
        return ''
    raw = re.sub(r'\s*(?:₽|руб(?:\.|лей|ля|ль)?)\s*$', '', text, flags=re.I)
    raw = raw.replace(' ', '').replace('\u00a0', '').replace(',', '.')
    if not re.fullmatch(r'\d+(?:\.\d{1,2})?', raw):
        raise ValueError('Введите сумму цифрами, например 3500 или 3500,50. Нулевая сумма — 0.')
    return format(Decimal(raw), '.2f')


def advance(db, chat, text, save):
    draft = get_draft(db, chat)
    if text in ('Отмена', '/cancel'):
        db.execute('DELETE FROM drafts WHERE chat=?', (chat,))
        return 'Заполнение отменено. Отчёт не записан.'
    if text in ('Отчёт за день', '/report'):
        if draft:
            return 'Продолжаем сохранённый черновик.\n' + prompt(draft)
        draft = {'step': 0, 'values': {}, 'editing': False}
        put_draft(db, chat, draft)
        return prompt(draft)
    if not draft:
        return None
    if draft['step'] == 'review':
        if text == 'Сохранить':
            try:
                result = save(report_text(draft))
            except ValueError as error:
                return 'Не сохранил: ' + str(error) + '\nЧерновик сохранён. Нажмите «Исправить» или «Отмена».'
            db.execute('DELETE FROM drafts WHERE chat=?', (chat,))
            return result
        if text == 'Исправить':
            draft['step'] = 'choose'
        else:
            return prompt(draft)
    elif draft['step'] == 'choose':
        if text in ('Назад', 'К отчёту'):
            draft['step'] = 'review'
        elif text in dict(STEPS):
            draft.update(step=[key for key, _ in STEPS].index(text), editing=True)
        else:
            return prompt(draft)
    elif text == 'Назад':
        if draft['editing']:
            draft.update(step='review', editing=False)
        else:
            draft['step'] = max(0, draft['step']-1)
    else:
        index = draft['step']
        try:
            value = validate(index, text)
        except ValueError as error:
            return str(error) + '\n' + prompt(draft)
        draft['values'][STEPS[index][0]] = value
        if draft['editing'] or index == len(STEPS)-1:
            draft.update(step='review', editing=False)
        else:
            draft['step'] += 1
    put_draft(db, chat, draft)
    return prompt(draft)


def keyboard(db, chat, home):
    draft = get_draft(db, chat)
    if not draft:
        return home
    step = draft['step']
    if step == 'review':
        buttons = [['Сохранить', 'Исправить'], ['Отмена']]
    elif step == 'choose':
        keys = [key for key, _ in STEPS]
        buttons = [keys[i:i+2] for i in range(0, len(keys), 2)] + [['К отчёту', 'Отмена']]
    else:
        buttons = ([['0']] if step >= 2 else [])
        if step == 1:
            buttons = [EMPLOYEE_NAMES]
        if step >= 5:
            buttons.append(['Пропустить'])
        buttons.append(['Назад', 'Отмена'])
    return {'keyboard': [[{'text': t} for t in row] for row in buttons], 'resize_keyboard': True}
