#!/usr/bin/env python3
"""Учёт продаж за октябрь. Не требует дополнительных библиотек."""
import argparse
import calendar
import csv
import fcntl
import io
import json
import os
from pathlib import Path
import re
import tempfile
from decimal import Decimal, InvalidOperation

ROOT = Path(__file__).resolve().parent
YEAR = 2026
HEADERS = ['Дата', 'Позиция/букет', 'Количество', 'Цена', 'Сумма', 'Канал продажи', 'Примечание']
CHANNELS = {'whatsapp': 'WhatsApp', 'ватсап': 'WhatsApp', 'ватсапп': 'WhatsApp',
            'сайт': 'сайт', 'офлайн': 'офлайн'}


def money(value):
    return format(value.quantize(Decimal('0.01')), '.2f')


def parse_sale(message):
    text, _, note = message.strip().partition(';')
    date_match = re.match(r'^(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?\s+(.+)$', text)
    if not date_match:
        raise ValueError('Начните с даты, например: 12.10 розы 11шт 1500 WhatsApp')
    day, month, year, body = date_match.groups()
    day, month, year = int(day), int(month), int(year or YEAR)
    if month != 10 or year != YEAR:
        raise ValueError(f'Эта таблица предназначена для октября {YEAR} года.')
    if not 1 <= day <= calendar.monthrange(year, month)[1]:
        raise ValueError('Такой даты не существует.')
    channel_match = re.search(r'\s+(WhatsApp|ватсапп?|сайт|офлайн)\s*$', body, re.I)
    if not channel_match:
        raise ValueError('В конце укажите канал: WhatsApp, сайт или офлайн. Примечание — после ;')
    channel = CHANNELS[channel_match.group(1).lower()]
    body = body[:channel_match.start()].strip()
    match = re.fullmatch(r'(.+?)\s+(\d+)\s*(?:шт\.?|штук|штуки|штука)\s+(?:(итого)\s+)?(\d+(?:[ \u00a0]\d{3})*(?:[.,]\d{1,2})?)\s*(?:₽|руб(?:\.|лей|ля|ль)?)?', body, re.I)
    if not match:
        raise ValueError('Формат: 12.10 розы 11шт 1500 WhatsApp. Для общей цены: 12.10 розы 11шт итого 1500 WhatsApp')
    item, quantity, is_total, raw_price = match.groups()
    quantity = int(quantity)
    if quantity <= 0:
        raise ValueError('Количество должно быть больше нуля.')
    price = Decimal(raw_price.replace(' ', '').replace('\u00a0', '').replace(',', '.'))
    if is_total:
        total = price
        price = (total / quantity).quantize(Decimal('0.01'))
        note = ('Цена за штуку округлена; сумма указана в сообщении. ' + note).strip()
    else:
        total = price * quantity
    return [f'{day:02d}.10.{year}', item.strip(), str(quantity), money(price), money(total), channel, note.strip()]


def read_rows(path):
    if not path.exists():
        return []
    with path.open(encoding='utf-8-sig', newline='') as file:
        reader = csv.reader(file, delimiter=';')
        if next(reader, None) != HEADERS:
            raise ValueError('Заголовки файла отличаются от ожидаемых. Файл не изменён.')
        rows = list(reader)
    for row in rows:
        if len(row) != len(HEADERS):
            raise ValueError('В таблице повреждена строка. Файл не изменён.')
        if not re.fullmatch(r'\d{2}\.10\.2026', row[0]):
            raise ValueError('В таблице найдена дата вне октября 2026. Файл не изменён.')
        Decimal(row[4])
    return rows


def save_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8-sig', newline='',
                                         dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            writer = csv.writer(file, delimiter=';')
            writer.writerow(HEADERS)
            writer.writerows(rows)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def update(path, messages):
    # Сначала разбираем весь пакет: при ошибке ни одна строка не добавится.
    parsed = [parse_sale(message) for message in messages]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + '.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        rows = read_rows(path)
        if parsed or not path.exists():
            rows.extend(parsed)
            rows.sort(key=lambda row: int(row[0][:2]))
            save_rows(path, rows)
        return rows


def main():
    parser = argparse.ArgumentParser(description='Продажи цветочного за октябрь 2026')
    parser.add_argument('messages', nargs='*', help='Сообщения о продажах')
    parser.add_argument('--file', type=Path, default=ROOT / 'sales_october_2026.csv')
    parser.add_argument('--init', action='store_true', help='Создать пустую таблицу, если её нет')
    parser.add_argument('--show', action='store_true', help='Показать строки и итог')
    args = parser.parse_args()
    try:
        if args.messages or args.init:
            rows = update(args.file, args.messages)
        else:
            rows = read_rows(args.file)
        result = {'таблица': str(args.file.resolve()), 'добавлено': len(args.messages),
                  'валюта': 'RUB', 'период': 'Октябрь 2026', 'число_продаж': len(rows),
                  'итого': money(sum((Decimal(row[4]) for row in rows), Decimal(0)))}
        if args.show:
            result['строки'] = [dict(zip(HEADERS, row)) for row in rows]
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, InvalidOperation, OSError) as error:
        parser.exit(2, f'Не удалось записать продажу: {error}\n')


if __name__ == '__main__':
    main()
