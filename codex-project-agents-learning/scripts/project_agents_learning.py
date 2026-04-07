"""项目会话汇总。

首次运行全量扫描项目所有 transcript ，后续运行扫描 transcript 增量状态，并写出本轮`memory-candidates.json` 候选汇总。
- 首次运行扫描当前项目的 `sessions` 和 `archived_sessions`
- 后续运行只扫描 `sessions`
- 仅聚合本次新增或发生变化的 session
"""  # noqa: INP001

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, Literal, cast

type JsonObject = dict[str, object]
type TurnRole = Literal["user", "assistant"]

INDEX_VERSION: Final[int] = 5
INDEX_FILENAME: Final[str] = "agents-learning-index.json"
CANDIDATES_FILENAME: Final[str] = "memory-candidates.json"


@dataclass(slots=True)
class StatePaths:
    """保存项目状态文件路径."""

    state_dir: Path
    index: Path
    candidates: Path


@dataclass(slots=True)
class TranscriptTurn:
    """表示一条可见对话消息."""

    role: TurnRole
    timestamp: str | None
    text: str
    phase: str | None = None

    def to_json(self) -> JsonObject:
        """转换为可序列化字典.

        Returns:
            当前消息对应的 JSON 字典.

        """
        payload: JsonObject = {
            "role": self.role,
            "timestamp": self.timestamp,
            "text": self.text,
        }
        if self.phase:
            payload["phase"] = self.phase
        return payload


@dataclass(slots=True)
class CommentaryBlock:
    """表示一段连续 assistant commentary."""

    start_timestamp: str | None
    end_timestamp: str | None
    steps: list[str]

    def to_json(self) -> JsonObject:
        """转换为可序列化字典.

        Returns:
            当前 commentary 块对应的 JSON 字典.

        """
        return {
            "role": "assistant",
            "phase": "commentary",
            "start_timestamp": self.start_timestamp,
            "end_timestamp": self.end_timestamp,
            "steps": self.steps,
        }


def iso_now() -> str:
    """返回当前 UTC ISO 时间戳.

    Returns:
        带 `Z` 后缀的 UTC ISO 时间戳.

    """
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_path(path: str | Path) -> Path:
    """返回规范化绝对路径.

    Returns:
        展开并规范化后的绝对路径.

    """
    candidate = Path(path).expanduser()
    try:
        return candidate.resolve(strict=False)
    except OSError:
        return candidate.absolute()


def path_key(path: str | Path) -> str:
    """返回用于大小写无关比较的路径键.

    Returns:
        适合做路径比较的字符串键.

    """
    return str(canonical_path(path)).casefold()


def path_text(path: str | Path) -> str:
    """返回规范路径字符串.

    Returns:
        规范路径的字符串形式.

    """
    return str(canonical_path(path))


def object_dict(value: object) -> JsonObject:
    """将值收窄为字典.

    Returns:
        字典值, 否则返回空字典.

    """
    if isinstance(value, dict):
        return cast("JsonObject", value)
    return {}


def object_list(value: object) -> list[object]:
    """将值收窄为列表.

    Returns:
        列表值, 否则返回空列表.

    """
    if isinstance(value, list):
        return cast("list[object]", value)
    return []


def record_list(value: object) -> list[JsonObject]:
    """从列表中过滤出字典记录.

    Returns:
        仅包含字典项的列表.

    """
    return [cast("JsonObject", item) for item in object_list(value) if isinstance(item, dict)]


def string_value(value: object) -> str | None:
    """将值收窄为字符串.

    Returns:
        字符串值, 否则返回 `None`.

    """
    if isinstance(value, str):
        return value
    return None


def normalize_message_text(value: object) -> str | None:
    """规范 transcript 文本中的换行符.

    Returns:
        规范后的文本; 空白文本返回 `None`.

    """
    text = string_value(value)
    if text is None:
        return None
    normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized_text.strip():
        return None
    return normalized_text


def int_value(value: object) -> int | None:
    """将值收窄为整数.

    Returns:
        整数值, 否则返回 `None`.

    """
    if isinstance(value, int):
        return value
    return None


def is_relative_to(child: str | Path, parent: str | Path) -> bool:
    """判断子路径是否位于父路径之下.

    Returns:
        若 `child` 位于 `parent` 之下则返回 `True`.

    """
    parent_key = path_key(parent)
    child_path = canonical_path(child)
    return any(path_key(candidate) == parent_key for candidate in (child_path, *child_path.parents))


def find_codex_home(override: str | None) -> Path:
    """解析 Codex home 目录.

    Returns:
        显式参数, 环境变量或默认目录对应的路径.

    """
    if override:
        return canonical_path(override)
    env_value = os.environ.get("CODEX_HOME")
    if env_value:
        return canonical_path(env_value)
    return canonical_path(Path.home() / ".codex")


def state_dir_for_project(project_root: Path) -> Path:
    """返回项目状态目录.

    Returns:
        项目下 `.agents/state` 的路径.

    """
    return project_root / ".agents" / "state"


def state_paths(project_root: Path) -> StatePaths:
    """构造项目状态文件路径集合.

    Returns:
        包含状态目录和状态文件路径的结构体.

    """
    state_dir = state_dir_for_project(project_root)
    return StatePaths(
        state_dir=state_dir,
        index=state_dir / INDEX_FILENAME,
        candidates=state_dir / CANDIDATES_FILENAME,
    )


def load_json_file[T](path: Path, default: T) -> T:
    """读取 JSON 文件, 缺失时返回默认值.

    Returns:
        解析后的 JSON 内容, 或传入的默认值.

    """
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return cast("T", json.load(handle))


def write_json_file(path: Path, payload: object) -> None:
    """原子写入 JSON 文件."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(path)


def read_first_json_line(path: Path) -> JsonObject | None:
    """读取 JSONL 首行.

    Returns:
        首行解析出的字典, 失败时返回 `None`.

    """
    try:
        with path.open("r", encoding="utf-8") as handle:
            first_line = handle.readline()
    except OSError:
        return None
    if not first_line.strip():
        return None
    try:
        loaded = json.loads(first_line)
    except json.JSONDecodeError:
        return None
    return object_dict(loaded)


def iter_transcript_files(root: Path) -> Iterable[Path]:
    """遍历目录下的 transcript 文件.

    Returns:
        按路径排序的 transcript 文件序列.

    """
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*.jsonl") if path.is_file())


def discovered_session_record(
    transcript_path: Path,
    source_kind: str,
    cwd: str,
) -> JsonObject:
    """构造扫描阶段使用的 session 记录.

    Returns:
        扫描结果中的 session 记录.

    """
    stat_result = transcript_path.stat()
    return {
        "path": path_text(transcript_path),
        "cwd": path_text(cwd),
        "source": source_kind,
        "mtime_ms": int(stat_result.st_mtime * 1000),
    }


def is_compatible_index(payload: JsonObject) -> bool:
    """判断索引文件是否兼容当前 schema.

    Returns:
        若索引文件兼容当前 schema 则返回 `True`.

    """
    return int_value(payload.get("version")) == INDEX_VERSION and isinstance(payload.get("sessions"), dict)


def discover_sessions(
    project_root: Path,
    codex_home: Path,
    *,
    first_run: bool,
    include_archived: bool,
) -> dict[str, JsonObject]:
    """发现属于当前项目的 transcript.

    Returns:
        发现结果映射.

    """
    search_roots: list[tuple[Path, str]] = [(codex_home / "sessions", "sessions")]
    if include_archived or first_run:
        search_roots.append((codex_home / "archived_sessions", "archived_sessions"))

    discovered: dict[str, JsonObject] = {}
    for root, source_kind in search_roots:
        for transcript_path in iter_transcript_files(root):
            first_record = read_first_json_line(transcript_path)
            if not first_record or first_record.get("type") != "session_meta":
                continue
            payload = object_dict(first_record.get("payload"))
            session_id = string_value(payload.get("id"))
            cwd = string_value(payload.get("cwd"))
            if not session_id or not cwd or not is_relative_to(cwd, project_root):
                continue
            session_record = discovered_session_record(
                transcript_path=transcript_path,
                source_kind=source_kind,
                cwd=cwd,
            )
            existing_record = discovered.get(session_id)
            if existing_record is not None and string_value(existing_record.get("source")) == "sessions":
                continue
            discovered[session_id] = session_record
    return discovered


def refresh_index(
    project_root: Path,
    existing_index: JsonObject,
    discovered_sessions: dict[str, JsonObject],
) -> tuple[JsonObject, list[str]]:
    """刷新 transcript 索引并返回变更集合.

    Returns:
        刷新后的索引负载和需要重处理的路径列表.

    """
    previous_sessions = object_dict(existing_index.get("sessions"))
    changed_paths: list[str] = []
    refreshed_sessions: dict[str, JsonObject] = {}
    for session_id, session_info in discovered_sessions.items():
        previous = object_dict(previous_sessions.get(session_id))
        current_mtime = int_value(session_info.get("mtime_ms"))
        current_cwd = string_value(session_info.get("cwd"))
        current_source = string_value(session_info.get("source"))
        current_path = string_value(session_info.get("path"))
        if current_mtime is None or current_cwd is None or current_source is None:
            continue
        entry: JsonObject = {
            "path": current_path,
            "mtime_ms": current_mtime,
            "cwd": current_cwd,
            "source": current_source,
        }
        extracted_at = string_value(previous.get("extracted_at"))
        if previous.get("mtime_ms") == current_mtime and extracted_at:
            entry["extracted_at"] = extracted_at
        else:
            changed_paths.append(session_id)
        refreshed_sessions[session_id] = entry

    refreshed_index: JsonObject = {
        "version": INDEX_VERSION,
        "project_root": path_text(project_root),
        "last_run_at": iso_now(),
        "sessions": refreshed_sessions,
    }
    return refreshed_index, sorted(changed_paths)


def update_extracted_at(index_payload: JsonObject, session_ids: Iterable[str]) -> None:
    """为已提取 session 写入时间戳."""
    extracted_at = iso_now()
    sessions = object_dict(index_payload.get("sessions"))
    for session_id in session_ids:
        if session_id not in sessions:
            continue
        session_record = object_dict(sessions.get(session_id))
        session_record["extracted_at"] = extracted_at
        sessions[session_id] = session_record
    index_payload["sessions"] = sessions


def transcript_turns(session_path: Path) -> list[TranscriptTurn]:
    """提取 transcript 中的可见 user/assistant 对话.

    Returns:
        当前 transcript 中保留下来的对话 turn 列表.

    """
    turns: list[TranscriptTurn] = []
    with session_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                record = object_dict(json.loads(line))
            except json.JSONDecodeError:
                continue
            if string_value(record.get("type")) != "event_msg":
                continue
            payload = object_dict(record.get("payload"))
            event_type = string_value(payload.get("type"))
            timestamp = string_value(record.get("timestamp"))
            text = normalize_message_text(payload.get("message"))
            if text is None:
                continue
            if event_type == "user_message":
                turns.append(TranscriptTurn(role="user", timestamp=timestamp, text=text))
            elif event_type == "agent_message":
                turns.append(
                    TranscriptTurn(
                        role="assistant",
                        timestamp=timestamp,
                        text=text,
                        phase=string_value(payload.get("phase")),
                    ),
                )
    return turns


def commentary_block_json(turns: list[TranscriptTurn]) -> JsonObject | None:
    """将连续 commentary turn 压缩为单个块.

    Returns:
        压缩后的 commentary 字典; 无有效步骤时返回 `None`.

    """
    steps = [turn.text for turn in turns if turn.text.strip()]
    if not steps:
        return None
    return CommentaryBlock(
        start_timestamp=turns[0].timestamp,
        end_timestamp=turns[-1].timestamp,
        steps=steps,
    ).to_json()


def compressed_transcript(turns: list[TranscriptTurn]) -> list[JsonObject]:
    """将原始 turn 列表压缩为学习候选使用的 transcript.

    Returns:
        压缩后的 transcript 条目列表.

    """
    compressed_items: list[JsonObject] = []
    pending_commentary: list[TranscriptTurn] = []

    def flush_commentary() -> None:
        if not pending_commentary:
            return
        commentary_json = commentary_block_json(pending_commentary)
        pending_commentary.clear()
        if commentary_json is not None:
            compressed_items.append(commentary_json)

    for turn in turns:
        if turn.role == "assistant" and turn.phase == "commentary":
            pending_commentary.append(turn)
            continue
        flush_commentary()
        compressed_items.append(turn.to_json())

    flush_commentary()
    return compressed_items


def first_user_timestamp(session_entry: JsonObject) -> str:
    """返回 session 中第一条 user 消息时间.

    Returns:
        第一条 user 消息的时间戳; 不存在时返回空字符串.

    """
    for item in record_list(session_entry.get("transcript")):
        if string_value(item.get("role")) != "user":
            continue
        timestamp = string_value(item.get("timestamp"))
        if timestamp:
            return timestamp
    return ""


def build_session_summary(session_id: str, session_info: JsonObject) -> JsonObject | None:
    """构造单个 session 的聚合结果.

    Returns:
        单个 session 的聚合字典, 或 `None`.

    """
    transcript_path_text = string_value(session_info.get("path"))
    if transcript_path_text is None:
        return None
    transcript_path = canonical_path(transcript_path_text)
    first_record = read_first_json_line(transcript_path)
    if not first_record or first_record.get("type") != "session_meta":
        return None
    payload = object_dict(first_record.get("payload"))
    turns = compressed_transcript(transcript_turns(transcript_path))
    return {
        "session_path": path_text(transcript_path),
        "session_id": session_id,
        "cwd": string_value(payload.get("cwd")) or string_value(session_info.get("cwd")),
        "transcript": turns,
    }


def sorted_session_entries(session_map: dict[str, JsonObject]) -> list[JsonObject]:
    """按时间和路径排序 session 条目.

    Returns:
        排序后的 session 条目列表.

    """
    return sorted(
        session_map.values(),
        key=lambda session: (
            first_user_timestamp(session),
            string_value(session.get("session_path")) or "",
        ),
    )


def transcript_items_total(session_entries: list[JsonObject]) -> int:
    """统计聚合后的 transcript 条目数.

    Returns:
        所有 session 中 transcript 条目的总数.

    """
    return sum(len(record_list(session.get("transcript"))) for session in session_entries)


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """为命令行解析器添加公共参数."""
    parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived session transcripts in this run.",
    )
    parser.add_argument(
        "--stdout-json",
        action="store_true",
        help="Print the command result as JSON.",
    )


def create_parser() -> argparse.ArgumentParser:
    """创建命令行解析器.

    Returns:
        配置完成的命令行解析器.

    """
    parser = argparse.ArgumentParser(description="Project Agents Learning helper")
    add_common_arguments(parser)
    return parser


def resolve_project_root() -> Path:
    """解析当前项目根目录.

    Returns:
        当前工作目录对应的项目根路径.

    """
    return canonical_path(Path.cwd())


def run_refresh(args: argparse.Namespace) -> JsonObject:
    """执行完整刷新流程.

    Returns:
        本次刷新的摘要信息.

    """
    project_root = resolve_project_root()
    paths = state_paths(project_root)
    existing_index = load_json_file(paths.index, default={})
    first_run = not is_compatible_index(existing_index)
    codex_home = find_codex_home(None)
    discovered_sessions = discover_sessions(
        project_root=project_root,
        codex_home=codex_home,
        first_run=first_run,
        include_archived=args.include_archived,
    )
    refreshed_index, changed_paths = refresh_index(
        project_root=project_root,
        existing_index=existing_index if not first_run else {},
        discovered_sessions=discovered_sessions,
    )

    sessions_to_reprocess = {session_id for session_id in changed_paths if session_id in discovered_sessions}
    extracted_successfully: set[str] = set()
    extract_failures = 0
    aggregated_sessions: list[JsonObject] = []
    for session_id in sorted(sessions_to_reprocess):
        session_info = object_dict(discovered_sessions.get(session_id))
        summary = build_session_summary(session_id, session_info)
        if summary is not None:
            aggregated_sessions.append(summary)
            extracted_successfully.add(session_id)
            continue
        extract_failures += 1

    aggregated_sessions = sorted_session_entries(
        {string_value(session.get("session_id")) or "": session for session in aggregated_sessions},
    )
    candidates_payload: JsonObject = {
        "project_root": path_text(project_root),
        "sessions": aggregated_sessions,
    }

    update_extracted_at(refreshed_index, extracted_successfully)
    write_json_file(paths.index, refreshed_index)
    write_json_file(paths.candidates, candidates_payload)

    return {
        "project_root": path_text(project_root),
        "codex_home": path_text(codex_home),
        "state_dir": path_text(paths.state_dir),
        "first_run": first_run,
        "sessions_discovered": len(discovered_sessions),
        "sessions_processed": len(sessions_to_reprocess),
        "sessions_extracted": len(extracted_successfully),
        "sessions_failed": extract_failures,
        "sessions_aggregated": len(aggregated_sessions),
        "transcript_items_aggregated": transcript_items_total(aggregated_sessions),
        "index_path": path_text(paths.index),
        "candidates_path": path_text(paths.candidates),
    }


def emit_result(result: JsonObject, *, stdout_json: bool) -> None:
    """输出命令结果."""
    if stdout_json:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return
    for key, value in result.items():
        if isinstance(value, dict):
            rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
        elif isinstance(value, list):
            rendered = json.dumps(value, ensure_ascii=False)
        else:
            rendered = str(value)
        print(f"{key}: {rendered}")


def main(argv: list[str] | None = None) -> int:
    """运行命令行入口.

    Returns:
        进程退出码.

    """
    parser = create_parser()
    args = parser.parse_args(argv)
    result = run_refresh(args)
    emit_result(result, stdout_json=args.stdout_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
