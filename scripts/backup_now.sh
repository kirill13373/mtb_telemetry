#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_ROOT="/home/pi/backups/mtb_telemetry"
TS="$(date +%Y%m%d_%H%M%S)"

mkdir -p "$BACKUP_ROOT"

# Snapshot current working tree (including uncommitted changes), excluding .git metadata and venv.
tar -czf "$BACKUP_ROOT/workingtree_${TS}.tar.gz" \
  --exclude='.git' \
  --exclude='venv' \
  -C "$REPO_DIR" .

# Save a portable backup of all git refs.
git -C "$REPO_DIR" bundle create "$BACKUP_ROOT/repo_${TS}.bundle" --all

# Keep a local bare mirror up to date for fast recovery.
if [ ! -d "$BACKUP_ROOT/repo_mirror.git" ]; then
  git init --bare "$BACKUP_ROOT/repo_mirror.git" >/dev/null
fi

if git -C "$REPO_DIR" remote get-url backup-local >/dev/null 2>&1; then
  git -C "$REPO_DIR" remote set-url backup-local "$BACKUP_ROOT/repo_mirror.git"
else
  git -C "$REPO_DIR" remote add backup-local "$BACKUP_ROOT/repo_mirror.git"
fi

git -C "$REPO_DIR" push --mirror backup-local >/dev/null

echo "Backup complete:"
echo "  $BACKUP_ROOT/workingtree_${TS}.tar.gz"
echo "  $BACKUP_ROOT/repo_${TS}.bundle"
echo "  $BACKUP_ROOT/repo_mirror.git"
