"""本地 Jina embedding 与可选大模型 API 辅助研判。

中文注释：这里不做实时主判断，只基于规则融合摘要异步生成解释性文本。所有网络 /
本地服务请求都使用标准库，避免新增依赖。
"""

from __future__ import annotations

import json
import math
import os
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Callable

try:
    from ..rules.detection_fusion import DetectionSummary, ai_fallback_text
except ImportError:  # 兼容 cd upper_computer 后直接 python main.py
    if __package__ and __package__.startswith("upper_computer"):
        raise
    from rules.detection_fusion import DetectionSummary, ai_fallback_text  # type: ignore


_APP_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SERVER_PATH = _APP_DIR / "runtime" / "llama-server.exe"
DEFAULT_MODEL_PATH = _APP_DIR / "models" / "v5-nano-retrieval-Q4_K_M.gguf"
DEFAULT_JINA_URL = "http://127.0.0.1:18081"
DEFAULT_EMBEDDING_MODEL = "jina-embeddings-v5-text-nano-retrieval"
DEFAULT_TIMEOUT = 12.0
DOWNLOAD_TIMEOUT = 60.0
ZHIPU_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
ZHIPU_MODEL_PRESETS = ("glm-5.1", "glm-5-turbo", "glm-4.5", "glm-4.5-air")
_PACKAGE_SERVER_MEMBER = "runtime/llama-server.exe"
_PACKAGE_MODEL_MEMBER = "models/v5-nano-retrieval-Q4_K_M.gguf"
LLAMA_RELEASE_API_URL = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
JINA_GGUF_DOWNLOAD_URL = (
    "https://huggingface.co/jinaai/jina-embeddings-v5-text-nano-retrieval-GGUF/resolve/main/"
    "v5-nano-retrieval-Q4_K_M.gguf"
)
ProgressCallback = Callable[[dict[str, Any]], None]


@dataclass(slots=True)
class AISettings:
    enabled: bool = True
    embedding_enabled: bool = True
    llama_server_path: str = str(DEFAULT_SERVER_PATH)
    jina_model_path: str = str(DEFAULT_MODEL_PATH)
    jina_base_url: str = DEFAULT_JINA_URL
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    llm_enabled: bool = False
    llm_provider: str = "zhipu_glm"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    save_api_key: bool = False

    def copy(self) -> "AISettings":
        return replace(self)


class LocalJinaRuntime:
    """管理由上位机启动的 llama-server 进程。"""

    def __init__(self) -> None:
        self._process: subprocess.Popen[str] | None = None

    def start(self, settings: AISettings) -> str:
        if self._process is not None and self._process.poll() is None:
            return "本地 Jina 服务已在运行"

        server_path = Path(settings.llama_server_path)
        model_path = Path(settings.jina_model_path)
        if not server_path.exists():
            raise FileNotFoundError(f"未找到 llama-server：{server_path}")
        if not model_path.exists():
            raise FileNotFoundError(f"未找到 Jina GGUF 模型：{model_path}")

        host, port = _host_port(settings.jina_base_url)
        command = [
            str(server_path),
            "-m",
            str(model_path),
            "--embedding",
            "--pooling",
            "last",
            "--host",
            host,
            "--port",
            str(port),
        ]
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._process = subprocess.Popen(  # noqa: S603 - 路径来自用户配置，且不经 shell。
            command,
            cwd=str(server_path.parent),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=creationflags,
        )
        return f"本地 Jina 服务启动中：{settings.jina_base_url}"

    def stop(self) -> str:
        if self._process is None:
            return "没有由上位机启动的本地 Jina 服务"
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None
        return "本地 Jina 服务已停止"

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None


def load_ai_settings() -> AISettings:
    path = ai_settings_path()
    if not path.exists():
        return AISettings()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AISettings()
    return settings_from_dict(payload)


def save_ai_settings(settings: AISettings) -> Path:
    path = ai_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(settings)
    if not settings.save_api_key:
        payload["llm_api_key"] = ""
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def ai_settings_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "EchoGuard" / "ai_settings.json"
    return Path.home() / ".echoguard" / "ai_settings.json"


def settings_from_dict(payload: dict[str, Any]) -> AISettings:
    values = asdict(AISettings())
    for key in values:
        if key in payload:
            values[key] = payload[key]
    for key in ("enabled", "embedding_enabled", "llm_enabled", "save_api_key"):
        values[key] = bool(values[key])
    values["llm_provider"] = _normalize_provider(str(values.get("llm_provider") or ""), values)
    values["llm_model"] = _normalize_model(str(values.get("llm_model") or ""), values["llm_provider"])
    values["llm_base_url"] = _normalize_base_url(str(values.get("llm_base_url") or ""), values["llm_provider"])
    return AISettings(**values)


def run_ai_judgement(settings: AISettings, summary: DetectionSummary) -> dict[str, Any]:
    """执行一次异步 AI 辅助研判，返回可直接进入 DataManager 快照的字典。"""

    result = _base_result(settings, summary)
    if not settings.enabled or not settings.embedding_enabled or not summary.participant_ids:
        result["text"] = ai_fallback_text(summary.status)
        result["status"] = "规则回退"
        return result

    try:
        matches = match_with_jina(settings, summary.summary_text)
    except Exception as exc:  # noqa: BLE001 - AI 辅助失败不能影响主判断。
        result["text"] = ai_fallback_text(summary.status)
        result["status"] = "本地 Jina 不可用，使用规则回退"
        result["error"] = str(exc)
        return result

    result["top_matches"] = matches
    result["source"] = "local_jina"
    result["status"] = "本地 Jina 模式匹配完成"
    result["text"] = _local_match_text(summary, matches)

    if settings.llm_enabled and settings.llm_base_url and settings.llm_model:
        try:
            llm_text = generate_llm_explanation(settings, summary, matches)
        except Exception as exc:  # noqa: BLE001
            result["error"] = str(exc)
            return result
        result["source"] = "llm_api"
        result["status"] = "大模型辅助解释完成"
        result["text"] = llm_text

    return result


def test_embedding(settings: AISettings, text: str = "EchoGuard AI 辅助研判测试") -> dict[str, Any]:
    vectors = embed_texts(settings, [text])
    vector = vectors[0] if vectors else []
    return {
        "dimension": len(vector),
        "preview": vector[:5],
    }


def wait_for_embedding_ready(settings: AISettings, timeout: float = 24.0) -> dict[str, Any]:
    """轮询 embedding endpoint，直到本地服务可用或超时。"""

    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        try:
            return test_embedding(settings)
        except Exception as exc:  # noqa: BLE001 - 这里需要把最后一次失败原因带回 UI。
            last_error = str(exc)
            time.sleep(0.7)
    raise RuntimeError(f"本地 Jina 服务未就绪：{last_error or '等待超时'}")


def jina_deployment_status(settings: AISettings) -> dict[str, Any]:
    """检查本地 Jina 运行时与 GGUF 模型是否已经部署到当前配置路径。"""

    server_path = Path(settings.llama_server_path or DEFAULT_SERVER_PATH).expanduser()
    model_path = Path(settings.jina_model_path or DEFAULT_MODEL_PATH).expanduser()
    server_exists = server_path.exists()
    model_exists = model_path.exists()
    host, port = _host_port(settings.jina_base_url)
    port_open = _is_tcp_port_open(host, port)
    deployed = server_exists and model_exists
    missing: list[str] = []
    if not server_exists:
        missing.append("llama-server.exe")
    if not model_exists:
        missing.append("Jina GGUF 模型")
    if deployed:
        service_text = "服务端口可连接" if port_open else "服务端口未启动"
        message = f"已部署：本地 Jina 运行时和 GGUF 模型均存在；{service_text}"
    else:
        message = f"未部署：缺少{'、'.join(missing)}"
    return {
        "deployed": deployed,
        "port_open": port_open,
        "server_path": str(server_path),
        "model_path": str(model_path),
        "endpoint": f"{settings.jina_base_url.rstrip('/')}/v1/embeddings",
        "message": message,
    }


def deploy_jina_package(
    settings: AISettings,
    package_path: str,
    overwrite: bool = True,
) -> dict[str, Any]:
    """从 EchoGuard-AI-Runtime.zip 离线包部署 llama-server 与 Jina GGUF。"""

    if not str(package_path or "").strip():
        raise RuntimeError("请先选择 EchoGuard-AI-Runtime.zip 离线包")
    source = Path(package_path).expanduser()
    if not source.exists():
        raise FileNotFoundError(f"未找到离线包：{source}")
    if not source.is_file() or not zipfile.is_zipfile(source):
        raise RuntimeError("请选择有效的 EchoGuard-AI-Runtime.zip 离线包")

    server_target = Path(settings.llama_server_path or DEFAULT_SERVER_PATH).expanduser()
    model_target = Path(settings.jina_model_path or DEFAULT_MODEL_PATH).expanduser()
    if server_target == Path(DEFAULT_SERVER_PATH) and model_target == Path(DEFAULT_MODEL_PATH):
        server_target = DEFAULT_SERVER_PATH
        model_target = DEFAULT_MODEL_PATH

    with zipfile.ZipFile(source) as archive:
        server_member = _find_package_member(archive, _PACKAGE_SERVER_MEMBER)
        model_member = _find_package_member(archive, _PACKAGE_MODEL_MEMBER)
        missing: list[str] = []
        if server_member is None:
            missing.append(_PACKAGE_SERVER_MEMBER)
        if model_member is None:
            missing.append(_PACKAGE_MODEL_MEMBER)
        if missing:
            raise RuntimeError(f"离线包结构不完整，缺少：{', '.join(missing)}")

        copied: list[str] = []
        for member, target in ((server_member, server_target), (model_member, model_target)):
            if target.exists() and not overwrite:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as src, target.open("wb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    dst.write(chunk)
            copied.append(target.name)

    status_settings = settings.copy()
    status_settings.llama_server_path = str(server_target)
    status_settings.jina_model_path = str(model_target)
    status = jina_deployment_status(status_settings)
    if not status["deployed"]:
        raise RuntimeError("部署完成后仍未检测到关键文件，请检查目标目录权限")
    status.update(
        {
            "copied": copied,
            "message": "已部署：本地 Jina 运行时和 GGUF 模型已就绪",
        }
    )
    return status


def online_deploy_jina(
    settings: AISettings,
    progress: ProgressCallback | None = None,
    overwrite: bool = False,
    llama_release_api_url: str = LLAMA_RELEASE_API_URL,
    jina_model_url: str = JINA_GGUF_DOWNLOAD_URL,
) -> dict[str, Any]:
    """在线下载 Windows CPU x64 llama-server 与 Jina GGUF，并部署到当前配置路径。"""

    server_target = Path(settings.llama_server_path or DEFAULT_SERVER_PATH).expanduser()
    model_target = Path(settings.jina_model_path or DEFAULT_MODEL_PATH).expanduser()
    copied: list[str] = []
    skipped: list[str] = []

    with tempfile.TemporaryDirectory(prefix="echoguard-ai-") as tmp:
        temp_root = Path(tmp)

        if server_target.exists() and not overwrite:
            skipped.append("llama-server.exe")
            _emit_progress(
                progress,
                phase="skip",
                current_file="llama-server.exe",
                message="llama-server.exe 已存在，跳过下载",
                server_path=str(server_target),
                model_path=str(model_target),
            )
        else:
            _emit_progress(progress, phase="resolve", current_file="llama.cpp release", message="正在获取 llama.cpp 最新版本")
            asset = resolve_llama_server_asset(llama_release_api_url)
            server_zip = temp_root / "llama-server-win-cpu-x64.zip"
            _download_file(asset["url"], server_zip, progress, asset["name"])
            _emit_progress(progress, phase="extract", current_file="llama-server.exe", message="正在解压 llama-server.exe")
            with zipfile.ZipFile(server_zip) as archive:
                member = _find_package_member(archive, "llama-server.exe")
                if member is None:
                    raise RuntimeError("llama.cpp 压缩包内未找到 llama-server.exe")
                server_target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, server_target.open("wb") as dst:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        dst.write(chunk)
            copied.append("llama-server.exe")

        if model_target.exists() and not overwrite:
            skipped.append(model_target.name)
            _emit_progress(
                progress,
                phase="skip",
                current_file=model_target.name,
                message=f"{model_target.name} 已存在，跳过下载",
                server_path=str(server_target),
                model_path=str(model_target),
            )
        else:
            _emit_progress(progress, phase="download", current_file=model_target.name, message="正在下载 Jina GGUF 模型")
            model_target.parent.mkdir(parents=True, exist_ok=True)
            temp_model = temp_root / model_target.name
            _download_file(jina_model_url, temp_model, progress, model_target.name)
            shutil.move(str(temp_model), str(model_target))
            copied.append(model_target.name)

    status_settings = settings.copy()
    status_settings.llama_server_path = str(server_target)
    status_settings.jina_model_path = str(model_target)
    status = jina_deployment_status(status_settings)
    if not status["deployed"]:
        raise RuntimeError("在线部署完成后仍未检测到关键文件，请检查网络和目标目录权限")
    if copied and skipped:
        message = f"在线部署完成：新增 {', '.join(copied)}；已存在 {', '.join(skipped)}"
    elif copied:
        message = f"在线部署完成：{', '.join(copied)} 已就绪"
    else:
        message = "在线部署完成：运行时和模型已存在"
    status.update({"copied": copied, "skipped": skipped, "message": message})
    return status


def create_jina_offline_package(settings: AISettings, package_path: str) -> dict[str, Any]:
    """把当前已部署的本地 Jina 运行时与模型打包成离线 zip。"""

    if not str(package_path or "").strip():
        raise RuntimeError("请先选择离线包保存路径")
    server_path = Path(settings.llama_server_path or DEFAULT_SERVER_PATH).expanduser()
    model_path = Path(settings.jina_model_path or DEFAULT_MODEL_PATH).expanduser()
    if not server_path.exists():
        raise FileNotFoundError(f"未找到 llama-server：{server_path}")
    if not model_path.exists():
        raise FileNotFoundError(f"未找到 Jina GGUF 模型：{model_path}")

    target = Path(package_path).expanduser()
    if target.suffix.lower() != ".zip":
        target = target.with_suffix(".zip")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(server_path, _PACKAGE_SERVER_MEMBER)
        archive.write(model_path, _PACKAGE_MODEL_MEMBER)
    return {
        "deployed": True,
        "package_path": str(target),
        "server_path": str(server_path),
        "model_path": str(model_path),
        "message": f"离线包已生成：{target}",
    }


def resolve_llama_server_asset(release_api_url: str = LLAMA_RELEASE_API_URL) -> dict[str, str]:
    """从 llama.cpp 最新 release 中选择 Windows CPU x64 二进制包。"""

    data = _request_json("GET", release_api_url, timeout=DEFAULT_TIMEOUT)
    assets = data.get("assets", [])
    if not isinstance(assets, list):
        raise RuntimeError("GitHub release 响应缺少 assets")
    for item in assets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        url = str(item.get("browser_download_url") or "")
        if name.startswith("llama-") and name.endswith("-bin-win-cpu-x64.zip") and url:
            return {"name": name, "url": url}
    raise RuntimeError("未在 llama.cpp 最新 release 中找到 Windows CPU x64 运行时")


def match_with_jina(settings: AISettings, summary_text: str) -> list[dict[str, Any]]:
    inputs = [summary_text] + [template["text"] for template in _TEMPLATES]
    vectors = embed_texts(settings, inputs)
    if len(vectors) < len(inputs):
        raise RuntimeError("embedding 返回数量不足")
    current = vectors[0]
    matches: list[dict[str, Any]] = []
    for template, vector in zip(_TEMPLATES, vectors[1:], strict=False):
        matches.append(
            {
                "label": template["label"],
                "advice": template["advice"],
                "score": round(_cosine(current, vector), 4),
            }
        )
    return sorted(matches, key=lambda item: item["score"], reverse=True)[:3]


def embed_texts(settings: AISettings, texts: list[str]) -> list[list[float]]:
    payload = {
        "model": settings.embedding_model or DEFAULT_EMBEDDING_MODEL,
        "input": texts,
    }
    data = _request_json(
        "POST",
        _join_url(settings.jina_base_url, "/v1/embeddings"),
        payload=payload,
        timeout=DEFAULT_TIMEOUT,
    )
    items = data.get("data", [])
    vectors: list[list[float]] = []
    for item in items:
        embedding = item.get("embedding")
        if isinstance(embedding, list):
            vectors.append([float(value) for value in embedding])
    if not vectors:
        raise RuntimeError("本地 Jina 服务未返回 embedding 向量")
    return vectors


def fetch_llm_models(settings: AISettings) -> list[str]:
    return list(fetch_llm_models_result(settings).get("models") or [])


def fetch_llm_models_result(settings: AISettings) -> dict[str, Any]:
    settings = settings.copy()
    settings.llm_provider = _normalize_provider(settings.llm_provider, asdict(settings))
    settings.llm_base_url = _normalize_base_url(settings.llm_base_url, settings.llm_provider)
    if settings.llm_provider == "zhipu_glm":
        return {
            "models": list(ZHIPU_MODEL_PRESETS),
            "endpoint": _join_url(settings.llm_base_url, "/models", provider=settings.llm_provider),
            "http_status": None,
            "provider": settings.llm_provider,
            "real_request": False,
            "model_source": "preset",
            "message": "智谱官方模型列表使用预设模型 ID，请选择后测试 API",
        }

    data, status, endpoint = _request_json_result(
        "GET",
        _join_url(settings.llm_base_url, "/v1/models", provider=settings.llm_provider),
        api_key=settings.llm_api_key,
        timeout=DEFAULT_TIMEOUT,
    )
    models = data.get("data", [])
    names = [str(item.get("id")) for item in models if isinstance(item, dict) and item.get("id")]
    return {
        "models": names,
        "endpoint": endpoint,
        "http_status": status,
        "provider": settings.llm_provider,
        "real_request": True,
        "model_source": "api",
        "message": f"真实请求成功：GET {endpoint}",
    }


def test_llm(settings: AISettings) -> str:
    return str(test_llm_result(settings).get("content") or "")


def test_llm_result(settings: AISettings) -> dict[str, Any]:
    if not settings.llm_model:
        raise RuntimeError("请先填写或选择大模型名称")
    settings = settings.copy()
    settings.llm_provider = _normalize_provider(settings.llm_provider, asdict(settings))
    settings.llm_base_url = _normalize_base_url(settings.llm_base_url, settings.llm_provider)
    settings.llm_model = _normalize_model(settings.llm_model, settings.llm_provider)
    content, status, endpoint = _chat_completion_result(
        settings,
        [
            {"role": "system", "content": "你是上位机 AI 辅助研判测试助手，只输出一句中文。"},
            {"role": "user", "content": "请回复：AI 接口测试通过。"},
        ],
        max_tokens=80,
    )
    return {
        "content": _sanitize_ai_text(content),
        "endpoint": endpoint,
        "http_status": status,
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "real_request": True,
    }


def generate_llm_explanation(
    settings: AISettings,
    summary: DetectionSummary,
    matches: list[dict[str, Any]],
) -> str:
    match_text = "\n".join(
        f"- {item['label']}，score={float(item['score']):.2f}，建议：{item['advice']}"
        for item in matches
    )
    user_text = (
        f"规则判断：{summary.status}\n"
        f"参与节点：{', '.join(summary.participant_labels) or '无'}\n"
        f"触发节点：{', '.join(summary.triggered_labels) or '无'}\n"
        f"时间窗口：最近 {summary.window_seconds:.0f} 秒\n"
        f"Jina 相似模式：\n{match_text}\n"
        f"结构化摘要：\n{summary.summary_text}\n\n"
        "请输出一句谨慎的 AI 辅助研判，最多 45 个中文字符，不能写确认生命。"
    )
    content = _chat_completion(
        settings,
        [
            {
                "role": "system",
                "content": "你是灾后救援上位机的辅助研判模块。只做解释和建议，不做确认生命结论。",
            },
            {"role": "user", "content": user_text},
        ],
        max_tokens=140,
    )
    text = _sanitize_ai_text(content)
    if not text.startswith("AI辅助研判："):
        text = f"AI辅助研判：{text}"
    return text


def _chat_completion(settings: AISettings, messages: list[dict[str, str]], max_tokens: int) -> str:
    content, _status, _endpoint = _chat_completion_result(settings, messages, max_tokens)
    return content


def _chat_completion_result(
    settings: AISettings,
    messages: list[dict[str, str]],
    max_tokens: int,
) -> tuple[str, int, str]:
    settings = settings.copy()
    settings.llm_provider = _normalize_provider(settings.llm_provider, asdict(settings))
    settings.llm_base_url = _normalize_base_url(settings.llm_base_url, settings.llm_provider)
    settings.llm_model = _normalize_model(settings.llm_model, settings.llm_provider)
    payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    data, status, endpoint = _request_json_result(
        "POST",
        _join_url(settings.llm_base_url, "/v1/chat/completions", provider=settings.llm_provider),
        payload=payload,
        api_key=settings.llm_api_key,
        timeout=DEFAULT_TIMEOUT,
    )
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError("大模型 API 未返回 choices")
    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    content = message.get("content") if isinstance(message, dict) else ""
    if not content:
        raise RuntimeError("大模型 API 未返回文本内容")
    return str(content).strip(), status, endpoint


def _base_result(settings: AISettings, summary: DetectionSummary) -> dict[str, Any]:
    return {
        "enabled": settings.enabled,
        "running": False,
        "status": "等待 AI 分析",
        "text": ai_fallback_text(summary.status),
        "source": "rule_fallback",
        "window_start": summary.window_start,
        "window_end": summary.window_end,
        "updated_at": time.time(),
        "top_matches": [],
        "error": "",
        "state_key": summary.state_key,
    }


def _local_match_text(summary: DetectionSummary, matches: list[dict[str, Any]]) -> str:
    if not matches:
        return ai_fallback_text(summary.status)
    best = matches[0]
    score = float(best.get("score") or 0.0)
    return f"AI辅助研判：本地模式匹配为“{best['label']}”({score * 100:.0f}%)，{best['advice']}"


def _sanitize_ai_text(text: str) -> str:
    cleaned = " ".join(str(text or "").replace("\n", " ").split())
    replacements = {
        "确认生命体征": "疑似生命微动",
        "确认生命": "疑似生命",
        "已判定有人": "提示存在疑似目标",
        "确定有人": "提示存在疑似目标",
        "实时检测生命": "辅助解释微动特征",
    }
    for old, new in replacements.items():
        cleaned = cleaned.replace(old, new)
    return cleaned.strip("` \t")


def _request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    api_key: str = "",
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    data, _status, _url = _request_json_result(method, url, payload, api_key, timeout)
    return data


def _request_json_result(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    api_key: str = "",
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[dict[str, Any], int, str]:
    body = None
    headers = {"Accept": "application/json", "User-Agent": "EchoGuard-AI-Runtime/1.0"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - 用户配置的本地/兼容 API。
            raw = response.read().decode("utf-8", errors="replace")
            status = int(getattr(response, "status", 200))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        hint = _http_error_hint(exc.code, detail)
        raise RuntimeError(f"HTTP {exc.code}: {hint} {detail[:240]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"请求失败：{exc.reason}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"响应不是 JSON：{raw[:160]}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("响应 JSON 顶层不是对象")
    return data, status, url


def _download_file(
    url: str,
    target: Path,
    progress: ProgressCallback | None,
    current_file: str,
) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "EchoGuard-AI-Runtime/1.0"})
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:  # noqa: S310 - 官方下载源。
            total_text = response.headers.get("Content-Length") or "0"
            total = int(total_text) if total_text.isdigit() else 0
            downloaded = 0
            with target.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    downloaded += len(chunk)
                    percent = int(downloaded * 100 / total) if total else 0
                    _emit_progress(
                        progress,
                        phase="download",
                        current_file=current_file,
                        downloaded_bytes=downloaded,
                        total_bytes=total,
                        percent=percent,
                        message=_download_message(current_file, downloaded, total),
                    )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"下载失败 HTTP {exc.code}：{current_file} {detail[:180]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"下载失败：{current_file} {exc.reason}") from exc


def _download_message(current_file: str, downloaded: int, total: int) -> str:
    if total:
        return f"正在下载 {current_file}：{_format_bytes(downloaded)} / {_format_bytes(total)}"
    return f"正在下载 {current_file}：{_format_bytes(downloaded)}"


def _format_bytes(value: int) -> str:
    size = float(max(0, value))
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def _emit_progress(progress: ProgressCallback | None, **payload: Any) -> None:
    if progress is not None:
        progress(dict(payload))


def _join_url(base_url: str, path: str, provider: str = "openai_compatible") -> str:
    base = (base_url or "").rstrip("/")
    if not base:
        raise RuntimeError("API 地址为空")
    if provider == "zhipu_glm":
        if path.startswith("/v1/"):
            path = path[3:]
        return base + path
    if path.startswith("/v1/") and base.endswith("/v1"):
        path = path[3:]
    return base + path


def _find_package_member(archive: zipfile.ZipFile, expected_suffix: str) -> str | None:
    expected = expected_suffix.replace("\\", "/").lower()
    for name in archive.namelist():
        normalized = name.replace("\\", "/").strip("/")
        if normalized.endswith("/") or normalized.lower().endswith("__macosx"):
            continue
        if normalized.lower().endswith(expected):
            return name
    return None


def _normalize_provider(provider: str, values: dict[str, Any]) -> str:
    value = str(provider or "").strip()
    if value in {"zhipu_glm", "openai_compatible", "custom"}:
        return value
    model = str(values.get("llm_model") or "").lower().replace(" ", "")
    base_url = str(values.get("llm_base_url") or "").lower()
    if "glm" in model or "bigmodel.cn" in base_url:
        return "zhipu_glm"
    return "openai_compatible"


def _normalize_base_url(base_url: str, provider: str) -> str:
    value = str(base_url or "").strip().rstrip("/")
    if provider == "zhipu_glm":
        parsed = urllib.parse.urlparse(value)
        if parsed.hostname in {"127.0.0.1", "localhost"}:
            return value
        if not value or "bigmodel.cn" not in value:
            return ZHIPU_BASE_URL
        if value.endswith("/api/paas/v4"):
            return value
        if value.endswith("/v4"):
            return value
        return ZHIPU_BASE_URL
    return value


def _normalize_model(model: str, provider: str) -> str:
    value = str(model or "").strip()
    if provider == "zhipu_glm":
        compact = value.lower().replace(" ", "-").replace("_", "-")
        aliases = {
            "glm-5.1": "glm-5.1",
            "glm5.1": "glm-5.1",
            "glm-5-turbo": "glm-5-turbo",
            "glm5-turbo": "glm-5-turbo",
        }
        return aliases.get(compact, compact or "glm-5.1")
    return value


def _http_error_hint(code: int, detail: str) -> str:
    lowered = detail.lower()
    if code in {401, 403}:
        return "鉴权失败，请检查 API Key。"
    if code == 404:
        return "接口或模型不存在，请检查 API 地址和模型 ID。"
    if "quota" in lowered or "余额" in detail or "insufficient" in lowered:
        return "额度或余额不足。"
    if code >= 500:
        return "服务端异常。"
    return ""


def _host_port(base_url: str) -> tuple[str, int]:
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 18081
    return host, port


def _is_tcp_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.35):
            return True
    except OSError:
        return False


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    size = min(len(left), len(right))
    dot = sum(left[index] * right[index] for index in range(size))
    left_norm = math.sqrt(sum(left[index] * left[index] for index in range(size)))
    right_norm = math.sqrt(sum(right[index] * right[index] for index in range(size)))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


_TEMPLATES = (
    {
        "label": "多节点疑似生命微动",
        "text": "多个节点在同一时间窗口内出现较高 presence 和 confidence，形成交叉支持，疑似稳定生命微动。",
        "advice": "建议继续采集并重点观察触发节点区域",
    },
    {
        "label": "单节点局部扰动",
        "text": "只有单个节点出现异常微动响应，其余节点缺少支持，可能是局部扰动或数据不足。",
        "advice": "建议等待更多节点参与交叉验证",
    },
    {
        "label": "低置信或信号弱",
        "text": "节点 confidence 偏低或 RSSI 较弱，样本稳定性不足，暂不宜形成明确结论。",
        "advice": "建议检查节点链路并延长采集时间",
    },
    {
        "label": "未检测到稳定微动",
        "text": "多节点 presence 和 motion 均未形成持续高响应，当前未检测到稳定微动特征。",
        "advice": "建议保持采集并关注后续状态变化",
    },
    {
        "label": "无有效数据",
        "text": "最近窗口内缺少有效 Gateway 串口样本，无法进行多节点融合判断。",
        "advice": "建议连接 Gateway 后继续采集",
    },
)
