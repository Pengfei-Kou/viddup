"""
Result formatting: Rich terminal output and JSON report generation.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from viddup.core.comparator import DuplicateGroup

console = Console()


# ── Formatting helpers ────────────────────────────────────────────────────────

def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} PB"


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ── Terminal output ───────────────────────────────────────────────────────────

def print_scan_header(scan_paths: tuple[Path, ...], total_videos: int) -> None:
    paths_str = ", ".join(str(p) for p in scan_paths)
    console.print(
        Panel.fit(
            f"[bold cyan]🔍 VidDup — 视频重复检测器[/]\n"
            f"[dim]📂 扫描目录: {paths_str}[/]\n"
            f"[dim]📹 发现视频: {total_videos} 个[/]",
            border_style="cyan",
        )
    )


def print_dry_run_list(paths: list[Path]) -> None:
    console.print(f"\n[yellow]⚠️  Dry-run 模式 — 将处理以下 {len(paths)} 个文件（不写入数据库）:[/]")
    for p in paths:
        console.print(f"  [dim]{p}[/]")


def print_groups(
    exact_groups: list[DuplicateGroup],
    similar_groups: list[DuplicateGroup],
) -> None:
    """Print all duplicate groups to the terminal with Rich formatting."""

    def _print_group(group: DuplicateGroup, label: str) -> None:
        sim_pct = f"{group.similarity * 100:.1f}%"
        header = (
            f"[bold]重复组 #{group.group_id}[/]  "
            f"相似度: [green]{sim_pct}[/]  "
            f"可释放: [yellow]{_human_size(group.reclaimable_size)}[/]"
        )
        table = Table(box=box.SIMPLE, show_header=True, header_style="bold dim")
        table.add_column("文件", style="cyan", no_wrap=False)
        table.add_column("大小", justify="right")
        table.add_column("时长", justify="right")
        table.add_column("分辨率", justify="right")
        table.add_column("编码", justify="right")
        table.add_column("", justify="left")

        for rec in group.records:
            is_keep = rec.path == group.suggested_keep.path
            keep_tag = "[bold green]← 建议保留[/]" if is_keep else ""
            table.add_row(
                str(Path(rec.path).name),
                _human_size(rec.file_size),
                _fmt_duration(rec.duration),
                rec.resolution,
                rec.codec or "?",
                keep_tag,
            )

        console.print(Panel(table, title=header, border_style="dim", expand=False))

    if exact_groups:
        console.print("\n[bold red]⚡ 精确重复[/]")
        for g in exact_groups:
            _print_group(g, "exact")

    if similar_groups:
        console.print("\n[bold yellow]🎯 近似重复[/]")
        for g in similar_groups:
            _print_group(g, "similar")


def print_summary(
    exact_groups: list[DuplicateGroup],
    similar_groups: list[DuplicateGroup],
    cached_count: int,
    computed_count: int,
    error_count: int,
    report_path: Path | None,
) -> None:
    exact_reclaim = sum(g.reclaimable_size for g in exact_groups)
    sim_reclaim = sum(g.reclaimable_size for g in similar_groups)

    console.print("\n[bold]📊 扫描汇总[/]")
    console.print(f"  使用缓存: [green]{cached_count}[/] 个")
    console.print(f"  新增指纹: [cyan]{computed_count}[/] 个")
    if error_count:
        console.print(f"  [red]处理失败: {error_count} 个[/]")
    console.print(
        f"  精确重复组: [bold]{len(exact_groups)}[/] 组，"
        f"可释放空间: [yellow]{_human_size(exact_reclaim)}[/]"
    )
    console.print(
        f"  近似重复组: [bold]{len(similar_groups)}[/] 组，"
        f"可释放空间: [yellow]{_human_size(sim_reclaim)}[/]"
    )
    if report_path:
        console.print(f"\n[dim]📄 详细报告已保存: {report_path}[/]")


# ── JSON report ───────────────────────────────────────────────────────────────

def _group_to_dict(group: DuplicateGroup) -> dict[str, Any]:
    return {
        "group_id": group.group_id,
        "similarity": group.similarity,
        "suggested_keep": group.suggested_keep.path,
        "reclaimable_bytes": group.reclaimable_size,
        "files": [
            {
                "path": r.path,
                "size": r.file_size,
                "duration": r.duration,
                "resolution": r.resolution,
                "codec": r.codec,
                "file_hash": r.file_hash,
            }
            for r in group.records
        ],
    }


def write_json_report(
    scan_paths: tuple[Path, ...],
    total_videos: int,
    exact_groups: list[DuplicateGroup],
    similar_groups: list[DuplicateGroup],
    output_dir: Path,
) -> Path:
    """Write a JSON report and return its path."""
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_path = output_dir / f"viddup_report_{timestamp}.json"

    from viddup import __version__

    report = {
        "viddup_version": __version__,
        "scan_time": datetime.now(UTC).isoformat(),
        "scan_paths": [str(p) for p in scan_paths],
        "total_videos": total_videos,
        "exact_duplicate_groups": [_group_to_dict(g) for g in exact_groups],
        "similar_duplicate_groups": [_group_to_dict(g) for g in similar_groups],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    return report_path
