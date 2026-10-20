import json
from pathlib import Path
import tempfile
import unittest
from telegram_bot import Store, REPORT_KEYBOARD
from report_wizard import get_draft, keyboard
from test_telegram_bot import message


class WizardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name, mode='daily', config={'qr_target':'Б/Н'})
        self.uid = 0
        self.send('/start secret')

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def send(self, text, user=7):
        self.uid += 1
        return self.store.handle(message(self.uid, text, user=user), 'secret')[1]

    def complete(self):
        self.send('Отчёт за день')
        reply = None
        for answer in ['20.10','Саша','1000','2500','100','3800','0','0','200','4000']:
            reply = self.send(answer)
        return reply

    def test_preview_edit_save_and_no_monthly_total(self):
        preview = self.complete()
        self.assertIn('Выручка: 3600.00', preview)
        self.assertIn('Б/Н: 2500.00', preview)
        source = Path(self.tmp.name)/'daily_reports_october_2026.json'
        self.assertFalse(source.exists())
        self.send('Исправить')
        self.send('Наличка')
        self.assertIn('Выручка: 4600.00', self.send('2000'))
        self.assertIn('Записал отчёт', self.send('Сохранить'))
        data = json.loads(source.read_text())
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['данные']['Выручка'], '4600.00')
        self.assertIsNone(get_draft(self.store.db,7))
        self.assertEqual(keyboard(self.store.db,7,REPORT_KEYBOARD),REPORT_KEYBOARD)
        self.assertNotIn('за октябрь', preview)

    def test_invalid_back_restart_and_cancel(self):
        self.send('/report')
        self.assertIn('октябрь', self.send('20.09'))
        self.send('20')
        self.send('Саша')
        self.assertIn('Введите сумму', self.send('-10'))
        self.send('100')
        self.send('Назад')
        self.assertEqual(get_draft(self.store.db,7)['step'],2)
        self.store.db.close()
        self.store = Store(self.tmp.name,mode='daily',config={'qr_target':'Б/Н'})
        self.assertIn('Продолжаем',self.send('/report'))
        self.send('/cancel')
        self.assertFalse((Path(self.tmp.name)/'daily_reports_october_2026.json').exists())

    def test_delivery_retry_and_unauthorized(self):
        self.send('/report')
        self.uid += 1
        update=message(self.uid,'21.10')
        self.store.handle(update,'secret')
        self.store.handle(update,'secret')
        self.assertEqual(get_draft(self.store.db,7)['step'],1)
        self.assertIn('только владельцу',self.send('/report',user=9))
        self.assertIsNone(get_draft(self.store.db,9))

    def test_conflicting_day_keeps_draft(self):
        self.complete()
        self.send('Сохранить')
        self.complete()
        self.send('Исправить')
        self.send('ЗП')
        self.send('5000')
        self.assertIn('Не сохранил',self.send('Сохранить'))
        self.assertIsNotNone(get_draft(self.store.db,7))

    def test_test_mode_never_writes_finance_files(self):
        from unittest.mock import patch
        self.store.save_wizard('19.10\nВыручка: 1000\nНал: 1000')
        self.send('/report')
        self.send('21.10')
        self.store.start_test(7)
        files = {p.name:p.read_bytes() for p in Path(self.tmp.name).glob('*') if p.suffix in ('.csv','.json')}
        self.complete()
        self.assertIn('НЕ записан', self.send('Сохранить'))
        self.send('22.10\nВыручка: 999999\nНал: 999999')
        self.store.config['google_webapp_url'] = 'https://example.test'
        with patch('telegram_bot.sync_report') as sync:
            self.assertEqual(self.store.flush_sync(),[])
            sync.assert_not_called()
        self.store.db.close()
        self.store = Store(self.tmp.name,mode='daily',config={'qr_target':'Б/Н'})
        self.assertEqual(self.store.setting('test_mode'),'1')
        self.assertEqual(files,{p.name:p.read_bytes() for p in Path(self.tmp.name).glob('*') if p.suffix in ('.csv','.json')})
        self.store.end_test(7)
        self.assertEqual(get_draft(self.store.db,7)['values']['Дата'],'21.10')
