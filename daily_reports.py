"""Разбор ежедневных отчётов и выгрузка с заголовками владельца."""
import argparse
import csv
import hashlib
import io
import json
import re
from datetime import date
from decimal import Decimal
from pathlib import Path
import fcntl
import os
import tempfile

ROOT = Path(__file__).resolve().parent
FIELDS = ['Дата', 'Имя', 'Зарплата', 'Выручка', 'Наличка', 'Безнал', 'QR-код',
          'Перевод', 'Остаток в кассе', 'Списание', 'Закупка', 'Прочие расходы',
          'Начало смены', 'Конец смены', 'Длительность смены', 'Примечание']
LABELS = {'выручка': 'Выручка', 'qr-код': 'QR-код', 'qr': 'QR-код',
          'б/н': 'Безнал', 'безнал': 'Безнал', 'нал': 'Наличка', 'наличка': 'Наличка',
          'списание': 'Списание', 'остаток в кассе': 'Остаток в кассе',
          'зарплата': 'Зарплата', 'зп': 'Зарплата', 'закупка': 'Закупка',
          'перевод': 'Перевод', 'прочие расходы': 'Прочие расходы'}
BUSINESS_HEADERS = ['Число', 'Имя', 'ЗП', 'Выручка', 'Наличка', 'Б/Н', 'Перевод',
                    'Остаток в кассе', 'Списание', 'Закупка', 'Прочие расходы']


def business_values(entry, qr_target=None):
    """Пустые поля не выдумываем. QR требует явного выбора владельца."""
    data = entry['данные']
    mapping = {'Число': 'Дата', 'ЗП': 'Зарплата', 'Б/Н': 'Безнал'}
    values = {key: data[mapping.get(key, key)] for key in BUSINESS_HEADERS}
    qr = data['QR-код']
    if qr != '':
        if qr_target not in ('Б/Н', 'Перевод'):
            raise ValueError('Нужно выбрать, куда записывать QR-код: Б/Н или Перевод. Отчёт сохранён в архиве.')
        base = values[qr_target]
        values[qr_target] = format(Decimal(base or 0) + Decimal(qr), '.2f')
    if any(values[key] != '' for key in ('Наличка', 'Б/Н', 'Перевод')):
        values['Выручка'] = format(sum((Decimal(values[key] or 0) for key in ('Наличка', 'Б/Н', 'Перевод')), Decimal(0)), '.2f')
    values['Число'] = data['Дата'][:5].replace('.', '/')
    return values


def export_business(directory=ROOT, qr_target=None):
    directory = Path(directory)
    source = directory / 'daily_reports_october_2026.json'
    entries = json.loads(source.read_text()) if source.exists() else []
    seed_file = directory / 'october_sheet_baseline.json'
    baseline = json.loads(seed_file.read_text()) if seed_file.exists() else []
    days = {day: dict.fromkeys(BUSINESS_HEADERS, '') for day in range(1, 32)}
    for day, row in days.items():
        row['Число'] = f'{day:02d}/10'
    for row in baseline:
        day = int(row['Число'][:2])
        days[day].update(row)
    pending = []
    for entry in entries:
        try:
            if Decimal(entry['разница_с_выручкой']) != 0:
                raise ValueError('Выручка отличается от суммы оплат на ' + entry['разница_с_выручкой'] + ' ₽. Ожидает уточнения.')
            values = business_values(entry, qr_target)
            day = int(values['Число'][:2])
            conflicts = [key for key, value in values.items() if key != 'Число' and value != '' and days[day][key] != ''
                         and str(days[day][key]).strip() != str(value).strip()
                         and not _same_amount(days[day][key], value)]
            if conflicts:
                raise ValueError('Данные отличаются от исходной таблицы: ' + ', '.join(conflicts))
            days[day].update({key: value for key, value in values.items() if value != ''})
        except ValueError as error:
            pending.append({'дата': entry['данные']['Дата'], 'причина': str(error)})
    buffer = io.StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=BUSINESS_HEADERS, delimiter=';')
    writer.writeheader()
    writer.writerows(days.values())
    path = directory / 'finance_october_2026.csv'
    atomic_text(path, '\ufeff' + buffer.getvalue())
    return {'таблица': str(path), 'ожидают_уточнения': pending,
            'итого': format(sum((Decimal(row['Выручка']) for row in days.values() if row['Выручка'] != ''), Decimal(0)), '.2f')}


def _same_amount(left, right):
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except Exception:
        return False


def parse_report(text):
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        raise ValueError('Пустой отчёт')
    match = re.fullmatch(r'(?:дата\s*[:\-–—]?\s*)?(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?\s*', lines[0], re.I)
    if not match:
        raise ValueError('Первая строка должна содержать дату: 19.10')
    day, month, year = match.groups()
    dt = date(int(year or 2026), int(month), int(day))
    if dt.year != 2026 or dt.month != 10:
        raise ValueError('Принимаются отчёты за октябрь 2026')
    row = dict.fromkeys(FIELDS, '')
    row['Дата'] = dt.strftime('%d.%m.%Y')
    notes = []
    for line in lines[1:]:
        empty_label = re.fullmatch(r'(.+?)\s*:\s*', line)
        if empty_label and (empty_label.group(1).lower().strip() in LABELS or empty_label.group(1).lower().strip() in ('имя', 'сотрудник')):
            continue
        name = re.fullmatch(r'(?:Имя|Сотрудник)\s*[:\-–—]?\s+(.+)|(?:Имя|Сотрудник)\s*[:\-–—]\s*(.+)', line, re.I)
        if name:
            if row['Имя']:
                raise ValueError('Имя указано дважды')
            row['Имя'] = next(group for group in name.groups() if group is not None).strip()
            continue
        shift = re.fullmatch(r'Был[аи]?\s+с\s+(\d{1,2})(?::(\d{2}))?\s+до\s+(\d{1,2})(?::(\d{2}))?', line, re.I)
        if shift:
            h1, m1, h2, m2 = [int(x or 0) for x in shift.groups()]
            if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
                raise ValueError('Некорректное время смены')
            minutes = (h2*60+m2-h1*60-m1) % (24*60)
            row.update({'Начало смены': f'{h1:02d}:{m1:02d}', 'Конец смены': f'{h2:02d}:{m2:02d}',
                        'Длительность смены': f'{minutes//60:02d}:{minutes%60:02d}'})
            continue
        normalized = line.replace('‑', '-')
        labels = '|'.join(re.escape(label) for label in sorted(LABELS, key=len, reverse=True))
        field_match = re.fullmatch(r'(' + labels + r')\s*(?:[:\-–—]\s*|\s+)(.+)', normalized, re.I)
        field = LABELS.get(field_match.group(1).lower()) if field_match else None
        if field:
            value = field_match.group(2)
            if row[field] != '':
                raise ValueError(f'Поле «{field}» встречается дважды')
            amount = re.fullmatch(r'\s*(\d+(?:[ \u00a0]\d{3})*(?:[.,]\d{1,2})?)\s*(?:₽|руб(?:\.|лей|ля|ль)?)?\s*(\(.*\))?\s*', value, re.I)
            if not amount:
                raise ValueError(f'Не удалось разобрать сумму в поле «{field}»')
            raw, note = amount.groups()
            row[field] = format(Decimal(raw.replace(' ', '').replace('\u00a0', '').replace(',', '.')), '.2f')
            if note:
                notes.append(f'{field}: {note[1:-1]}')
        else:
            # Неизвестные строки не пропадают: сохраняются вместе с исходником.
            notes.append(line)
    if row['Выручка'] == '':
        raise ValueError('В отчёте не указана выручка')
    row['Примечание'] = '\n'.join(notes)
    payments = ['Наличка', 'Безнал', 'QR-код', 'Перевод']
    known = sum((Decimal(row[key]) for key in payments if row[key] != ''), Decimal(0))
    return {'данные': row, 'сумма_указанных_оплат': format(known, '.2f'),
            'разница_с_выручкой': format(Decimal(row['Выручка'])-known, '.2f'),
            'не_указаны_оплаты': [key for key in payments if row[key] == ''],
            'исходное_сообщение': text,
            'id': hashlib.sha256(text.strip().replace('\r\n', '\n').encode()).hexdigest()}


def atomic_text(path, text):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def record(text, directory=ROOT):
    entry = parse_report(text)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / 'daily_reports_october_2026.json'
    output = directory / 'daily_reports_october_2026.csv'
    with (directory / 'daily_reports.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        entries = json.loads(source.read_text()) if source.exists() else []
        duplicate = any(x['id'] == entry['id'] for x in entries)
        if not duplicate:
            if any(x['данные']['Дата'] == entry['данные']['Дата'] for x in entries):
                raise ValueError('Отчёт за этот день уже есть. Нужна явная корректировка, чтобы не удвоить выручку.')
            entries.append(entry)
            entries.sort(key=lambda x: int(x['данные']['Дата'][:2]))
        atomic_text(source, json.dumps(entries, ensure_ascii=False, indent=2))
        buffer = io.StringIO(newline='')
        writer = csv.DictWriter(buffer, fieldnames=FIELDS, delimiter=';')
        writer.writeheader()
        writer.writerows(x['данные'] for x in entries)
        atomic_text(output, '\ufeff'+buffer.getvalue())
    return {'записано': not duplicate, 'таблица': str(output), 'отчёт': entry,
            'итого_выручка': format(sum((Decimal(x['данные']['Выручка']) for x in entries), Decimal(0)), '.2f')}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(record(args.input.read_text(encoding='utf-8')), ensure_ascii=False, indent=2))
    except (ValueError, OSError) as error:
        parser.exit(2, f'Отчёт не записан: {error}\n')
