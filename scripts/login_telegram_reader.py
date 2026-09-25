"""One-time local QR authorization. Never print API keys, QR tokens or sessions."""
import asyncio
import io
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs
import qrcode
from dotenv import dotenv_values
from telethon import TelegramClient, errors
from bootstrap_private_setup import ROOT, _restrict_permissions, _protect_for_current_windows_user

state = {'png': b'', 'status':'connecting', 'password':None}
nonce = secrets.token_urlsafe(24)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def do_GET(self):
        if not self.path.startswith('/'+nonce):
            self.send_error(404); return
        self.send_response(200)
        self.send_header('Cache-Control','no-store')
        if self.path.endswith('/qr.png'):
            self.send_header('Content-Type','image/png'); self.end_headers()
            self.wfile.write(state['png']); return
        self.send_header('Content-Type','text/html; charset=utf-8'); self.end_headers()
        status = state['status']
        content = '<title>Telegram reader login</title><h2>Telegram — link news reader</h2>'
        if status == 'authorized':
            content += '<p>Account linked successfully. You can close this page.</p>'
        elif status == 'password_required':
            content += '<p>Enter your Telegram two-step verification password locally.</p><form method="post"><input type="password" name="password" autocomplete="off"><button>Verify</button></form>'
        elif status.startswith('error'):
            content += '<p>Login failed. Restart the local login script.</p>'
        else:
            content += '<meta http-equiv="refresh" content="5"><p>Telegram app: Settings → Devices → Link Desktop Device.</p><img src="/'+nonce+'/qr.png" width="320" height="320"><p>Scan using the intended reader account.</p>'
        self.wfile.write(content.encode())
    def do_POST(self):
        if self.path != '/'+nonce or state['status'] != 'password_required' or int(self.headers.get('Content-Length',0))>2048:
            self.send_error(403); return
        form = parse_qs(self.rfile.read(int(self.headers.get('Content-Length',0))).decode())
        state['password'] = form.get('password',[''])[0]
        state['status'] = 'verifying'
        self.send_response(303); self.send_header('Location','/'+nonce); self.end_headers()

async def login():
    cfg = dotenv_values(ROOT/'.env')
    session = ROOT/'.runtime/telegram-reader.session'
    client = TelegramClient(str(session), int(cfg['TELEGRAM_API_ID']), cfg['TELEGRAM_API_HASH'],
                            device_model='AI-Trader News Reader', connection_retries=2)
    try:
        await client.connect()
        if session.exists():
            _restrict_permissions(session)
        for _ in range(30):
            if await client.is_user_authorized():
                break
            qr = await client.qr_login()
            image = qrcode.make(qr.url); data = io.BytesIO(); image.save(data, format='PNG')
            state.update(png=data.getvalue(),status='scan_qr')
            try:
                await qr.wait(timeout=60)
            except asyncio.TimeoutError:
                continue
            except errors.SessionPasswordNeededError:
                state['status'] = 'password_required'
                while state['password'] is None:
                    await asyncio.sleep(.5)
                password = state['password']; state['password'] = None
                await client.sign_in(password=password)
                password = None
        if not await client.is_user_authorized():
            state['status'] = 'error_timeout'; return
        await client.disconnect()
        _restrict_permissions(session)
        encrypted = _protect_for_current_windows_user(session.read_bytes())
        if encrypted:
            backup = ROOT/'.runtime/telegram-reader.session.encrypted'
            backup.write_bytes(encrypted); _restrict_permissions(backup)
        state.update(status='authorized',png=b'')
        print('Telegram reader account authorized; session stored privately.',flush=True)
    except Exception as exc:
        state['status'] = 'error'
        print('Authorization failed: '+type(exc).__name__,flush=True)
    finally:
        await client.disconnect()

if __name__ == '__main__':
    server = HTTPServer(('127.0.0.1',18770),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    print('http://127.0.0.1:18770/'+nonce,flush=True)
    asyncio.run(login())
    time.sleep(30)
    server.shutdown()
