"""System-Python TLS transport. Credentials arrive over stdin, never argv/files."""
import base64
import json
import sys
import urllib.error
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    payload = json.loads(sys.stdin.buffer.read(100000))
    body = base64.b64decode(payload['body']) if payload['method'] == 'POST' else None
    request = urllib.request.Request(payload['url'], data=body, headers=payload['headers'], method=payload['method'])
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=50) as response:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                return {'error': '翻譯回應過大，已停止接收。'}
            return {'status': response.status, 'body': base64.b64encode(raw).decode()}
    except urllib.error.HTTPError as exc:
        return {'status': exc.code, 'body': ''}
    except (OSError, urllib.error.URLError):
        return {'error': '服務無法連線，請檢查網路、API 地址與系統時間。'}


if __name__ == '__main__':
    try:
        print(json.dumps(main(), ensure_ascii=False))
    except Exception:
        print(json.dumps({'error': '翻譯請求無法完成。'}, ensure_ascii=False))
