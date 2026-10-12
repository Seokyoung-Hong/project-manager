#!/bin/sh
# 유달리 Claude Code 스킬 설치·갱신: curl -fsSL __BASE__/skills/install.sh | sh
# 압축 풀기에도 Python을 쓴다(unzip이 없는 환경이 있다). UDALLY_SKIP_LOGIN=1이면 로그인을 건너뛴다.
set -e
BASE='__BASE__'
DEST="$HOME/.claude/skills"
CONF="$HOME/.config/udally"

PY=
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    PY=$c
    break
  fi
done
if [ -z "$PY" ]; then
  echo 'Python 3.9 이상이 필요합니다. 설치한 뒤 이 명령을 다시 실행해 주세요.' >&2
  exit 1
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
curl -fsSL "$BASE/skills/udally-skills.zip" -o "$TMP/skills.zip"
mkdir -p "$DEST" "$CONF"
"$PY" -m zipfile -e "$TMP/skills.zip" "$DEST"
printf '%s' "$BASE" > "$CONF/url"
echo "유달리 스킬을 $DEST 에 설치했습니다."

if [ -n "$UDALLY_SKIP_LOGIN" ]; then
  echo "로그인은 건너뛰었습니다. 나중에 $PY \"$DEST/pm/scripts/pm.py\" login 을 실행해 주세요."
else
  "$PY" "$DEST/pm/scripts/pm.py" login
fi
