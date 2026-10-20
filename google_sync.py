"""Постоянное соединение бота с Google через Apps Script Web App."""
import json
from urllib.request import Request, urlopen
from urllib.error import URLError
from daily_reports import business_values


def sync_report(entry, config):
    from decimal import Decimal
    if Decimal(entry['разница_с_выручкой']) != 0:
        return {'ok': False, 'message': 'Выручка отличается от суммы оплат. Нужна проверка владельца.'}
    url = config.get('google_webapp_url', '')
    secret = config.get('google_sync_secret', '')
    if not url or not secret:
        return {'ok': False, 'pending': True,
                'message': 'Google-таблица ещё не подключена. Отчёт сохранён локально; синхронизация ожидает подключения.'}
    if not url.startswith('https://script.google.com/macros/s/') or not url.endswith('/exec'):
        raise ValueError('Некорректный адрес подключения Google')
    values = business_values(entry, config.get('qr_target'))
    values = {key: (float(value) if key not in ('Число', 'Имя') and value != '' else value)
              for key, value in values.items()}
    payload = {'secret': secret, 'report_id': entry['id'], 'values': values}
    request = Request(url, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except (URLError, OSError, ValueError):
        return {'ok': False, 'pending': True, 'message': 'Нет подтверждения Google. Отчёт сохранён, запись будет повторена.'}
    return result
