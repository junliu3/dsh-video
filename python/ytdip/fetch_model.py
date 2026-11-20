"""通过镜像把 faster-whisper 模型下载到本地，避开 hub API 在国内容易超时。

    python -m ytdip.fetch_model small
    python -m ytdip.fetch_model large-v3
    python -m ytdip.fetch_model --list
"""
import os
import sys
import urllib.request

from . import config

MIRROR = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com").rstrip("/")

REPOS = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v2": "Systran/faster-whisper-large-v2",
    "large-v3": "Systran/faster-whisper-large-v3",
}

REQUIRED = ["model.bin", "config.json", "tokenizer.json"]
OPTIONAL = ["preprocessor_config.json", "vocabulary.txt", "vocabulary.json"]


def _download(url, dest):
    tmp = dest + ".part"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        total = int(response.headers.get("Content-Length") or 0)
        got = 0
        with open(tmp, "wb") as handle:
            while True:
                chunk = response.read(1 << 18)
                if not chunk:
                    break
                handle.write(chunk)
                got += len(chunk)
                if total:
                    sys.stdout.write(f"\r    {got / 1048576:6.1f} / "
                                     f"{total / 1048576:.1f} MB  {got * 100 / total:5.1f}%")
                    sys.stdout.flush()
    sys.stdout.write("\n")
    os.replace(tmp, dest)
    return got


def fetch(name):
    if name not in REPOS:
        raise SystemExit(f"不支持的模型: {name}（可选 {', '.join(REPOS)}）")
    repo = REPOS[name]
    out = os.path.join(config.MODEL_DIR, "faster-whisper-" + name)
    os.makedirs(out, exist_ok=True)
    print(f"模型 {name}  ->  {repo}")
    print(f"镜像 {MIRROR}")
    print(f"目录 {out}\n")

    for filename in REQUIRED + OPTIONAL:
        dest = os.path.join(out, filename)
        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            print(f"  跳过 {filename}（已存在）")
            continue
        url = f"{MIRROR}/{repo}/resolve/main/{filename}"
        try:
            size = _download(url, dest)
            print(f"  {filename}  {size / 1048576:.1f} MB")
        except Exception as exc:
            if filename in REQUIRED:
                raise
            print(f"  可选文件 {filename} 没拿到（{type(exc).__name__}），跳过")
    print("\n完成。")
    return out


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    if "--list" in argv:
        root = config.MODEL_DIR
        have = []
        if os.path.isdir(root):
            for name in os.listdir(root):
                if name.startswith("faster-whisper-") and \
                        os.path.isfile(os.path.join(root, name, "model.bin")):
                    have.append(name.replace("faster-whisper-", ""))
        print("可用尺寸: " + ", ".join(REPOS))
        print("已下载:   " + (", ".join(sorted(have)) or "无"))
        print("目录:     " + root)
        return 0
    if not argv:
        raise SystemExit("用法: python -m ytdip.fetch_model <tiny|base|small|medium|large-v3>")
    fetch(argv[0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
