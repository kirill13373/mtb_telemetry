#!/usr/bin/env bash
set -euo pipefail

TEST_ROOT="${SUFNI_TEST_ROOT:-$HOME/sufni_test}"
SST_DIR="${SUFNI_SST_DIR:-$TEST_ROOT/sst}"
REPO_URL="${SUFNI_REPO_URL:-https://github.com/sghctoma/sst.git}"
REF="${SUFNI_REF:-}"
HOTSPOT_IP="${SUFNI_HOTSPOT_IP:-192.168.10.1}"

usage() {
  cat <<'EOF'
Usage: sufni_test.sh <command>

Commands:
  baseline      Print platform, storage, memory and service baseline.
  install-docker
                Install Docker Engine and Compose plugin if absent.
  prepare       Clone/update Sufni in an isolated test directory.
  arm64-check   Check the required base images for linux/arm64 support.
  build         Run docker compose build inside the Sufni checkout.
  up            Run docker compose up in the foreground.
  down          Run docker compose down.
  ps            Run docker compose ps.
  stats         Run docker stats --no-stream.
  urls          Print the expected home and hotspot access URLs.
  help          Show this help.

Environment:
  SUFNI_TEST_ROOT   Override the remote test root (default: ~/sufni_test)
  SUFNI_SST_DIR     Override the Sufni checkout path (default: ~/sufni_test/sst)
  SUFNI_REPO_URL    Override the git repository URL
  SUFNI_REF         Git tag, branch or commit to checkout during prepare
  SUFNI_HOTSPOT_IP  Expected hotspot IP for URL output (default: 192.168.10.1)
EOF
}

log() {
  printf '[sufni-test] %s\n' "$*"
}

fail() {
  printf '[sufni-test] ERROR: %s\n' "$*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

docker_prefix() {
  if docker info >/dev/null 2>&1; then
    printf 'docker\n'
    return 0
  fi

  if sudo docker info >/dev/null 2>&1; then
    printf 'sudo docker\n'
    return 0
  fi

  fail "Docker is not available or the current user cannot access it yet. Re-login after installation."
}

run_compose() {
  local prefix
  prefix="$(docker_prefix)"
  cd "$SST_DIR"
  if [[ "$prefix" == "docker" ]]; then
    docker compose "$@"
  else
    sudo docker compose "$@"
  fi
}

latest_tag() {
  git -C "$SST_DIR" tag --sort=-version:refname | head -n 1
}

run_baseline() {
  log "Collecting baseline information"
  uname -m
  cat /etc/os-release
  free -h
  df -h /
  printf '\n'

  if command -v docker >/dev/null 2>&1; then
    docker --version || true
    docker compose version || true
  else
    log "Docker not installed"
  fi

  printf '\n'
  for service in ssh smbd NetworkManager mtb-wifi-mode mtb-hostapd mtb-dnsmasq mtb-telemetry-button; do
    if systemctl list-unit-files "$service.service" >/dev/null 2>&1; then
      printf '%s: ' "$service"
      systemctl is-active "$service" || true
    fi
  done

  printf '\n'
  ip -4 addr show wlan0 || true
}

install_docker_repo() {
  local arch codename

  arch="$(dpkg --print-architecture)"
  codename="$(. /etc/os-release && printf '%s' "${VERSION_CODENAME:-bookworm}")"

  sudo install -m 0755 -d /etc/apt/keyrings
  if [[ ! -f /etc/apt/keyrings/docker.asc ]]; then
    curl -fsSL https://download.docker.com/linux/debian/gpg |
      sudo tee /etc/apt/keyrings/docker.asc >/dev/null
    sudo chmod a+r /etc/apt/keyrings/docker.asc
  fi

  cat <<EOF | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
deb [arch=$arch signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $codename stable
EOF
}

run_install_docker() {
  need_cmd curl
  need_cmd gpg
  need_cmd dpkg
  need_cmd apt-get

  if command -v docker >/dev/null 2>&1; then
    log "Docker already installed"
    docker --version || true
    docker compose version || true
    return 0
  fi

  log "Installing Docker Engine and Compose plugin"
  sudo apt-get update
  sudo apt-get install -y ca-certificates curl gnupg git
  install_docker_repo
  sudo apt-get update
  sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  sudo systemctl enable --now docker

  if id -nG "$USER" | grep -qw docker; then
    log "User already in docker group"
  else
    sudo usermod -aG docker "$USER"
    log "Added user '$USER' to docker group; open a new login session before using docker without sudo"
  fi

  docker --version || true
  docker compose version || true
}

run_prepare() {
  need_cmd git
  mkdir -p "$TEST_ROOT"

  if [[ ! -d "$SST_DIR/.git" ]]; then
    log "Cloning Sufni repository into $SST_DIR"
    git clone "$REPO_URL" "$SST_DIR"
  fi

  log "Refreshing repository metadata"
  git -C "$SST_DIR" fetch --all --tags --prune

  local selected_ref
  selected_ref="$REF"

  if [[ -z "$selected_ref" ]]; then
    selected_ref="$(latest_tag || true)"
  fi

  if [[ -n "$selected_ref" ]]; then
    log "Checking out $selected_ref"
    git -C "$SST_DIR" checkout "$selected_ref"
  else
    log "No tag detected; leaving repository on its current ref"
  fi

  log "Current Sufni revision: $(git -C "$SST_DIR" rev-parse HEAD)"
}

check_image_arm64() {
  local image="$1"
  local output docker_mode="$2"

  if [[ "$docker_mode" == "docker" ]]; then
    output="$(docker buildx imagetools inspect "$image" 2>/dev/null || true)"
  else
    output="$(sudo docker buildx imagetools inspect "$image" 2>/dev/null || true)"
  fi

  if [[ -z "$output" ]]; then
    printf 'FAIL  %s (manifest unavailable)\n' "$image"
    return 1
  fi

  if grep -q 'linux/arm64' <<<"$output"; then
    printf 'OK    %s\n' "$image"
    return 0
  fi

  printf 'FAIL  %s (linux/arm64 not advertised)\n' "$image"
  return 1
}

run_arm64_check() {
  local docker_bin
  docker_bin="$(docker_prefix)"

  log "Checking published images for linux/arm64 support"

  local images failures=0
  images=(
    node:22.0-bookworm-slim
    python:3.11-slim-bookworm
    golang:1.22-alpine
    alpine:3.20
    caddy:2.7.6
  )

  for image in "${images[@]}"; do
    check_image_arm64 "$image" "$docker_bin" || failures=1
  done

  if [[ $failures -ne 0 ]]; then
    fail "At least one required image does not advertise linux/arm64 support"
  fi
}

run_build() {
  [[ -f "$SST_DIR/docker-compose.yml" ]] || fail "Missing docker-compose.yml under $SST_DIR. Run prepare first."
  log "Running docker compose build in $SST_DIR"
  run_compose build
}

run_up() {
  [[ -f "$SST_DIR/docker-compose.yml" ]] || fail "Missing docker-compose.yml under $SST_DIR. Run prepare first."
  log "Running docker compose up in the foreground"
  run_compose up
}

run_down() {
  [[ -f "$SST_DIR/docker-compose.yml" ]] || fail "Missing docker-compose.yml under $SST_DIR. Run prepare first."
  log "Stopping Sufni stack"
  run_compose down
}

run_ps() {
  [[ -f "$SST_DIR/docker-compose.yml" ]] || fail "Missing docker-compose.yml under $SST_DIR. Run prepare first."
  run_compose ps
}

run_stats() {
  local prefix
  prefix="$(docker_prefix)"
  if [[ "$prefix" == "docker" ]]; then
    docker stats --no-stream
  else
    sudo docker stats --no-stream
  fi
}

run_urls() {
  local host_ips
  host_ips="$(hostname -I 2>/dev/null || true)"
  printf 'Home network URL candidates:\n'
  for ip in $host_ips; do
    printf '  https://%s\n' "$ip"
  done
  printf 'Hotspot URL:\n'
  printf '  https://%s\n' "$HOTSPOT_IP"
}

main() {
  local command="${1:-help}"

  case "$command" in
    baseline)
      run_baseline
      ;;
    install-docker)
      run_install_docker
      ;;
    prepare)
      run_prepare
      ;;
    arm64-check)
      run_arm64_check
      ;;
    build)
      run_build
      ;;
    up)
      run_up
      ;;
    down)
      run_down
      ;;
    ps)
      run_ps
      ;;
    stats)
      run_stats
      ;;
    urls)
      run_urls
      ;;
    help|-h|--help)
      usage
      ;;
    *)
      usage >&2
      fail "Unknown command: $command"
      ;;
  esac
}

main "$@"