"""Resource-limited PDF text extraction helper. Never evaluates user code."""
import json
import sys


def main():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (384 * 1024 * 1024, 384 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    except (ImportError, OSError, ValueError):
        # Supported production target is Linux. Refuse extraction without limits.
        sys.exit(2)
    from pypdf import PdfReader

    try:
        reader = PdfReader(sys.argv[1], strict=True)
        if reader.is_encrypted:
            sys.exit(2)
        pieces = []
        count = 0
        truncated = len(reader.pages) > 30
        for page in reader.pages[:30]:
            text = page.extract_text() or ""
            pieces.append(text[:30_001 - count])
            count += len(pieces[-1])
            if count > 30_000:
                truncated = True
                break
        text = "\n".join(pieces)
        print(json.dumps({"text": text[:30_000], "truncated": truncated or len(text) > 30_000}))
    except Exception:
        # No parser exception or uploaded content is surfaced to logs/client.
        sys.exit(2)


if __name__ == "__main__":
    main()
