"""Telegram: личные сообщения → CSV. Только стандартная библиотека Python."""
import argparse
import csv
from decimal import Decimal
import fcntl
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from sales import HEADERS, parse_sale, read_rows, save_rows
from daily_reports import record, export_business
from google_sync import sync_report
from report_wizard import advance, get_draft, put_draft, keyboard
from report_corrections import (init_tables, seed_test_reports, save_test_report,
                                get_correction, advance_correction, correction_keyboard)

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / 'bot_config.json'
REPORT_TEMPLATE = ('Дата: ДД.10\nИмя: \nЗП: \nВыручка: \nНаличка: \nБ/Н: \n'
                   'Перевод: \nОстаток в кассе: \nСписание: \nЗакупка: \nПрочие расходы: ')
TEMPLATE_TIP = ('Скопируйте заготовку ниже, замените ДД на число и впишите суммы после двоеточий. '
                'Если сумма равна нулю — напишите 0. Если данных нет — оставьте поле пустым. '
                'Выручка складывается из налички, Б/Н и переводов.')
REPORT_KEYBOARD = {'keyboard': [[{'text': 'Отчёт за день'}, {'text': 'Исправить отчёт'}]],
                   'resize_keyboard': True, 'is_persistent': True}
HELP = ('Перешлите текст продажи: 12.10 розы 11шт итого 1500 WhatsApp\n'
        '«итого» — стоимость всей продажи; без этого слова — цена за штуку.\n'
        'Каналы: WhatsApp, сайт, офлайн. Примечание — после ;\n'
        'Дневной отчёт с полем «Выручка:» запишу в отдельную таблицу дневных итогов.')
DAILY_HELP = ('Перешлите отчёт за день в обычном виде:\n19.10\nИмя: Боня\nЗП: 5000\nВыручка: 10150\nБ/н: 10150\nСписание: 1913\nОстаток в кассе: 4000\n\n'
              'Выручка = наличка + Б/Н + перевод.\n'
              'Неуказанные имя, ЗП и расходы оставляю пустыми.')
DAILY_HELP += '\nНажмите «Отчёт за день» — задам вопросы по одному. /cancel — отменить черновик.'


class ApiError(Exception):
    pass


def private_reply(text):
    """Скрываем месячные итоги также в сохранённых старых подтверждениях."""
    return re.split(r'(?:Итого за октябрь|Сумма отдельных продаж за октябрь|Выручка по дневным отчётам за октябрь|Выручка за октябрь по локальной)', text)[0].strip() or 'Отчёт обработан.'


def message_format(text):
    match = re.search(r'^Шаг \d+ из \d+$', text, re.M)
    if not match:
        return {'text': text}
    # Telegram считает смещения в UTF-16. Остальной текст остаётся буквальным.
    return {'text': text, 'entities': [{'type': 'bold',
            'offset': len(text[:match.start()].encode('utf-16-le'))//2,
            'length': len(match.group().encode('utf-16-le'))//2}]}


class Telegram:
    def __init__(self, token):
        self.token = token

    def call(self, method, **payload):
        request = Request(f'https://api.telegram.org/bot{self.token}/{method}',
                          data=json.dumps(payload).encode(),
                          headers={'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=45) as response:
                data = json.load(response)
        except HTTPError as error:
            # URL содержит токен: не выводим исключение urllib или traceback.
            raise ApiError(f'Telegram HTTP {error.code}') from None
        except (URLError, TimeoutError, OSError, ValueError):
            raise ApiError('Нет связи с Telegram или некорректный ответ') from None
        if not data.get('ok'):
            raise ApiError(f'Telegram отклонил запрос (код {data.get("error_code", "?")})')
        return data['result']


class Store:
    def __init__(self, directory=ROOT, mode='sales', config=None):
        self.directory = Path(directory)
        self.mode = mode
        self.config = config or {}
        self.csv_path = self.directory / 'sales_october_2026.csv'
        self.db = sqlite3.connect(self.directory / 'telegram_state.sqlite3')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS sales(id TEXT PRIMARY KEY,row_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS updates(id INTEGER PRIMARY KEY, reply TEXT);
            CREATE TABLE IF NOT EXISTS report_sync(id TEXT PRIMARY KEY,entry_json TEXT,chat INTEGER,status TEXT);
            CREATE TABLE IF NOT EXISTS drafts(chat INTEGER PRIMARY KEY,data TEXT NOT NULL);
        ''')
        init_tables(self.db)
        # Импортируем существующие реальные продажи ровно один раз.
        with self.db:
            if not self.setting('imported'):
                for i, row in enumerate(read_rows(self.csv_path)):
                    self.db.execute('INSERT INTO sales VALUES(?,?)', (f'initial:{i}', json.dumps(row, ensure_ascii=False)))
                self.set_setting('imported', '1')
        self.export()

    def setting(self, key):
        result = self.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return result[0] if result else None

    def set_setting(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, str(value)))

    def total(self):
        return sum((Decimal(json.loads(row[0])[4]) for row in self.db.execute('SELECT row_json FROM sales')), Decimal(0))

    def export(self):
        if self.setting('test_mode') == '1':
            return
        rows = [json.loads(row[0]) for row in self.db.execute('SELECT row_json FROM sales ORDER BY rowid')]
        rows.sort(key=lambda row: int(row[0][:2]))
        save_rows(self.csv_path, rows)

    def save_wizard(self, text):
        if self.setting('test_mode') == '1':
            seed_test_reports(self.db,self.directory)
            return save_test_report(self.db,text)
        report = record(text, self.directory)
        export_business(self.directory, self.config.get('qr_target', 'Б/Н'))
        return 'Записал отчёт за ' + report['отчёт']['данные']['Дата'] + ' в локальную таблицу.\nGoogle-таблица остаётся без изменений.'

    def start_test(self, chat):
        with self.db:
            if self.setting('test_mode') != '1':
                self.set_setting('test_original_draft', json.dumps(get_draft(self.db, chat), ensure_ascii=False))
            self.set_setting('test_mode', '1')
            put_draft(self.db, chat, {'step':0, 'values':{}, 'editing':False})

    def end_test(self, chat):
        with self.db:
            original = json.loads(self.setting('test_original_draft') or 'null')
            self.db.execute('DELETE FROM drafts WHERE chat=?', (chat,))
            if original:
                put_draft(self.db, chat, original)
            self.set_setting('test_mode', '0')
            self.db.execute('DELETE FROM settings WHERE key=?', ('test_original_draft',))

    def reply_keyboard(self,chat):
        return correction_keyboard(self.db,chat) or keyboard(self.db,chat,REPORT_KEYBOARD)

    def handle(self, update, pairing_code):
        message = update.get('message')
        if not message or message.get('chat', {}).get('type') != 'private':
            return None
        update_id = update['update_id']
        chat = message['chat']['id']
        user_id = str(message.get('from', {}).get('id', ''))
        text = (message.get('text') or message.get('caption') or '').strip()
        if text.split('@')[0] == '/total' or text == 'Итог октября':
            return chat, 'Итоги месяца в Telegram не показываются.'
        old = self.db.execute('SELECT reply FROM updates WHERE id=?', (update_id,)).fetchone()
        if old:
            self.export()  # Восстановление CSV после сбоя между commit и export.
            return chat, private_reply(old[0])
        with self.db:
            owner = self.setting('owner')
            if owner is None:
                if text == '/start ' + pairing_code and user_id:
                    self.set_setting('owner', user_id)
                    reply = 'Доступ подключён.\n' + (DAILY_HELP if self.mode == 'daily' else HELP)
                else:
                    reply = 'Для подключения отправьте /start и код из инструкции запуска владельца.'
            elif owner != user_id:
                reply = 'Доступ разрешён только владельцу.'
            elif text in ('Исправить отчёт','/editreport') or get_correction(self.db,chat):
                if self.setting('test_mode') != '1':
                    reply = 'Исправление сохранённых отчётов пока доступно только в пробном режиме.'
                else:
                    seed_test_reports(self.db,self.directory)
                    reply = advance_correction(self.db,chat,text,user_id)
            elif self.mode == 'daily' and (text in ('Отчёт за день', '/report', 'Отмена', '/cancel') or
                                          (get_draft(self.db, chat) and text not in ('/help', '/start'))):
                reply = advance(self.db, chat, text, self.save_wizard)
            elif text.split('@')[0] in ('/start', '/help'):
                reply = DAILY_HELP if self.mode == 'daily' else HELP
            elif text.split('@')[0] == '/template' or text == 'Шаблон отчёта':
                reply = REPORT_TEMPLATE
            elif not text:
                reply = 'Нужен текст продажи или фотография с текстовой подписью. Голосовые и текст внутри фото пока не распознаются.'
            elif self.setting('test_mode') == '1':
                reply = 'Тестовый режим: сообщение не записано в таблицы. Нажмите «Отчёт за день», чтобы пройти вопросы.'
            else:
                try:
                    if self.mode == 'daily' or re.search(r'^Выручка\s*:', text, re.I | re.M):
                        report = record(text, self.directory)
                        if self.mode == 'daily':
                            summary = export_business(self.directory, self.config.get('qr_target'))
                            self.db.execute('INSERT OR IGNORE INTO report_sync VALUES(?,?,?,?)',
                                            (report['отчёт']['id'], json.dumps(report['отчёт'], ensure_ascii=False), chat, 'pending'))
                            reply = 'Записал дневной отчёт за ' + report['отчёт']['данные']['Дата'] + ' в локальную таблицу.'
                            if summary['ожидают_уточнения']:
                                reply += '\nЕсть отчёты, ожидающие уточнения: они пока не включены в итог.'
                            if Decimal(report['отчёт']['разница_с_выручкой']) != 0:
                                reply += '\nВнимание: указанная выручка отличается от суммы оплат на ' + report['отчёт']['разница_с_выручкой'] + ' ₽. Отчёт сохранён в архиве, но строка таблицы и итог ожидают уточнения.'
                            if not self.config.get('google_webapp_url'):
                                reply += '\nGoogle ещё не подключён: автоматическая запись в него ожидает настройки.'
                            else:
                                reply += '\nПодтверждение записи в Google пришлю отдельно.'
                        else:
                            reply = 'Записал дневной отчёт за ' + report['отчёт']['данные']['Дата'] + '.'
                    else:
                        row = parse_sale(text)
                        # Повторная доставка одного update не создаёт новую продажу.
                        origin = message.get('forward_origin', {})
                        if origin.get('type') == 'channel':
                            key = f"forward:{origin['chat']['id']}:{origin['message_id']}"
                        else:
                            key = f'message:{chat}:{message["message_id"]}'
                        exists = self.db.execute('SELECT 1 FROM sales WHERE id=?', (key,)).fetchone()
                        if not exists:
                            self.db.execute('INSERT INTO sales VALUES(?,?)', (key, json.dumps(row, ensure_ascii=False)))
                        reply = ('Уже записано' if exists else 'Записал') + f': {row[1]}, {row[2]} шт., {row[4]} ₽.'
                except ValueError as error:
                    reply = 'Не записал: ' + str(error)
            self.db.execute('INSERT INTO updates VALUES(?,?)', (update_id, reply))
        self.export()
        return chat, reply

    def flush_sync(self):
        if self.setting('test_mode') == '1':
            return []
        if not self.config.get('google_webapp_url'):
            return []
        notices = []
        for key, raw, chat in self.db.execute("SELECT id,entry_json,chat FROM report_sync WHERE status='pending'").fetchall():
            try:
                result = sync_report(json.loads(raw), self.config)
            except ValueError as error:
                result = {'ok':False, 'message':str(error)}
            if result.get('ok'):
                notices.append((chat, 'Отчёт за ' + json.loads(raw)['данные']['Дата'] + ': запись в Google-таблицу подтверждена.'))
                with self.db:
                    self.db.execute("UPDATE report_sync SET status='done' WHERE id=?", (key,))
            elif not result.get('pending'):
                notices.append((chat, 'Нужна проверка Google-таблицы: ' + result.get('message', 'нет подтверждения')))
                with self.db:
                    self.db.execute("UPDATE report_sync SET status='review' WHERE id=?", (key,))
        return notices


def load_config():
    config = json.loads(CONFIG.read_text())
    token = config.get('token', '').strip()
    if not re.fullmatch(r'\d+:[A-Za-z0-9_-]{20,}', token):
        raise ValueError('В bot_config.json пока нет действительного токена. Добавьте токен BotFather в поле token.')
    if not config.get('pairing_code'):
        config['pairing_code'] = secrets.token_urlsafe(12)
        CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2))
    CONFIG.chmod(0o600)
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    try:
        config = load_config()
        api = Telegram(config['token'])
        me = api.call('getMe')
        webhook = api.call('getWebhookInfo')
        if webhook.get('url'):
            raise ValueError('У бота уже подключён webhook. Используйте отдельного нового бота; существующее подключение не менялось.')
        print('Бот: @' + me['username'], flush=True)
        print('В личке боту отправьте: /start ' + config['pairing_code'], flush=True)
        if args.check:
            return
        with (ROOT / '.telegram_bot.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Бот уже запущен') from None
            store = Store(mode=config.get('mode', 'daily'), config=config)
            backoff = 2
            while True:
                try:
                    offset = int(store.setting('offset') or 0)
                    updates = api.call('getUpdates', offset=offset, timeout=25, allowed_updates=['message'])
                    for update in updates:
                        result = store.handle(update, config['pairing_code'])
                        if result:
                            api.call('sendMessage', chat_id=result[0], **message_format(result[1]), reply_markup=store.reply_keyboard(result[0]))
                        with store.db:
                            store.set_setting('offset', update['update_id']+1)
                    for chat, text in store.flush_sync():
                        api.call('sendMessage', chat_id=chat, text=text)
                    backoff = 2
                except ApiError as error:
                    logging.warning('%s; повтор через %s с.', error, backoff)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 60)
    except (ValueError, OSError) as error:
        # Не печатаем содержимое конфигурации, исключения JSON и токен.
        print('Не запущен: ' + (str(error) if isinstance(error, ValueError) and not isinstance(error, json.JSONDecodeError) else 'Проверьте доступ к файлам и формат конфигурации.'))
        return 1
    except ApiError as error:
        print('Не запущен: ' + str(error))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
