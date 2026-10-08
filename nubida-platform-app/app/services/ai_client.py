"""
누비다 AI — 자체 LLM 클라이언트 (Ollama OPENAI 호환 API)

- 외부 API(OpenRouter 등) 사용 금지 — 자체 LLM(RTX 3080 서버) 전제
- 기본 엔드포인트: http://<LLM_HOST>:11434/v1  (Ollama OPENAI 호환)
- 설정은 환경변수로 주입 (서버 접근 정보 수신 후 .env/docker-compose에 반영)
  - LLM_BASE_URL : 예) http://192.168.0.10:11434/v1  (기본 http://localhost:11434/v1)
  - LLM_MODEL    : 예) exaone3.0:7.8b (기본)
  - LLM_TIMEOUT  : 초 단위 (기본 60)
- 의존성 최소화: stdlib urllib만 사용 (httpx/aiohttp 미설치 환경 대응),
  네트워크 호출은 asyncio.to_thread로 블로킹 방지
"""
import asyncio
import json
import os
import queue
import threading
import urllib.error
import urllib.request

from app.core.config import settings

# 설정 우선순위: 환경변수 > .env(pydantic-settings) > 기본값
LLM_BASE_URL = settings.LLM_BASE_URL
LLM_MODEL = settings.LLM_MODEL
LLM_TIMEOUT = settings.LLM_TIMEOUT


class LlmUnavailableError(RuntimeError):
    """자체 LLM 서버에 연결할 수 없음 (서버 미기동/주소 미설정)"""


def _http_post_json(url: str, payload: dict, timeout: int) -> dict:
    """동기 urllib POST — to_thread로 감싸서 호출할 것"""
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        raise LlmUnavailableError(f"LLM HTTP {e.code}: {body}") from e
    except Exception as e:  # 연결 실패/타임아웃 등
        raise LlmUnavailableError(f"LLM 연결 실패: {e}") from e


async def chat(
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 512,
) -> dict:
    """
    채팅 완성 요청 → {content, model, tokens_in, tokens_out}
    messages: [{"role": "system"|"user"|"assistant", "content": str}, ...]

    ⚠️ reasoning_effort="none" — qwen3 thinking 토큰 비활성화.
       유지 시 180초 백엔드 타임아웃을 초과해 503이 발생한다 (실측 확인).
    """
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
        "reasoning_effort": "none",
    }
    data = await asyncio.to_thread(
        _http_post_json, f"{LLM_BASE_URL}/chat/completions", payload, LLM_TIMEOUT
    )
    try:
        choice = data["choices"][0]["message"]
        content = choice.get("content", "")
        usage = data.get("usage", {})
        return {
            "content": content,
            "model": data.get("model", LLM_MODEL),
            "tokens_in": usage.get("prompt_tokens", 0),
            "tokens_out": usage.get("completion_tokens", 0),
        }
    except (KeyError, IndexError) as e:
        raise LlmUnavailableError(f"LLM 응답 형식 오류: {str(data)[:200]}") from e


def _iter_sse_lines(url: str, payload: dict, timeout: int):
    """
    동기 urllib 스트리밍 — SSE(data: {...}) 라인을 하나씩 yield
    to_thread로 감싸지 말고, 스레드에서 직접 소비할 것 (제너레이터는 to_thread 불가)
    """
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "text/event-stream"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if body == "[DONE]":
                    break
                try:
                    yield json.loads(body)
                except Exception:
                    continue
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        raise LlmUnavailableError(f"LLM HTTP {e.code}: {body}") from e
    except Exception as e:  # 연결 실패/타임아웃 등
        raise LlmUnavailableError(f"LLM 연결 실패: {e}") from e


def _stream_worker(url: str, payload: dict, timeout: int, q: "queue.Queue"):
    """별도 스레드에서 SSE를 읽어 큐에 넣는다. 끝나면 None을 넣어 종료를 알린다."""
    try:
        for obj in _iter_sse_lines(url, payload, timeout):
            q.put(("chunk", obj))
        q.put(("done", None))
    except LlmUnavailableError as e:
        q.put(("error", str(e)))
    except Exception as e:  # pragma: no cover
        q.put(("error", f"LLM 스트리밍 오류: {e}"))


async def stream_chat(
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 2048,
):
    """
    채팅 스트리밍 → async generator of {"type": "delta"|"done"|"error", ...}
      - delta: {"text": str}            (토큰 조각)
      - done : {"model","tokens_in","tokens_out"}
      - error: {"message": str}

    stdlib만 사용: 별도 스레드 + queue로 블로킹 urllib을 감싼다.

    ⚠️ reasoning_effort="none" 필수
       qwen3 계열은 기본적으로 'thinking' 토큰을 먼저 생성한다.
       실측: thinking ON → 첫 토큰 35.7초 / OFF → 0.87초 (약 40배 개선)
       답변 품질은 동일하며, 학생 안내문에는 추론 과정이 불필요하다.
    """
    payload = {
        "model": LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
        "reasoning_effort": "none",   # ← thinking 비활성 (체감 대기 대폭 단축)
    }
    q: "queue.Queue" = queue.Queue()
    # 스트리밍은 '연결 유지'이므로 읽기 타임아웃을 넉넉히 (LLM_TIMEOUT이 짧아도 안전)
    stream_timeout = max(LLM_TIMEOUT, 600)
    worker = threading.Thread(
        target=_stream_worker,
        args=(f"{LLM_BASE_URL}/chat/completions", payload, stream_timeout, q),
        daemon=True,
    )
    worker.start()

    model_used = LLM_MODEL
    tokens_out = 0
    got_any = False

    while True:
        kind, payload_item = await asyncio.to_thread(q.get)
        if kind == "done":
            yield {"type": "done", "model": model_used,
                   "tokens_in": 0, "tokens_out": tokens_out}
            return
        if kind == "error":
            yield {"type": "error", "message": payload_item}
            return
        # chunk
        obj = payload_item
        if obj.get("model"):
            model_used = obj["model"]
        choices = obj.get("choices") or [{}]
        delta = choices[0].get("delta") or {}
        piece = delta.get("content")
        if piece:
            got_any = True
            tokens_out += 1
            yield {"type": "delta", "text": piece}
        usage = obj.get("usage") or {}
        if usage.get("completion_tokens"):
            tokens_out = usage["completion_tokens"]
        if not got_any and choices[0].get("finish_reason") == "stop":
            # 빈 응답도 종료로 처리
            pass


async def embed(text: str) -> list[float]:
    """
    텍스트 임베딩 (RAG용) — 로컬 모델(bge-m3 등) 사용
    실패 시 빈 리스트 반환 (호출부에서 키워드 fallback)
    """
    payload = {"model": os.environ.get("LLM_EMBED_MODEL", "bge-m3"), "prompt": text}
    try:
        data = await asyncio.to_thread(
            _http_post_json, f"{LLM_BASE_URL}/embeddings", payload, min(LLM_TIMEOUT, 30)
        )
        return data.get("embedding", [])
    except LlmUnavailableError:
        return []


async def health() -> dict:
    """Ollama /api/tags — 서버 기동 여부 (스켈레톤: 상태 확인용)"""
    try:
        data = await asyncio.to_thread(
            _http_post_json, f"{LLM_BASE_URL.replace('/v1', '')}/api/tags", {}, 5
        )
        models = [m.get("name") for m in data.get("models", [])]
        return {"ok": True, "models": models}
    except LlmUnavailableError as e:
        return {"ok": False, "error": str(e)}
