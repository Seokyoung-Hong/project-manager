"""Call Sandol MCP tools through their JSON HTTP relay using only Python stdlib."""

import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in {"list", "call"}:
        raise SystemExit("usage: pm.py list | pm.py call TOOL_NAME JSON_ARGUMENTS")
    token = os.environ.get("SANDOL_PM_TOKEN")
    if not token:
        raise SystemExit("SANDOL_PM_TOKEN is not set on this device")
    base = os.environ.get("SANDOL_PM_API_URL", "https://project.sio2.kr/mcp/relay/tools").rstrip("/")
    if sys.argv[1] == "list":
        if len(sys.argv) != 2:
            raise SystemExit("usage: pm.py list")
        request = Request(base, headers={"Authorization": f"Bearer {token}"})
    else:
        if len(sys.argv) != 4 or not sys.argv[2].replace("_", "").isalnum():
            raise SystemExit("usage: pm.py call TOOL_NAME JSON_ARGUMENTS")
        try:
            arguments = json.loads(sys.argv[3])
        except ValueError as exc:
            raise SystemExit(f"invalid JSON arguments: {exc}") from exc
        if not isinstance(arguments, dict):
            raise SystemExit("JSON arguments must be an object")
        request = Request(
            f"{base}/{sys.argv[2]}",
            data=json.dumps(arguments, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise SystemExit(f"connection failed: {exc.reason}") from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
