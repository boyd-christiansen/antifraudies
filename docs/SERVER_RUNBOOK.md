# Server runbook — build & maintain the dataset

This is the operator/agent runbook for running antifraudies on a dedicated server (large
disk) that **owns and maintains the scraped dataset**. It assumes a Linux host (Debian/
Ubuntu commands shown; adapt for your distro) with plenty of storage. The full Thermo Fisher
antibody catalog is ~261K products; image bytes are ~100 GB of real data (well within a
multi-TB disk). The crawl takes roughly 6–9 hours.

> **Framing discipline (binding):** this system surfaces *apparent* anomalies for human
> review — it never renders a verdict. Keep the crawl defensible (honest User-Agent +
> contact, robots.txt respected, adaptive backoff). Do **not** disable robots compliance or
> spoof a browser identity to go faster. This is research we may publish.

## 0. Preflight — verify the environment (don't skip)

```bash
uname -a                          # OS / arch
python3 --version                 # need >= 3.11
psql --version || echo "postgres not installed yet"
df -h                             # find the big disk + its mount point; note it
nproc; free -h                    # cores / RAM
```

Pick the large-disk mount point (e.g. `/mnt/data`, `/data`, a ZFS dataset). Everything below
calls it `$BIGDISK`. **Verify it's a real Linux filesystem (ext4/xfs/zfs) — not exFAT/NTFS**
(those waste space and/or can't host Postgres):

```bash
export BIGDISK=/mnt/data          # <-- set to the actual mount you found
mount | grep " $BIGDISK "         # confirm fstype is ext4/xfs/zfs/btrfs
```

## 1. Get the code

```bash
cd "$BIGDISK"
git clone https://github.com/boyd-christiansen/antifraudies.git
# (private repo? authenticate first: gh auth login, or use an SSH remote / PAT)
cd antifraudies

python3 -m venv .venv
. .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
pytest -q                         # GATE: expect "42 passed". Stop & report if not.
```

## 2. PostgreSQL + pgvector

```bash
sudo apt-get update
sudo apt-get install -y postgresql postgresql-contrib
PGMAJ=$(pg_config --version | grep -oE '[0-9]+' | head -1)   # e.g. 16 or 17
sudo apt-get install -y "postgresql-${PGMAJ}-pgvector" \
  || echo "no pgvector package for PG ${PGMAJ}; build from github.com/pgvector/pgvector (make && sudo make install)"

# A DB role matching the Linux user, with createdb, so the default DSN works over the local socket:
sudo -u postgres createuser --createdb "$USER" 2>/dev/null || true
createdb antifraudies 2>/dev/null || echo "(db may already exist)"
psql -d antifraudies -c "CREATE EXTENSION IF NOT EXISTS vector;"
psql -d antifraudies -tAc "SELECT extversion FROM pg_extension WHERE extname='vector';"   # GATE: prints a version
```

If local-socket auth fails, create a password role and set the DSN instead:
`export ANTIFRAUDIES_DATABASE__DSN="postgresql://antifraudies:PASSWORD@localhost:5432/antifraudies"`

## 3. Point storage at the big disk

```bash
export ANTIFRAUDIES_DATA_DIR="$BIGDISK/antifraudies/data"   # holds blobs/ + cache/
mkdir -p "$ANTIFRAUDIES_DATA_DIR"
# (optional) identify the crawler honestly with your own contact:
export ANTIFRAUDIES_CRAWL__CONTACT="you@example.org"
```

Make these persistent for the service: add the three `export` lines to `~/.profile`, or set
them in the systemd unit below. (Postgres stays on its default data dir — it's only a few GB.)

## 4. Smoke test — GATE before the long run

```bash
antifraudies scrape --vendor thermofisher --limit 50 --concurrency 16
antifraudies report --vendor thermofisher
ls "$ANTIFRAUDIES_DATA_DIR/blobs" | head        # confirm image bytes landed on the big disk
```

Expect a provenance/modality breakdown and image blobs on `$BIGDISK`. If this works, proceed.

## 5. Full crawl — run it durably

The crawl is hours long; run it so it survives disconnects. `--resume` skips products already
in the DB, so it's safe to re-run after any interruption.

**Option A — tmux (simple):**
```bash
tmux new -s scrape
antifraudies scrape --vendor thermofisher --concurrency 48 --resume
#   detach with Ctrl-b d ; reattach with: tmux attach -t scrape
```

**Option B — systemd (recommended for a maintained service):** create
`/etc/systemd/system/antifraudies-scrape.service`:
```ini
[Unit]
Description=antifraudies full catalog scrape
After=postgresql.service

[Service]
User=YOUR_USER
WorkingDirectory=BIGDISK/antifraudies
Environment=ANTIFRAUDIES_DATA_DIR=BIGDISK/antifraudies/data
ExecStart=BIGDISK/antifraudies/.venv/bin/antifraudies scrape --vendor thermofisher --concurrency 48 --resume
Restart=on-failure
RestartSec=60

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload && sudo systemctl start antifraudies-scrape
journalctl -u antifraudies-scrape -f          # watch progress (logs every 1000 products)
```

Monitor: progress prints every 1000 products (`... N products, M images, K errors`). A few
errors are fine; a flood of 429/5xx means dial `--concurrency` down (the crawler already backs
off). Disk to expect: ~100 GB of images.

## 6. Run the detectors

After the crawl (or any time, on whatever is scraped so far):
```bash
antifraudies detect --tier all                 # Tier 0 metadata/exact reuse, Tier 1 features + near-dup
antifraudies report  --vendor thermofisher
antifraudies findings --type near_duplicate    # ranked apparent-anomaly clusters
```

## 7. Maintenance — keep the dataset fresh & safe

- **Refresh** (catch new/changed images): re-run the scrape with `--resume` on a schedule —
  e.g. a weekly cron / systemd timer — then re-run `detect --tier all`.
- **Back up the metadata DB** (small, high value): `pg_dump antifraudies | gzip > backup.sql.gz`
  on a schedule. Image blobs are large but re-fetchable; back them up only if convenient.
- **Don't run two scrapers at once** against the same DB/host.

## Guardrails (do not violate)

1. Keep robots.txt compliance and the honest UA + contact. Never spoof a browser identity or
   disable politeness to go faster.
2. This produces *apparent* anomalies for review, never verdicts. Don't add code/labels that
   assert "confirmed manipulation."
3. If a GATE step fails (tests, pgvector, smoke test), **stop and report** — don't improvise
   around it.
4. Don't modify detector logic or scoring as part of operating the server; report issues back
   to the main repo instead.
```
