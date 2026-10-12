# 유달리 Claude Code 스킬 설치·갱신: irm __BASE__/skills/install.ps1 | iex
# iex로 사용자 셸에서 돌므로 exit를 쓰지 않고 설정도 이 블록 안에만 둔다. UDALLY_SKIP_LOGIN=1이면 로그인을 건너뛴다.
& {
  $ErrorActionPreference = 'Stop'
  $base = '__BASE__'
  $dest = Join-Path $HOME '.claude\skills'
  $conf = Join-Path $HOME '.config\udally'
  $zip = Join-Path ([IO.Path]::GetTempPath()) 'udally-skills.zip'
  Invoke-WebRequest "$base/skills/udally-skills.zip" -OutFile $zip -UseBasicParsing
  New-Item -ItemType Directory -Force $dest, $conf | Out-Null
  Expand-Archive $zip $dest -Force
  Remove-Item $zip
  [IO.File]::WriteAllText((Join-Path $conf 'url'), $base)
  Write-Host "유달리 스킬을 $dest 에 설치했습니다."

  $py = $null
  foreach ($c in 'python', 'python3', 'py') {
    if (Get-Command $c -ErrorAction SilentlyContinue) {
      & $c -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>$null
      if ($LASTEXITCODE -eq 0) { $py = $c; break }
    }
  }
  if (-not $py) {
    Write-Host 'Python 3.9 이상이 필요합니다. https://www.python.org/downloads/ 에서 설치한 뒤 이 명령을 다시 실행해 주세요.'
  } elseif ($env:UDALLY_SKIP_LOGIN) {
    Write-Host "로그인은 건너뛰었습니다. 나중에 $py `"$dest\pm\scripts\pm.py`" login 을 실행해 주세요."
  } else {
    & $py (Join-Path $dest 'pm\scripts\pm.py') login
  }
}
