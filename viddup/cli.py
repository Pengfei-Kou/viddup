"""
VidDup CLI entry point.

Commands:
  scan    Scan directories for duplicate videos
  status  Show database cache statistics
  clear   Clear the fingerprint cache
"""
from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

from viddup import __version__
from viddup.config import (
    DEFAULT_DB_PATH,
    DEFAULT_DURATION_TOL,
    DEFAULT_FRAMES,
    DEFAULT_THRESHOLD,
    DEFAULT_WORKERS,
    Config,
)
from viddup.utils.ffmpeg_utils import check_ffmpeg

console = Console()
err_console = Console(stderr=True, style="red")


# ── Root group ────────────────────────────────────────────────────────────────

@click.group()
@click.version_option(__version__, prog_name="viddup")
def main() -> None:
    """VidDup — Fast, local video duplicate detector.

    Scan directories for exact and near-duplicate video files using
    multi-layer fingerprinting (file hash + metadata + perceptual hash).
    """


# ── scan ──────────────────────────────────────────────────────────────────────

@main.command()
@click.argument(
    "directories",
    nargs=-1,
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--threshold", "-t",
    default=DEFAULT_THRESHOLD,
    show_default=True,
    help="Similarity threshold (0.0–1.0). Videos above this score are flagged.",
)
@click.option(
    "--frames", "-f",
    default=DEFAULT_FRAMES,
    show_default=True,
    help="Number of frames to sample per video for perceptual hashing.",
)
@click.option(
    "--duration-tol",
    default=DEFAULT_DURATION_TOL,
    show_default=True,
    help="Relative duration tolerance for L2 pre-filter (e.g. 0.05 = ±5%).",
)
@click.option(
    "--db",
    "db_path",
    default=DEFAULT_DB_PATH,
    show_default=True,
    type=click.Path(path_type=Path),
    help="Path to the SQLite fingerprint database.",
)
@click.option(
    "--workers", "-w",
    default=DEFAULT_WORKERS,
    show_default=True,
    help="Number of parallel worker processes.",
)
@click.option(
    "--output", "-o",
    "output_dir",
    default=None,
    type=click.Path(path_type=Path),
    help="Directory to write reports. Defaults to the first scanned directory.",
)
@click.option(
    "--no-cache",
    is_flag=True,
    default=False,
    help="Ignore cached fingerprints and recompute everything.",
)
@click.option(
    "--recursive/--no-recursive",
    default=True,
    show_default=True,
    help="Recursively scan subdirectories.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="List files that would be processed without writing to the database.",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="Show per-file progress details.",
)
@click.option(
    "--html/--no-html",
    default=True,
    show_default=True,
    help="Generate an interactive HTML report (default: on).",
)
@click.option(
    "--open/--no-open",
    "open_browser",
    default=True,
    show_default=True,
    help="Auto-open the HTML report in the browser after scan.",
)
def scan(
    directories: tuple[Path, ...],
    threshold: float,
    frames: int,
    duration_tol: float,
    db_path: Path,
    workers: int,
    output_dir: Path,
    no_cache: bool,
    recursive: bool,
    dry_run: bool,
    verbose: bool,
    html: bool,
    open_browser: bool,
) -> None:
    """Scan DIRECTORIES for duplicate videos.

    Supports multiple directories:

      viddup scan ~/Movies ~/Downloads/Videos

    Results are printed to the terminal and saved as a JSON report.
    """
    # ── Validate ffmpeg ───────────────────────────────────────────────────────
    ok, msg = check_ffmpeg()
    if not ok:
        err_console.print(f"[bold red]Error:[/] {msg}")
        sys.exit(1)

    # ── Resolve output directory ──────────────────────────────────────────────
    resolved_output = output_dir if output_dir is not None else directories[0]

    # ── Build Config ──────────────────────────────────────────────────────────
    try:
        cfg = Config(
            scan_paths=directories,
            db_path=db_path,
            threshold=threshold,
            frames=frames,
            duration_tol=duration_tol,
            workers=workers,
            output_dir=resolved_output,
            recursive=recursive,
            no_cache=no_cache,
            dry_run=dry_run,
            verbose=verbose,
        )
    except ValueError as e:
        err_console.print(f"[bold red]Invalid option:[/] {e}")
        sys.exit(1)

    # ── Imports (lazy to keep startup fast) ───────────────────────────────────
    from viddup.core.comparator import find_duplicates
    from viddup.core.fingerprinter import generate_fingerprints
    from viddup.core.reporter import (
        print_dry_run_list,
        print_groups,
        print_scan_header,
        print_summary,
        write_json_report,
    )
    from viddup.core.scanner import scan_directories

    # ── Scan ──────────────────────────────────────────────────────────────────
    scan_result = scan_directories(cfg.scan_paths, recursive=cfg.recursive)
    video_paths = scan_result.paths
    print_scan_header(cfg.scan_paths, len(video_paths))
    if scan_result.ignored_count:
        console.print(
            f"  [dim]🚫 已过滤 {scan_result.ignored_count} 个文件"
            f"（.viddup_ignore 来自: "
            f"{', '.join(str(s) for s in scan_result.ignore_sources)}）[/]"
        )

    if not video_paths:
        console.print("[yellow]No video files found.[/]")
        return

    if dry_run:
        print_dry_run_list(video_paths)
        return

    # ── Fingerprint ───────────────────────────────────────────────────────────
    cached_count = 0
    computed_count = 0
    error_count = 0

    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TaskProgressColumn,
        TimeElapsedColumn,
    )

    with Progress(
        SpinnerColumn(),
        "[progress.description]{task.description}",
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            "[cyan]🔬 生成指纹...", total=len(video_paths)
        )

        def on_progress(path: Path, from_cache: bool, error: str | None) -> None:
            nonlocal cached_count, computed_count, error_count
            if error:
                error_count += 1
                if verbose:
                    console.print(f"  [red]✗[/] {path.name}: {error}")
            elif from_cache:
                cached_count += 1
            else:
                computed_count += 1
            progress.advance(task)

        fp_results = generate_fingerprints(
            video_paths,
            db_path=cfg.db_path,
            num_frames=cfg.frames,
            workers=cfg.workers,
            no_cache=cfg.no_cache,
            progress_callback=on_progress,
        )

    # ── Compare ───────────────────────────────────────────────────────────────
    console.print("[cyan]🎯 比较相似度...[/]")
    valid_records = [r.record for r in fp_results if r.error is None]
    exact_groups, similar_groups = find_duplicates(
        valid_records,
        threshold=cfg.threshold,
        duration_tol=cfg.duration_tol,
    )

    # ── Report ────────────────────────────────────────────────────────────────
    print_groups(exact_groups, similar_groups)

    json_path: Path | None = None
    html_path: Path | None = None

    if exact_groups or similar_groups:
        json_path = write_json_report(
            cfg.scan_paths, len(video_paths), exact_groups, similar_groups, cfg.output_dir,
        )
        if html:
            from viddup.core.html_reporter import write_html_report as write_html
            console.print("[dim]📄 生成 HTML 报告（含缩略图）...[/]")
            html_path = write_html(
                cfg.scan_paths, len(video_paths), exact_groups, similar_groups, cfg.output_dir,
            )

    print_summary(
        exact_groups, similar_groups, cached_count, computed_count, error_count, json_path,
    )

    if html_path:
        console.print(f"[cyan]🌐 HTML 报告已保存: {html_path}[/]")
        if open_browser:
            import webbrowser
            webbrowser.open(html_path.resolve().as_uri())


# ── status ────────────────────────────────────────────────────────────────────

@main.command()
@click.option(
    "--db",
    "db_path",
    default=DEFAULT_DB_PATH,
    show_default=True,
    type=click.Path(path_type=Path),
    help="Path to the SQLite fingerprint database.",
)
def status(db_path: Path) -> None:
    """Show fingerprint database statistics."""
    from viddup.core.database import Database

    if not db_path.exists():
        console.print(f"[yellow]Database not found:[/] {db_path}")
        return

    with Database(db_path) as db:
        count = db.count()
        size = db.db_size_bytes()
        latest = db.latest_indexed_at()
        orphan_count = sum(
            1 for r in db.get_all() if not Path(r.path).exists()
        )

    console.print("\n[bold]📊 VidDup 数据库状态[/]")
    console.print(f"  路径:         {db_path}")
    console.print(f"  已缓存视频:  [green]{count}[/] 个")
    console.print(f"  孤儿记录:    [{'red' if orphan_count else 'green'}]{orphan_count}[/] 个")
    console.print(f"  数据库大小:  {size / 1024:.1f} KB")
    console.print(f"  最近索引:    {latest or '—'}")
    if orphan_count:
        console.print(
            "\n[dim]提示: 运行 `viddup clear --orphans-only` 清理孤儿记录[/]"
        )


# ── clear ─────────────────────────────────────────────────────────────────────

@main.command()
@click.option(
    "--db",
    "db_path",
    default=DEFAULT_DB_PATH,
    show_default=True,
    type=click.Path(path_type=Path),
    help="Path to the SQLite fingerprint database.",
)
@click.option(
    "--orphans-only",
    is_flag=True,
    default=False,
    help="Only delete records whose files no longer exist.",
)
@click.option(
    "--confirm",
    is_flag=True,
    default=False,
    help="Skip confirmation prompt.",
)
def clear(db_path: Path, orphans_only: bool, confirm: bool) -> None:
    """Clear the fingerprint cache database."""
    from viddup.core.database import Database

    if not db_path.exists():
        console.print(f"[yellow]Database not found:[/] {db_path}")
        return

    if orphans_only:
        with Database(db_path) as db:
            deleted = db.purge_orphans()
        console.print(f"[green]✓[/] 已清理 {deleted} 条孤儿记录。")
        return

    if not confirm:
        click.confirm(
            f"确认清空整个数据库 {db_path}？此操作不可撤销。",
            abort=True,
        )

    with Database(db_path) as db:
        db.clear()
    console.print("[green]✓[/] 数据库已清空。")
