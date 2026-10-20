"""Локальный CLI: сбор продаж и сводная таблица октября 2026."""
import argparse
import json
from pathlib import Path
from decimal import Decimal, InvalidOperation
from daily_reports import record, export_business
from sales import update, read_rows, money


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path('data'), help='Папка локальных данных (по умолчанию data)')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init', help='Создать пустые таблицы')
    sale = commands.add_parser('sale', help='Добавить отдельные продажи')
    sale.add_argument('messages', nargs='+')
    report = commands.add_parser('report', help='Добавить дневной отчёт из UTF-8 файла')
    report.add_argument('--input', type=Path, required=True)
    commands.add_parser('summary', help='Пересобрать сводку за 31 день')
    args = parser.parse_args()
    try:
        args.directory.mkdir(parents=True, exist_ok=True)
        path = args.directory / 'sales_october_2026.csv'
        result = {}
        if args.command == 'init':
            update(path, [])
        elif args.command == 'sale':
            update(path, args.messages)
            result['добавлено_продаж'] = len(args.messages)
        elif args.command == 'report':
            saved = record(args.input.read_text(encoding='utf-8-sig'), args.directory)
            result['отчёт_добавлен'] = saved['записано']
        result.update(export_business(args.directory, 'Б/Н'))
        rows = read_rows(path)
        result['отдельные_продажи'] = {'число': len(rows), 'сумма': money(sum((Decimal(row[4]) for row in rows), Decimal(0)))}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result['ожидают_уточнения'] else 0
    except (ValueError, InvalidOperation, OSError) as error:
        parser.exit(2, f'Ошибка: {error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
