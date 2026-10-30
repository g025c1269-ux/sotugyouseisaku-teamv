"""Bounded, local-only Ollama /api/chat client using Python's standard library."""
from dataclasses import dataclass
from http.client import HTTPException
import ipaddress
import json
from pathlib import Path
import re
import socket
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from annual_ai_context import build_annual_ai_context, is_rule_recital


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
ANNUAL_PROMPT = '''あなたは生態系ゲームの研究員「リーフ」。明るい相棒の口調で、今年の重要な変化を1〜2個選んで考察します。
「何が起きた？」→「なぜ起きた可能性がある？」→「この先どうなる可能性がある？」に答えてください。
観測値を先に使い、参考ルールは今回の変化に当てはめます。原因は「〜かも」と仮説にし、繁殖・遺伝・集団構成など別の説明も考えます。未来は条件付きです。
草食と肉食・食物・環境のつながりを考えてください。不明な数値や出来事は作らず、材料がない点だけ不明と伝えます。partial=trueは観察した期間だけの話です。
200〜350文字を目安に、{"comment":"本文"}だけを返します。仕様の列挙、命令文の復唱、「因果は未検証」だけの結びは不要です。'''
ANNUAL_DATA_MARKER = '\n\n年間観測データ(JSON):\n'


class OllamaError(Exception):
    """Safe Japanese message suitable for the UI."""
    def __init__(self, message, raw_response=None, kind="generation_error"):
        super().__init__(message)
        self.raw_response = raw_response
        self.kind = kind


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
        minimum, maximum = (40, 2000) if annual else (40, 80)
        if annual:
            # No explicit system: preserve the model's own SYSTEM/TEMPLATE.
            # Task/persona/reference in the user message also work without one.
            data = json.dumps(build_annual_ai_context(context), ensure_ascii=False,
                              allow_nan=False, separators=(',', ':'))
            messages = [{'role': 'user', 'content': ANNUAL_PROMPT + ANNUAL_DATA_MARKER + data}]
        else:
            messages = [{'role': 'system', 'content': SYSTEM_PROMPT},
                        {'role': 'user', 'content': json.dumps(context, ensure_ascii=False,
                                                            allow_nan=False, separators=(',', ':'))}]
        payload = {
            'model': cfg.model, 'think': False, 'stream': False, 'keep_alive': cfg.keep_alive,
            'messages': messages,
            'format': {'type': 'object', 'properties': {'comment': {'type': 'string', 'minLength': minimum, 'maxLength': maximum}},
                       'required': ['comment'], 'additionalProperties': False},
            'options': {'num_predict': min(512, cfg.num_predict * 2) if annual else cfg.num_predict, 'num_ctx': cfg.num_ctx,
                        'num_thread': cfg.num_thread, 'temperature': 0.4},
        }
        return payload

    def generate(self, context):
        started = time.monotonic()
        self.last_diagnostics = {
            'year': context.get('year'), 'target': context.get('target'),
            'model': self.settings.model,
            'started_at': datetime.now(timezone.utc).isoformat(),
            'timeout_seconds': self.settings.timeout_seconds,
            'success': False, 'error_kind': None, 'ollama': {}, 'repairs': [],
        }
        try:
            text = self._generate(context)
            self.last_diagnostics['success'] = True
            self.last_diagnostics['characters'] = len(text)
            return text
        except OllamaError as exc:
            self.last_diagnostics['error_kind'] = exc.kind
            raise
        except Exception:
            self.last_diagnostics['error_kind'] = 'internal_error'
            raise
        finally:
            self.last_diagnostics['finished_at'] = datetime.now(timezone.utc).isoformat()
            self.last_diagnostics['elapsed_seconds'] = round(time.monotonic() - started, 6)

    def _generate(self, context):
        cfg = self.settings
        annual = context.get('target') == 'annual'
        minimum, maximum = (40, 2000) if annual else (40, 80)
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
            for key in ('total_duration', 'load_duration', 'prompt_eval_count', 'prompt_eval_duration',
                        'eval_count', 'eval_duration'):
                value = envelope.get(key)
                if type(value) in (int, float) and value >= 0 and value < 1e20:
                    self.last_diagnostics['ollama'][key] = value
            if envelope.get('error'):
                raise OllamaError('Ollamaが生成できなかったよ。モデルと設定を確認してね。')
            if envelope.get('done') is not True:
                raise OllamaError('AIの返事が途中で終わったよ。もう一度更新してね。')
            content = self._parse_comment(envelope['message']['content'])
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
            if annual and self._is_instruction_echo(text):
                raise OllamaError('年間データの考察ではなく指示の説明が返ったため、通常解説に切り替えるね。',
                                  raw.decode('utf-8', errors='replace'), kind='instruction_echo')
            if annual and is_rule_recital(text):
                raise OllamaError('観測結果に触れず仕様説明だけが返ったため、通常解説に切り替えるね。',
                                  raw.decode('utf-8', errors='replace'), kind='rule_recital')
            return text
        except HTTPError as exc:
            if exc.code == 404:
                raise OllamaError('モデルが見つからないよ。ollama listで設定したモデルを確認してね。', kind='model_not_found') from exc
            raise OllamaError('Ollamaが応答できないよ。起動状態やバージョンを確認してね。', kind='http_error') from exc
        except (socket.timeout, TimeoutError) as exc:
            raise OllamaError('AIの返事が時間切れだよ。通常解説に切り替えるね。', kind='timeout') from exc
        except URLError as exc:
            if isinstance(exc.reason, (socket.timeout, TimeoutError)):
                raise OllamaError('AIの返事が時間切れだよ。通常解説に切り替えるね。', kind='timeout') from exc
            raise OllamaError('Ollamaにつながらないよ。Ollamaを起動してね。', kind='connection_error') from exc
        except (ValueError, KeyError, TypeError, UnicodeError, OSError, HTTPException) as exc:
            raise OllamaError('AIの返事を使えなかったよ。ルール解説を表示するね。', raw.decode('utf-8', errors='replace'), kind='response_format') from exc


    def _parse_comment(self, source):
        """Repair only whole JSON fences and commas outside quoted strings."""
        if not isinstance(source, str):
            raise ValueError('Invalid content type')
        source = source.strip()
        fence = re.fullmatch(r'```(?:json)?\s*\n(.*?)\n```', source, re.S | re.I)
        if fence:
            source = fence.group(1).strip()
            self.last_diagnostics['repairs'].append('json_fence')
        repaired = re.sub(r'"(?:\\.|[^"\\])*"|,\s*(?=[}\]])',
                          lambda m: m.group() if m.group().startswith('"') else '', source)
        if repaired != source:
            self.last_diagnostics['repairs'].append('trailing_comma')
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate JSON key')
                result[key] = value
            return result
        return json.loads(repaired, object_pairs_hook=unique)


    @staticmethod
    def _is_instruction_echo(text):
        """Reject explicit output/procedure instructions, not ordinary advice.

        Deliberately narrow: facts, hypotheses, 'ください', or shared trait words
        alone are not evidence of an echo. This is not a factuality verifier.
        """
        patterns = (
            r'(?:Python|パイソン).{0,25}(?:確定|計算).{0,30}(?:使って|用いて|参照して|使用して)ください',
            r'(?:comment|JSON).{0,30}(?:返して|出力して|返します|出力します|キーだけ)',
            r'(?:回答|解説|文章)(?:では|は).{0,20}(?:観測|仮説|展望).{0,30}(?:含め|順に|説明|書いて|まとめ)',
            r'(?:システムプロンプト|systemプロンプト|命令文|指示や書き方).{0,30}(?:説明|従|言い換え|復唱)',
            r'(?:仲間の増減|平均形質の変化).{0,50}(?:つなげて|順に|優先して).{0,12}(?:話して|述べて|説明して|話しています)',
            r'(?:草食|肉食).{0,20}(?:両方|それぞれ).{0,20}(?:触れ|言及|説明).{0,12}(?:ください|します|しています)',
        )
        return any(re.search(pattern, sentence, re.I)
                   for sentence in re.split(r'[。！？\n]', text) for pattern in patterns)
