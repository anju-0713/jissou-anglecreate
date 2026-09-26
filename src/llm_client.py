"""OpenAI 呼び出しをまとめたモジュール。

- 応答は JSON（Structured Outputs）で受け取る。temperature=0
- 同じ入力の応答は cache/ に保存し、再実行時は API を呼ばない（課金しない）
- 失敗したら待って最大3回まで再試行。それでも失敗したら outputs/errors.csv に残して None を返す
- レート制限（429）のときは、通常の再試行とは別に、長めに待って再試行する
- chat_json_many で同時に config.LLM_WORKERS 件ずつ並列に送れる
- 呼び出し回数とトークン数を数え、概算費用を出す
"""
import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
from tqdm import tqdm

from src import config, io_utils


def estimate_tokens(text: str) -> int:
    """概算トークン数（多めの見積もり）。"""
    return int(len(text) * config.EST_TOKENS_PER_CHAR)


def price_of(model: str) -> dict | None:
    """モデルの料金表（米ドル/100万トークン）。表にないモデルは None。"""
    return config.MODEL_PRICES_USD.get(model)


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    p = price_of(model)
    if p is None:
        return None
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000


def format_cost(usd: float | None) -> str:
    if usd is None:
        return "不明（config.MODEL_PRICES_USD に料金を追加してください）"
    return f"${usd:.4f}（約 {usd * config.USD_JPY:.1f} 円）"


def confirm(message: str) -> bool:
    """y が入力されたときだけ True。入力できない環境では False（実行しない）。"""
    try:
        return input(f"{message} [y/N]: ").strip().lower() == "y"
    except EOFError:
        print("\n（入力がないため中止しました）")
        return False


class LLMClient:
    """OpenAI の呼び出し役。使った分の回数・トークンを覚えておく。"""

    def __init__(self, step: str):
        load_dotenv(config.ROOT_DIR / ".env")
        from openai import OpenAI  # APIを使うときだけ読み込む

        self.step = step
        self.model = os.getenv("OPENAI_MODEL") or config.DEFAULT_MODEL
        # OPENAI_API_KEY は環境変数（.env）から読まれる。再試行はこのクラスで行うのでライブラリ側は0回
        self.client = OpenAI(max_retries=0)
        self._lock = threading.Lock()  # 並列実行中に回数・トークンを正しく数えるため
        self.api_calls = 0
        self.cache_hits = 0
        self.input_tokens = 0
        self.output_tokens = 0

    def _cache_path(self, target: str, system: str, user: str, schema: dict):
        # 対象＋モデル＋プロンプト全文＋スキーマのハッシュ。1文字でも変われば別キャッシュ
        raw = json.dumps([target, self.model, system, user, schema], ensure_ascii=False)
        key = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
        return config.CACHE_DIR / self.step / f"{key}.json"

    def is_cached(self, target: str, system: str, user: str, schema: dict) -> bool:
        """同じ入力の応答がキャッシュにあるか（あれば課金なし）。"""
        return self._cache_path(target, system, user, schema).exists()

    def chat_json(self, target: str, system: str, user: str, schema: dict) -> dict | None:
        """JSONで応答を受け取る。失敗したら None（errors.csv に記録済み）。"""
        path = self._cache_path(target, system, user, schema)
        if path.exists():
            with self._lock:
                self.cache_hits += 1
            return json.loads(path.read_text(encoding="utf-8"))["result"]

        from openai import RateLimitError

        errors = rate_limits = 0
        last_error = ""
        while errors < config.LLM_MAX_RETRIES:
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    temperature=config.LLM_TEMPERATURE,
                    messages=[{"role": "system", "content": system},
                              {"role": "user", "content": user}],
                    response_format={"type": "json_schema", "json_schema": {
                        "name": "result", "strict": True, "schema": schema}},
                )
                with self._lock:
                    self.api_calls += 1
                    self.input_tokens += resp.usage.prompt_tokens
                    self.output_tokens += resp.usage.completion_tokens
                result = json.loads(resp.choices[0].message.content)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"target": target, "model": self.model, "result": result},
                                           ensure_ascii=False, indent=1), encoding="utf-8")
                return result
            except RateLimitError as e:
                # レート制限：通常の再試行回数には数えず、長めに待つ
                rate_limits += 1
                last_error = f"RateLimitError: {e}"
                if rate_limits > config.LLM_RATE_LIMIT_MAX_RETRIES:
                    break
                time.sleep(config.LLM_RATE_LIMIT_WAIT_SEC * rate_limits)
            except Exception as e:  # 通信エラー・JSON不正などは通常の再試行
                errors += 1
                last_error = f"{type(e).__name__}: {e}"
                tqdm.write(f"  エラー（{errors}回目）{target}: {last_error[:120]}")
                if errors < config.LLM_MAX_RETRIES:
                    time.sleep(config.LLM_RETRY_WAIT_SEC * errors)
        with self._lock:
            io_utils.append_error(self.step, target, last_error)
        return None

    def chat_json_many(self, requests: list[tuple[str, str, str, dict]]) -> list[dict | None]:
        """(target, system, user, schema) の一覧を並列に送る。結果は requests と同じ順番で返す。"""
        results: list[dict | None] = [None] * len(requests)
        with ThreadPoolExecutor(max_workers=config.LLM_WORKERS) as pool:
            futures = {pool.submit(self.chat_json, *r): i for i, r in enumerate(requests)}
            for f in tqdm(as_completed(futures), total=len(futures), desc=f"{self.step} API", unit="件"):
                results[futures[f]] = f.result()
        return results

    def summary_lines(self) -> list[str]:
        """実行ログ用の集計。"""
        usd = cost_usd(self.model, self.input_tokens, self.output_tokens)
        return [
            f"モデル: {self.model} / API呼び出し: {self.api_calls} 回 / キャッシュ利用: {self.cache_hits} 件",
            f"トークン: 入力 {self.input_tokens} / 出力 {self.output_tokens} / 費用: {format_cost(usd)}",
        ]
