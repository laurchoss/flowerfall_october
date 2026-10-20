"""Запуск/остановка бота на Mac. Команды выполняет помощник."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
LABEL = 'local.flowerfall.telegram'
TARGET = f'gui/{os.getuid()}/{LABEL}'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'stop', 'status'])
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.exit(1, 'Этот запуск подготовлен для macOS.\n')
    status = subprocess.run(['/bin/launchctl', 'print', TARGET], capture_output=True, text=True)
    if args.action == 'status':
        if status.returncode:
            print('Бот не загружен в фоновые службы macOS.')
        else:
            lines = [x.strip() for x in status.stdout.splitlines() if x.strip().startswith(('state =', 'pid =', 'last exit code ='))]
            print('Служба бота загружена. ' + '; '.join(lines))
        return 0
    if args.action == 'stop':
        if not status.returncode:
            subprocess.run(['/bin/launchctl', 'bootout', TARGET], check=True)
        print('Бот остановлен.')
        return 0
    if not status.returncode:
        print('Служба уже загружена. Для проверки попросите показать статус бота.')
        return 0
    # Проверка токена и Telegram до фонового запуска.
    check = subprocess.run([sys.executable, str(ROOT/'telegram_bot.py'), '--check'], cwd=ROOT)
    if check.returncode:
        return check.returncode
    for name in ['bot.stdout.log', 'bot.stderr.log']:
        path = ROOT/name
        path.touch(exist_ok=True)
        path.chmod(0o600)
    plist = ROOT/'flowerfall_bot.plist'
    plist.write_bytes(plistlib.dumps({
        'Label': LABEL,
        'ProgramArguments': [sys.executable, str(ROOT/'telegram_bot.py')],
        'WorkingDirectory': str(ROOT),
        'RunAtLoad': True,
        'KeepAlive': True,
        'ThrottleInterval': 30,
        'StandardOutPath': str(ROOT/'bot.stdout.log'),
        'StandardErrorPath': str(ROOT/'bot.stderr.log'),
        'Umask': 0o077,
    }))
    subprocess.run(['/bin/launchctl', 'bootstrap', f'gui/{os.getuid()}', str(plist)], check=True)
    print('Служба бота запущена. Попросите помощника проверить статус и первую пересылку.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
