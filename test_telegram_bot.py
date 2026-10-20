import json
from pathlib import Path
import tempfile
import unittest
from telegram_bot import Store, REPORT_TEMPLATE


def message(uid, text, user=7, kind='private'):
    return {'update_id': uid, 'message': {'message_id': uid, 'from': {'id': user},
            'chat': {'id': user, 'type': kind}, 'text': text}}


class BotTests(unittest.TestCase):
    def test_template_does_not_write_and_can_be_filled(self):
        from daily_reports import parse_report
        self.store.mode = 'daily'
        for i, command in enumerate(['/template', 'Шаблон отчёта'], 10):
            self.assertEqual(self.store.handle(message(i, command), 'secret')[1], REPORT_TEMPLATE)
        self.assertFalse((Path(self.tmp.name)/'daily_reports_october_2026.json').exists())
        filled = REPORT_TEMPLATE.replace('ДД', '20').replace('Имя: ', 'Имя: Боня').replace('Выручка: ', 'Выручка: 1000').replace('Наличка: ', 'Наличка: 1000')
        data = parse_report(filled)['данные']
        self.assertEqual(data['Выручка'], '1000.00')
        self.assertEqual(data['Зарплата'], '')
        self.assertEqual(data['Примечание'], '')

    def test_daily_mode_with_google_pending(self):
        self.store.mode = 'daily'
        self.store.config = {'qr_target': 'Б/Н'}
        report = '19.10\nВыручка: 10150\nQR-код: 5200\nБ/н: 4950'
        reply = self.store.handle(message(2, report), 'secret')[1]
        self.assertIn('Google ещё не подключён', reply)
        self.assertNotIn('Итого за октябрь', reply)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM report_sync').fetchone()[0],1)
        self.assertEqual('Итоги месяца в Telegram не показываются.', self.store.handle(message(3, '/total'), 'secret')[1])
        self.assertIn('Не записал', self.store.handle(message(4, '12.10 розы 1шт 1500 сайт'), 'secret')[1])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.store.handle(message(1, '/start secret'), 'secret')

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def test_forward_sale_and_duplicate_after_restart(self):
        update = message(2, '12.10 розы 11шт итого 1500 WhatsApp')
        update['message']['forward_origin'] = {'type': 'user', 'date': 1}
        reply = self.store.handle(update, 'secret')[1]
        self.assertIn('Записал', reply)
        self.assertEqual(self.store.total(), 1500)
        self.store.db.close()
        self.store = Store(self.tmp.name)
        self.store.handle(update, 'secret')
        self.assertEqual(self.store.total(), 1500)
        self.assertIn('1500.00', self.store.csv_path.read_text(encoding='utf-8-sig'))

    def test_access_group_invalid(self):
        self.store.handle(message(2, '12.10 розы 1шт 1500 сайт', user=9), 'secret')
        self.assertIsNone(self.store.handle(message(3, '12.10 розы 1шт 1500 сайт', kind='group'), 'secret'))
        self.assertIn('Не записал', self.store.handle(message(4, 'не продажа'), 'secret')[1])
        self.assertEqual(self.store.total(), 0)

    def test_three_sales_and_total(self):
        for i, text in enumerate(['12.10 розы 11шт 1500 WhatsApp', '13.10 букет 1шт 3500 сайт', '14.10 тюльпаны 10шт 180 офлайн'], 2):
            self.store.handle(message(i, text), 'secret')
        self.assertEqual(self.store.total(), 21800)
        self.assertNotIn('21,800.00', self.store.handle(message(5, '/total'), 'secret')[1])

    def test_daily_separate_from_sales(self):
        reply = self.store.handle(message(2, '19.10\nВыручка: 10150\nQR-код: 5200\nБ/н: 4950'), 'secret')[1]
        self.assertNotIn('10150.00', reply)
        self.assertEqual(self.store.total(), 0)
        self.assertTrue((Path(self.tmp.name)/'daily_reports_october_2026.csv').exists())
