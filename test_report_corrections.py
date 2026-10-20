import json
from pathlib import Path
import tempfile
import unittest
from telegram_bot import Store
from test_telegram_bot import message


class CorrectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(self.tmp.name,mode='daily',config={'qr_target':'Б/Н'})
        self.uid=0
        self.send('/start secret')
        self.store.save_wizard('18.10\nИмя: Саша\nВыручка: 1000\nНал: 1000\nСписание: 100')
        self.store.start_test(7)
        self.send('/cancel')

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def send(self,text,user=7):
        self.uid+=1
        return self.store.handle(message(self.uid,text,user=user),'secret')[1]

    def test_confirm_history_idempotency_and_real_files_unchanged(self):
        before={p.name:p.read_bytes() for p in Path(self.tmp.name).glob('*') if p.suffix in ('.csv','.json')}
        self.send('Исправить отчёт')
        self.send('18.10')
        self.send('Списание')
        self.assertIn('Было: 100.00\nСтанет: 200.00',self.send('200'))
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM test_report_history').fetchone()[0],0)
        self.uid+=1
        update=message(self.uid,'Подтвердить')
        self.assertIn('только в пробной копии',self.store.handle(update,'secret')[1])
        self.store.handle(update,'secret')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM test_reports').fetchone()[0],1)
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM test_report_history').fetchone()[0],1)
        self.assertEqual(before,{p.name:p.read_bytes() for p in Path(self.tmp.name).glob('*') if p.suffix in ('.csv','.json')})
        self.assertEqual(self.store.setting('test_mode'),'1')
        self.send('/editreport');self.send('18.10')
        self.assertIn('200.00',self.send('История исправлений'))

    def test_payment_recalculation_cancel_and_restart(self):
        self.send('/editreport');self.send('18.10');self.send('Наличка')
        self.assertIn('Введите сумму',self.send('-5'))
        self.assertIn('Выручка: 1000.00 → 1500.00',self.send('1500'))
        self.store.db.close()
        self.store=Store(self.tmp.name,mode='daily')
        self.send('Подтвердить')
        row=json.loads(self.store.db.execute('SELECT data FROM test_reports').fetchone()[0])
        self.assertEqual(row['Выручка'],'1500.00')
        self.send('/editreport');self.send('18.10');self.send('ЗП');self.send('9999');self.send('Отмена')
        self.assertEqual(self.store.db.execute('SELECT COUNT(*) FROM test_report_history').fetchone()[0],1)
        self.assertIn('только владельцу',self.send('/editreport',user=9))

    def test_name_buttons(self):
        self.send('/report');self.send('20.10')
        labels=[b['text'] for row in self.store.reply_keyboard(7)['keyboard'] for b in row]
        self.assertTrue({'Бону','Саша','Ксюша'}.issubset(labels))
        self.assertIn('Наличка',self.send('Другое имя'))
