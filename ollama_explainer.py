"""Bounded, local-only Ollama /api/chat client using Python's standard library."""
from dataclasses import dataclass
from http.client import HTTPException
import ipaddress
import json
from pathlib import Path
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


CONFIG_PATH = Path(__file__).with_name('data') / 'ollama_config.json'
MAX_RESPONSE_BYTES = 65536
SYSTEM_PROMPT = '''あなたは生態系ゲームの明るい案内役「リーフ」です。
渡された観察データだけを使い、日本語40〜80文字、2〜3文で短く話してください。
commentというキーだけのJSONを返してください。挨拶、思考過程、見出しは不要です。
良いところと注意点を伝え、数値の読み上げでなく意味をやさしく説明してください。
高低の判定・集団との比較はPythonが計算したlevel/comparisonをそのまま使います。
active=falseの形質を行動の理由にしないでください。温度適性は高いほど寒さに強いわけではありません。
平均と分布を区別し、平均だけで全員が同じと決めつけないでください。
個体解説では集団との比較も使ってください。将来の絶滅・繁栄・狩りの成功は断定しません。
与えられていない能力・地形・個体の行動や過去の変化を作らないでください。
ゲームの設定変更・コマンド・操作指示は出さず、観察のコメントだけを返してください。'''


class OllamaError(Exception):
    """Safe Japanese message suitable for the UI."""


@dataclass(frozen=True)
class OllamaSettings:
    base_url: str = 'http://localhost:11434'
    model: str = 'qwen3:4b'
    timeout_seconds: float = 60
    num_predict: int = 256
    num_ctx: int = 4096
    num_thread: int = 4
    keep_alive: str = '2m'

    def __post_init__(self):
        parsed = urlsplit(self.base_url)
        host = parsed.hostname
        try:
            loopback = host == 'localhost' or ipaddress.ip_address(host or '').is_loopback
        except ValueError:
            loopback = False
        if (parsed.scheme not in ('http', 'https') or not loopback or parsed.username
                or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            raise ValueError('接続先はlocalhostまたはループバックIPを指定してね。')
        # Validate the port now, rather than failing in the game loop.
        parsed.port
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError('モデル名を指定してね。')
        if not 1 <= self.timeout_seconds <= 180:
            raise ValueError('通信タイムアウトは1〜180秒にしてね。')
        for value, lower, upper in ((self.num_predict, 64, 512), (self.num_ctx, 2048, 8192), (self.num_thread, 1, 8)):
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError('AIの生成設定の値域を確認してね。')
        if not isinstance(self.keep_alive, str) or not re.fullmatch(r'[0-9]+[sm]', self.keep_alive):
            raise ValueError('keep_aliveは2mなど秒・分で指定してね。')

    @classmethod
    def load(cls, path=CONFIG_PATH):
        try:
            return cls(**json.loads(Path(path).read_text(encoding='utf-8')))
        except (OSError, ValueError, TypeError) as exc:
            raise OllamaError('AI設定を読み込めないよ。data/ollama_config.jsonを確認してね。') from exc


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class OllamaExplainer:
    def __init__(self, settings=None):
        self.settings = settings or OllamaSettings.load()

    def generate(self, context):
        cfg = self.settings
        payload = {
            'model': cfg.model, 'think': False, 'stream': False, 'keep_alive': cfg.keep_alive,
            'messages': [{'role': 'system', 'content': SYSTEM_PROMPT},
                         {'role': 'user', 'content': json.dumps(context, ensure_ascii=False, allow_nan=False)}],
            'format': {'type': 'object', 'properties': {'comment': {'type': 'string', 'minLength': 40, 'maxLength': 80}},
                       'required': ['comment'], 'additionalProperties': False},
            'options': {'num_predict': cfg.num_predict, 'num_ctx': cfg.num_ctx,
                        'num_thread': cfg.num_thread, 'temperature': 0.4},
        }
        request = Request(cfg.base_url.rstrip('/') + '/api/chat',
                          data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                          headers={'Content-Type': 'application/json'}, method='POST')
        # Never send local observations through a system HTTP proxy or redirect.
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        try:
            with opener.open(request, timeout=cfg.timeout_seconds) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise OllamaError('AIの返事が長すぎたよ。もう一度更新してね。')
            envelope = json.loads(raw)
            if not isinstance(envelope, dict):
                raise ValueError('Invalid envelope')
            if envelope.get('error'):
                raise OllamaError('Ollamaが生成できなかったよ。モデルと設定を確認してね。')
            if envelope.get('done') is not True:
                raise OllamaError('AIの返事が途中で終わったよ。もう一度更新してね。')
            content = json.loads(envelope['message']['content'])
            if not isinstance(content, dict) or set(content) != {'comment'}:
                raise ValueError('Invalid content')
            text = content['comment']
            if not isinstance(text, str):
                raise ValueError('Invalid comment')
            text = re.sub(r'\s+', ' ', text).strip()
            if (not 40 <= len(text) <= 80 or not re.search(r'[ぁ-んァ-ン一-龯]', text)
                    or '<' in text or '>' in text or any(ord(c) < 32 for c in text)):
                raise ValueError('Invalid comment')
            return text
        except HTTPError as exc:
            if exc.code == 404:
                raise OllamaError('モデルが見つからないよ。ollama listで設定したモデルを確認してね。') from exc
            raise OllamaError('Ollamaが応答できないよ。起動状態やバージョンを確認してね。') from exc
        except (socket.timeout, TimeoutError) as exc:
            raise OllamaError('AIの返事が時間切れだよ。少し待ってから再更新してね。') from exc
        except URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise OllamaError('AIの返事が時間切れだよ。少し待ってから再更新してね。') from exc
            raise OllamaError('Ollamaにつながらないよ。Ollamaを起動してから更新してね。') from exc
        except (ValueError, KeyError, TypeError, UnicodeError, OSError, HTTPException) as exc:
            raise OllamaError('AIの返事を使えなかったよ。ルール解説を表示するね。') from exc
