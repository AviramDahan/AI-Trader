"""Import API credentials through a private loopback form without logging values."""
import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import re
import subprocess
from datetime import date
from dotenv import set_key
from bootstrap_private_setup import ROOT, PRIVATE_FILE, ENCRYPTED_FILE, _restrict_permissions, _protect_for_current_windows_user

def save(pair):
    for name in ('.env', 'PRIVATE_SETUP_CREDENTIALS.txt', '.runtime/telegram-reader.session'):
        if subprocess.run(['git', 'check-ignore', '-q', name], cwd=ROOT).returncode:
            raise SystemExit('Private storage is not git-ignored')
    app_id, app_hash = str(pair['api_id']).strip(), str(pair['api_hash']).strip()
    if not app_id.isdigit() or not re.fullmatch(r'[0-9a-fA-F]{32}', app_hash):
        raise SystemExit('Invalid credential format; nothing saved')
    for key, value in [('TELEGRAM_API_ID',app_id),('TELEGRAM_API_HASH',app_hash)]:
        set_key(str(ROOT/'.env'), key, value)
    with PRIVATE_FILE.open('a', encoding='utf-8') as out:
        out.write('\n\nService: Telegram reader API\nPurpose: Authorized news channel reader\nWebsite: https://my.telegram.org\nAccount email: N/A\nUsername: Telegram phone account ending 0675\nPassword: N/A\nAPI key: '+app_id+'\nAPI secret/token: '+app_hash+'\nAccount/project ID: '+app_id+'\nFree plan/tier: Free Telegram API\nEnvironment variable name: TELEGRAM_API_ID, TELEGRAM_API_HASH\nWhere the secret is stored: local ignored .env\nDate created: '+str(date.today())+'\nWhere it is used: local news reader\nNotes: User session requires separate account login; never publish session files.\n')
    encrypted = _protect_for_current_windows_user(PRIVATE_FILE.read_bytes())
    if encrypted:
        ENCRYPTED_FILE.write_bytes(encrypted)
    for path in (ROOT/'.env',PRIVATE_FILE,ENCRYPTED_FILE):
        if path.exists():
            _restrict_permissions(path)
    print('API credentials saved locally; private backup updated.')

def main():
    from urllib.parse import parse_qs
    nonce = secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            if self.path != '/' + nonce:
                self.send_error(404); return
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Cache-Control','no-store'); self.end_headers()
            self.wfile.write(b'<title>Private local Telegram setup</title><form method="post"><label>API credentials JSON<textarea name="pair"></textarea></label><button>Save locally</button></form>')
        def do_POST(self):
            if self.path != '/' + nonce or int(self.headers.get('Content-Length',0)) > 4096:
                self.send_error(403); return
            try:
                form = parse_qs(self.rfile.read(int(self.headers['Content-Length'])).decode())
                save(json.loads(form['pair'][0]))
            except Exception:
                self.send_error(400, 'Could not save credentials'); return
            self.send_response(200); self.send_header('Cache-Control','no-store'); self.end_headers()
            self.wfile.write(b'Credentials saved privately. You can close this tab.')
            threading.Thread(target=self.server.shutdown, daemon=True).start()
    server = HTTPServer(('127.0.0.1',18769),Handler)
    print('http://127.0.0.1:18769/' + nonce, flush=True)
    server.serve_forever()

if __name__ == '__main__':
    main()
