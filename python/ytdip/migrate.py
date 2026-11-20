"""把旧资料库搬进新位置，并重写 media.json 里的绝对路径。

    python -m ytdip.migrate --from "C:\\Users\\me\\Desktop\\大肥鱼\\yt-dip\\资料库"
    python -m ytdip.migrate --from "..." --to "D:\\备份\\yt-dip" --overwrite

只复制、不改动源目录；默认跳过已存在的条目。
"""
import argparse
import json
import os
import shutil
import sys

from . import config, store

PATH_FIELDS = ("media_path", "cover_path", "audio_path")


def _rewrite(directory, old_root, new_root):
    path = store.media_json_path(directory)
    record = store.load_json(path)
    if not record:
        return 0
    changed = 0
    for field in PATH_FIELDS:
        value = record.get(field) or ""
        if not value:
            continue
        if os.path.abspath(value).startswith(os.path.abspath(old_root)):
            candidate = os.path.join(new_root, os.path.relpath(value, old_root))
            if os.path.exists(candidate):
                record[field] = candidate
                changed += 1
            else:
                record[field] = ""
                changed += 1
    if changed:
        store.write_media(directory, record)
    return changed


def migrate(source_root, target_root, overwrite=False, dry_run=False):
    source_root = os.path.abspath(source_root)
    target_root = os.path.abspath(target_root or config.LIB_ROOT)
    if not os.path.isdir(source_root):
        raise SystemExit(f"源目录不存在: {source_root}")
    os.makedirs(target_root, exist_ok=True)

    copied, skipped, rewritten = [], [], 0
    for name in sorted(os.listdir(source_root)):
        if name.startswith(".") or name in ("__pycache__",):
            continue
        src = os.path.join(source_root, name)
        if not os.path.isdir(src):
            continue
        dst = os.path.join(target_root, name)
        if os.path.exists(dst) and not overwrite:
            skipped.append(name)
        else:
            if not dry_run:
                shutil.copytree(src, dst, dirs_exist_ok=True)
            copied.append(name)
        if not dry_run:
            rewritten += _rewrite(dst, source_root, target_root)

    return {
        "from": source_root,
        "to": target_root,
        "copied": copied,
        "skipped": skipped,
        "rewritten": rewritten,
        "dryRun": dry_run,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(prog="ytdip.migrate", description="迁移旧资料库")
    parser.add_argument("--from", dest="source", required=True, help="旧资料库根目录")
    parser.add_argument("--to", dest="target", default=config.LIB_ROOT, help="新资料库根目录")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在的条目")
    parser.add_argument("--dry-run", action="store_true", help="只看会做什么")
    args = parser.parse_args(argv)

    report = migrate(args.source, args.target, overwrite=args.overwrite, dry_run=args.dry_run)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n复制 {len(report['copied'])} 条，跳过 {len(report['skipped'])} 条，"
          f"重写路径 {report['rewritten']} 处")
    return 0


if __name__ == "__main__":
    sys.exit(main())
