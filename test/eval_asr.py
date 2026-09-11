#!/usr/bin/env python3
"""独立 ASR 评测：对 trainsets 中指定训练集逐条转写，并与 reference.csv 比对。

比对时忽略标点、空白，并对英文做大小写不敏感处理（全角会先规范成半角）。

示例（仓库根目录，使用本仓库 .venv）：

    .venv\\Scripts\\python.exe test\\eval_asr.py --list
    .venv\\Scripts\\python.exe test\\eval_asr.py test1
    .venv\\Scripts\\python.exe test\\eval_asr.py --trainset test1 --base-url http://127.0.0.1:8000
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
TRAINSETS_DIR = TEST_DIR / "trainsets"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
TRANSCRIBE_PATH = "/api/v1/asr/transcribe"
HEALTH_PATH = "/api/v1/asr/health"

# 额外去掉的符号（部分符号 Unicode 分类不是 P，但不应算识别错误）
_EXTRA_IGNORE = set("·•・℃°…—–‐‑‒―‑_~`^|\\/<>=")


@dataclass
class Sample:
    sid: str
    grade: str
    filename: str
    audio_path: Path
    reference_text: str
    source: str


@dataclass
class SampleResult:
    sample: Sample
    hypothesis: str
    raw_text: str
    cost_ms: int | None
    error: str
    passed: bool
    cer: float
    norm_ref: str
    norm_hyp: str
    diff: str


def _enable_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
            except Exception:
                pass


def _enable_windows_ansi() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        handle = ctypes.windll.kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            ctypes.windll.kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


def color(text: str, code: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def normalize_for_compare(text: str) -> str:
    """去掉标点/空白后用于比对。英文大小写不敏感。"""
    folded = unicodedata.normalize("NFKC", text or "")
    kept: list[str] = []
    for ch in folded:
        if ch in _EXTRA_IGNORE or ch.isspace():
            continue
        category = unicodedata.category(ch)
        if category.startswith("P") or category.startswith("Z") or category == "Cc":
            continue
        kept.append(ch)
    return "".join(kept).casefold()


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            insert = curr[j - 1] + 1
            delete = prev[j] + 1
            replace = prev[j - 1] + (0 if ca == cb else 1)
            curr.append(min(insert, delete, replace))
        prev = curr
    return prev[-1]


def character_error_rate(ref: str, hyp: str) -> float:
    if not ref and not hyp:
        return 0.0
    if not ref:
        return 1.0
    return levenshtein(ref, hyp) / len(ref)


def format_diff(ref: str, hyp: str) -> str:
    if ref == hyp:
        return "(无差异)"
    parts: list[str] = []
    matcher = SequenceMatcher(a=ref, b=hyp, autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            parts.append(ref[i1:i2])
        elif op == "delete":
            parts.append(f"[-{ref[i1:i2]}-]")
        elif op == "insert":
            parts.append(f"[+{hyp[j1:j2]}+]")
        else:
            parts.append(f"[-{ref[i1:i2]}-][+{hyp[j1:j2]}+]")
    return "".join(parts)


def list_trainsets() -> list[str]:
    if not TRAINSETS_DIR.is_dir():
        return []
    names: list[str] = []
    for child in sorted(TRAINSETS_DIR.iterdir()):
        if child.is_dir() and (child / "reference.csv").is_file():
            names.append(child.name)
    return names


def load_samples(trainset: str) -> list[Sample]:
    dataset_dir = TRAINSETS_DIR / trainset
    ref_path = dataset_dir / "reference.csv"
    if not dataset_dir.is_dir():
        available = "、".join(list_trainsets()) or "(无)"
        raise SystemExit(f"找不到训练集：{trainset}\n可用训练集：{available}")
    if not ref_path.is_file():
        raise SystemExit(f"训练集缺少 reference.csv：{ref_path}")

    samples: list[Sample] = []
    with ref_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"id", "filename", "reference_text"}
        fieldnames = {name.strip() for name in (reader.fieldnames or [])}
        missing = required - fieldnames
        if missing:
            raise SystemExit(f"reference.csv 缺少列：{', '.join(sorted(missing))}")
        for row_no, row in enumerate(reader, start=2):
            sid = (row.get("id") or "").strip()
            filename = (row.get("filename") or "").strip() or (f"{sid}.wav" if sid else "")
            reference_text = (row.get("reference_text") or "").strip()
            if not sid or not filename:
                raise SystemExit(f"{ref_path} 第 {row_no} 行缺少 id 或 filename")
            audio_path = dataset_dir / filename
            if not audio_path.is_file():
                raise SystemExit(f"缺少音频文件：{audio_path}")
            samples.append(
                Sample(
                    sid=sid,
                    grade=(row.get("grade") or "").strip(),
                    filename=filename,
                    audio_path=audio_path,
                    reference_text=reference_text,
                    source=(row.get("source") or "").strip(),
                )
            )
    if not samples:
        raise SystemExit(f"reference.csv 为空：{ref_path}")
    return samples


def _guess_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".flac": "audio/flac",
        ".ogg": "audio/ogg",
        ".webm": "audio/webm",
        ".opus": "audio/opus",
    }.get(suffix, "application/octet-stream")


def post_audio(url: str, audio_path: Path, timeout: float) -> dict[str, object]:
    boundary = "----VoiceRecEvalBoundary"
    filename = audio_path.name
    content_type = _guess_content_type(audio_path)
    header = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode("utf-8")
    footer = f"\r\n--{boundary}--\r\n".encode("utf-8")
    body = header + audio_path.read_bytes() + footer
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore").strip()[-400:]
        raise RuntimeError(f"HTTP {exc.code}：{detail or exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接评测接口（{url}）：{exc.reason}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("接口返回了无法解析的内容") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("接口返回格式不是 JSON 对象")
    return payload


def check_health(base_url: str, timeout: float) -> dict[str, object]:
    url = base_url.rstrip("/") + HEALTH_PATH
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=min(timeout, 8)) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"健康检查失败 HTTP {exc.code}：{url}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"无法连接 FastAPI（{base_url}）。请先启动后端和 Xinference。\n原因：{exc.reason}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"健康检查返回无法解析的内容：{url}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("健康检查返回格式异常")
    return payload


def evaluate_sample(sample: Sample, transcribe_url: str, timeout: float) -> SampleResult:
    error = ""
    hypothesis = ""
    raw_text = ""
    cost_ms: int | None = None
    try:
        payload = post_audio(transcribe_url, sample.audio_path, timeout)
        hypothesis = str(payload.get("text") or "").strip()
        raw_text = str(payload.get("raw_text") or "").strip()
        cost_raw = payload.get("cost_ms")
        if isinstance(cost_raw, int):
            cost_ms = cost_raw
        elif isinstance(cost_raw, float):
            cost_ms = int(cost_raw)
        if not hypothesis and not raw_text:
            error = "接口未返回识别文本"
    except Exception as exc:
        error = str(exc)

    norm_ref = normalize_for_compare(sample.reference_text)
    norm_hyp = normalize_for_compare(hypothesis)
    passed = not error and norm_ref == norm_hyp
    cer = 1.0 if error else character_error_rate(norm_ref, norm_hyp)
    diff = error or format_diff(norm_ref, norm_hyp)
    return SampleResult(
        sample=sample,
        hypothesis=hypothesis,
        raw_text=raw_text,
        cost_ms=cost_ms,
        error=error,
        passed=passed,
        cer=cer,
        norm_ref=norm_ref,
        norm_hyp=norm_hyp,
        diff=diff,
    )


def print_header(trainset: str, count: int, base_url: str, health: dict[str, object]) -> None:
    print("=" * 72)
    print(f"ASR 评测    训练集: {trainset}")
    print(f"参考文件: {TRAINSETS_DIR / trainset / 'reference.csv'}")
    print(f"接口:     {base_url.rstrip('/')}{TRANSCRIBE_PATH}")
    print(f"模型:     {health.get('asr_model', '-')}")
    print(f"样本数:   {count}")
    print("比对规则: 忽略标点 / 空白 / 全半角差异，英文大小写不敏感")
    print("=" * 72)
    print()


def print_sample(index: int, total: int, result: SampleResult) -> None:
    sample = result.sample
    if result.error:
        badge = color("ERROR", "31;1")
    elif result.passed:
        badge = color("PASS", "32;1")
    else:
        badge = color("FAIL", "31;1")
    grade = f" {sample.grade}级" if sample.grade else ""
    cost = f"  {result.cost_ms}ms" if result.cost_ms is not None else ""
    cer_text = "" if result.passed and not result.error else f"  CER={result.cer:.1%}"
    print(f"[{index}/{total}] {sample.sid}{grade}  {badge}{cer_text}{cost}  {sample.filename}")
    print(f"  参考: {sample.reference_text}")
    if result.error:
        print(f"  错误: {result.error}")
    else:
        print(f"  识别: {result.hypothesis or '(空)'}")
        if result.raw_text and result.raw_text != result.hypothesis:
            print(f"  原始: {result.raw_text}")
        if not result.passed:
            print(f"  归一化参考: {result.norm_ref or '(空)'}")
            print(f"  归一化识别: {result.norm_hyp or '(空)'}")
            print(f"  差异: {result.diff}")
    print()


def print_summary(results: list[SampleResult]) -> int:
    total = len(results)
    passed = sum(1 for item in results if item.passed)
    failed = sum(1 for item in results if not item.passed and not item.error)
    errored = sum(1 for item in results if item.error)
    mean_cer = sum(item.cer for item in results) / total if total else 0.0

    by_grade: dict[str, list[SampleResult]] = {}
    for item in results:
        key = item.sample.grade or "-"
        by_grade.setdefault(key, []).append(item)

    print("-" * 72)
    print("汇总")
    print(f"  通过: {passed}/{total}  ({(passed / total if total else 0):.1%})")
    print(f"  失败: {failed}")
    print(f"  错误: {errored}")
    print(f"  平均 CER（忽略标点/空白）: {mean_cer:.1%}")
    if by_grade:
        parts = []
        for grade in sorted(by_grade):
            group = by_grade[grade]
            ok = sum(1 for item in group if item.passed)
            parts.append(f"{grade} {ok}/{len(group)}")
        print(f"  按等级: {'  '.join(parts)}")

    mismatches = [item for item in results if not item.passed]
    if mismatches:
        print()
        print("未通过条目")
        for item in mismatches:
            status = "ERROR" if item.error else "FAIL"
            print(f"  - {item.sample.sid} [{status}] {item.diff}")
    print("=" * 72)
    return 0 if passed == total else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="对 test/trainsets 下指定训练集做 ASR 识别，并与 reference.csv 比对。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python test/eval_asr.py --list\n"
            "  python test/eval_asr.py test1\n"
            "  python test/eval_asr.py --trainset test1 --base-url http://127.0.0.1:8000\n"
        ),
    )
    parser.add_argument(
        "trainset",
        nargs="?",
        help="trainsets 目录下的训练集名称，例如 test1",
    )
    parser.add_argument(
        "--trainset",
        dest="trainset_opt",
        help="与位置参数相同，指定训练集名称",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出可用训练集后退出",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("ASR_API_URL", DEFAULT_BASE_URL),
        help=f"FastAPI 根地址，默认 {DEFAULT_BASE_URL}",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("ASR_TIMEOUT_SECONDS", "60")),
        help="单条转写超时秒数，默认 60",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _enable_utf8_stdio()
    _enable_windows_ansi()
    args = parse_args(argv)
    trainset = (args.trainset_opt or args.trainset or "").strip()

    available = list_trainsets()
    if args.list or not trainset:
        print("可用训练集：")
        if not available:
            print("  (test/trainsets 下没有带 reference.csv 的目录)")
            return 1
        for name in available:
            ref_file = TRAINSETS_DIR / name / "reference.csv"
            with ref_file.open("r", encoding="utf-8-sig", newline="") as handle:
                sample_count = max(sum(1 for _ in csv.DictReader(handle)), 0)
            print(f"  {name}  ({sample_count} 条)")
        if args.list:
            return 0
        print("\n请指定训练集，例如：python test/eval_asr.py test1")
        return 2

    samples = load_samples(trainset)
    health = check_health(args.base_url, args.timeout)
    transcribe_url = args.base_url.rstrip("/") + TRANSCRIBE_PATH
    print_header(trainset, len(samples), args.base_url, health)

    results: list[SampleResult] = []
    for index, sample in enumerate(samples, start=1):
        result = evaluate_sample(sample, transcribe_url, args.timeout)
        results.append(result)
        print_sample(index, len(samples), result)
        sys.stdout.flush()

    return print_summary(results)


if __name__ == "__main__":
    raise SystemExit(main())
