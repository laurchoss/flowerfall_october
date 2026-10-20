import tempfile
import unittest
from daily_reports import parse_report, record, business_values, export_business, BUSINESS_HEADERS

SAMPLE = '19.10\nВыручка: 10150\nQR-код: 5200\nБ/н: 4950\nСписание: 1913 (часть перебрала)\nОстаток в кассе: 4000\nБыла с 8:47 до 21'


class DailyReportTests(unittest.TestCase):
    def test_report_from_screenshot(self):
        text = 'дата- 15.10\nимя- Бону\nзп-5000₽\nВыручка 16000₽\nНал 1600₽\nб/н -0₽\nперевод - 0₽\nОстаток в кассе 4550₽'
        report = parse_report(text)
        self.assertEqual(report['данные']['Дата'], '15.10.2026')
        self.assertEqual(report['данные']['Имя'], 'Бону')
        self.assertEqual(report['данные']['Зарплата'], '5000.00')
        self.assertEqual(report['данные']['Выручка'], '16000.00')
        self.assertEqual(report['данные']['Безнал'], '0.00')
        self.assertEqual(report['данные']['Остаток в кассе'], '4550.00')
        self.assertEqual(report['разница_с_выручкой'], '14400.00')

    def test_business_layout_and_qr(self):
        report = parse_report(SAMPLE)
        row = business_values(report, 'Б/Н')
        self.assertEqual(list(row), BUSINESS_HEADERS)
        self.assertEqual(row['Б/Н'], '10150.00')
        self.assertEqual(row['Выручка'], '10150.00')
        self.assertEqual(row['ЗП'], '')
        with self.assertRaises(ValueError):
            business_values(report)

    def test_name_and_revenue_from_payments(self):
        row = business_values(parse_report(SAMPLE.replace('19.10', '19/10\nИмя: Боня\nЗП: 5000').replace('10150', '10500')), 'Б/Н')
        self.assertEqual(row['Имя'], 'Боня')
        self.assertEqual(row['ЗП'], '5000.00')
        self.assertEqual(row['Выручка'], '10150.00')

    def test_monthly_export(self):
        with tempfile.TemporaryDirectory() as directory:
            record(SAMPLE, directory)
            summary = export_business(directory, 'Б/Н')
            self.assertEqual(summary['итого'], '10150.00')
            self.assertEqual(summary['ожидают_уточнения'], [])
            import csv
            with open(summary['таблица'], encoding='utf-8-sig') as file:
                rows = list(csv.reader(file, delimiter=';'))
            self.assertEqual(rows[0], BUSINESS_HEADERS)
            self.assertEqual(rows[19][5], '10150.00')
            self.assertEqual(len(rows), 32)

    def test_sample(self):
        report = parse_report(SAMPLE)
        row = report['данные']
        self.assertEqual(report['разница_с_выручкой'], '0.00')
        self.assertEqual(row['Длительность смены'], '12:13')
        self.assertEqual(row['Наличка'], '')
        self.assertEqual(row['Зарплата'], '')
        self.assertEqual(row['QR-код'], '5200.00')
        self.assertIn('часть перебрала', row['Примечание'])

    def test_duplicate_and_conflict(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(record(SAMPLE, directory)['записано'])
            self.assertFalse(record(SAMPLE, directory)['записано'])
            with self.assertRaises(ValueError):
                record(SAMPLE.replace('10150', '10500'), directory)

    def test_invalid_and_difference(self):
        self.assertEqual(parse_report(SAMPLE.replace('10150', '10500'))['разница_с_выручкой'], '350.00')
        for text in [SAMPLE.replace('19.10', '32.10'), SAMPLE.replace('10150', 'ошибка'), SAMPLE.replace('8:47', '8:99')]:
            with self.assertRaises(ValueError):
                parse_report(text)
