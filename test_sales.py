import tempfile
import unittest
from pathlib import Path
from sales import parse_sale, update, read_rows


class SalesTests(unittest.TestCase):
    def test_unit_price_and_note(self):
        row = parse_sale('12.10 розы 11шт 1 500 WhatsApp; красные')
        self.assertEqual(row, ['12.10.2026', 'розы', '11', '1500.00', '16500.00', 'WhatsApp', 'красные'])

    def test_total_and_decimal(self):
        self.assertEqual(parse_sale('13.10 розы 3 шт итого 1000 сайт')[3:5], ['333.33', '1000.00'])
        self.assertEqual(parse_sale('14.10 лента 2шт 12,50 офлайн')[4], '25.00')

    def test_invalid(self):
        for text in ['32.10 розы 1шт 10 сайт', '12.11 розы 1шт 10 сайт',
                     '12.10 розы 0шт 10 сайт', '12.10 розы 1шт -10 сайт',
                     '12.10 розы 1шт 10', '12.10.2025 розы 1шт 10 сайт']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_sale(text)

    def test_saved_batch_and_no_partial_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'sales.csv'
            messages = ['12.10 розы 11шт 1500 WhatsApp', '13.10 букет 1шт 3500 сайт', '14.10 тюльпаны 10шт 180 офлайн']
            self.assertEqual(len(update(path, messages)), 3)
            before = path.read_bytes()
            with self.assertRaises(ValueError):
                update(path, [messages[0], 'плохое сообщение'])
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(len(read_rows(path)), 3)


if __name__ == '__main__':
    unittest.main()
