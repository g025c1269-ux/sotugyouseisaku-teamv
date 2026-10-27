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
ANNUAL_PROMPT = '''あなたは生態系ゲームの明るく親しみやすい案内役「リーフ」です。
確定した年間データだけから、日本語80〜150文字、3〜4文の年間総括を作ってください。
commentだけを持つJSONを返し、見出し・挨拶・思考過程は出さないでください。
草食と肉食の両方に必ず触れ、特に大きな増減や形質の変化を優先し、数値の羅列は避けてください。
増減・高低・比較はPythonが確定した結果を使ってください。平均は全員の特徴ではありません。
partial=trueなら年の途中までの記録であることを伝えてください。nullの平均やイベントは取得不能です。
災害や行動、過去の出来事を捏造せず、気温や食料が増減の原因だったと断定しないでください。
active=falseの形質を行動の理由にしないでください。温度適性が高いほど寒さに強いとは限りません。
最後に次の観察への期待や注意を一言添えても構いません。未来の繁栄や絶滅は断定しません。
設定変更や操作コマンドは出さず、表示用の文章だけを作ってください。'''


class OllamaError(Exception):
    """Safe Japanese message suitable for the UI."""
    def __init__(self, message, raw_response=None):
        super().__init__(message)
        self.raw_response = raw_response


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

    def build_request(self, context):
        cfg = self.settings
        annual = context.get('target') == 'annual'
        minimum, maximum = (80, 150) if annual else (40, 80)
        prompt = ANNUAL_PROMPT if annual else SYSTEM_PROMPT
        if annual:
            # The audit keeps full snapshots; avoid sending duplicate distributions twice.
            context = {k: v for k, v in context.items() if k not in ('start', 'end')}
        payload = {
            'model': cfg.model, 'think': False, 'stream': False, 'keep_alive': cfg.keep_alive,
            'messages': [{'role': 'system', 'content': prompt},
                         {'role': 'user', 'content': json.dumps(context, ensure_ascii=False, allow_nan=False, separators=(',', ':'))}],
            'format': {'type': 'object', 'properties': {'comment': {'type': 'string', 'minLength': minimum, 'maxLength': maximum}},
                       'required': ['comment'], 'additionalProperties': False},
            'options': {'num_predict': min(512, cfg.num_predict * 2) if annual else cfg.num_predict, 'num_ctx': cfg.num_ctx,
                        'num_thread': cfg.num_thread, 'temperature': 0.4},
        }
        return payload

    def generate(self, context):
        cfg = self.settings
        annual = context.get('target') == 'annual'
        minimum, maximum = (80, 150) if annual else (40, 80)
        payload = self.build_request(context)
        request = Request(cfg.base_url.rstrip('/') + '/api/chat',
                          data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                          headers={'Content-Type': 'application/json'}, method='POST')
        # Never send local observations through a system HTTP proxy or redirect.
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        raw = b''
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
            if (not minimum <= len(text) <= maximum or not re.search(r'[ぁ-んァ-ン一-龯]', text)
                    or '<' in text or '>' in text or any(ord(c) < 32 for c in text)):
                raise ValueError('Invalid comment')
            if annual and ('草食' not in text or '肉食' not in text):
                raise ValueError('Both species must be mentioned')
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
            raise OllamaError('AIの返事を使えなかったよ。ルール解説を表示するね。', raw.decode('utf-8', errors='replace')) from exc
