import dataclasses, os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app.config import settings, validate_settings
from app.bot.formatting import fits_alone, split_messages, fmt_duration

assert validate_settings() == []
def bad(**kw): return validate_settings(dataclasses.replace(settings, **kw))
assert any("TEST_CONCURRENCY" in m for m in bad(TEST_CONCURRENCY=0))
assert any("CHUNK_SIZE" in m for m in bad(FUNCTIONAL_TEST_CHUNK_SIZE=0))
assert any("MIN_PASSES" in m for m in bad(FUNCTIONAL_TEST_MIN_PASSES=5))
assert any("GITHUB_REPO" in m for m in bad(GITHUB_REPO="not a repo"))
assert bad(GITHUB_REPO="owner/name") == []
assert any("EXIT_GEO_URL" in m for m in bad(EXIT_GEO_URL="ftp://x"))
r = subprocess.run([sys.executable, "-c", "import app.config"], cwd=ROOT, capture_output=True, text=True,
                   env={**os.environ, "TEST_CONCURRENCY": "abc"})
assert r.returncode != 0 and "Invalid value for TEST_CONCURRENCY" in r.stderr

header, footer = "H" * 30, "F" * 160
entries = ["x" * 900 for _ in range(10)]
msgs = split_messages(header, entries, footer)
assert all(len(m) <= 3900 for m in msgs) and msgs[-1].endswith(footer) and len(msgs) > 1
assert sum(m.count("x" * 900) for m in msgs) == 10
assert fits_alone("x" * 900, header, footer) and not fits_alone("x" * 4500, header, footer)
assert fmt_duration(30) == "1m" and fmt_duration(3700) == "1h 1m" and fmt_duration(90000) == "1d 1h"
print("config/format tests: ALL PASSED")
