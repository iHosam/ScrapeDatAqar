#!/usr/bin/env bash
# ==============================================================================
# ScrapeDatAqar - Idempotent System Setup Script
# Checks host environment and installs missing packages/services conditionally.
# ==============================================================================
set -e

echo "=== [1/4] Checking Operating System ==="
if [ -f /etc/os-release ]; then
    . /etc/os-release
    echo "[FOUND] OS: $NAME $VERSION"
else
    echo "[ERROR] Linux OS not detected. Please install Ubuntu 24.04 or Debian 12."
    exit 1
fi

echo "=== [2/4] Checking Required System Packages ==="
REQUIRED_PKGS=(openssh-server curl wget git htop net-tools build-essential python3 python3-pip python3-venv sqlite3 libsqlite3-dev ca-certificates gnupg lsb-release)
MISSING_PKGS=()

for pkg in "${REQUIRED_PKGS[@]}"; do
    if dpkg -s "$pkg" >/dev/null 2>&1; then
        echo "  [FOUND] $pkg"
    else
        MISSING_PKGS+=("$pkg")
    fi
done

if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
    echo "[INSTALLING] Missing packages: ${MISSING_PKGS[*]}"
    sudo apt update
    sudo apt install -y "${MISSING_PKGS[@]}"
else
    echo "[OK] All system packages are installed."
fi

echo "=== [3/4] Checking Docker Engine ==="
if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    echo "[FOUND] Docker Engine is active."
else
    echo "[INSTALLING] Installing Docker Engine..."
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt update
    sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    
    sudo mkdir -p /etc/docker
    sudo tee /etc/docker/daemon.json << 'EOF'
{
  "dns": ["1.1.1.1", "8.8.8.8"]
}
EOF
    sudo systemctl restart docker
    sudo usermod -aG docker "$USER"
    echo "[OK] Docker Engine installed."
fi

echo "=== [4/4] Checking Python Virtual Environment ==="
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$DIR"

if [ ! -d "venv" ]; then
    echo "[CREATING] Python virtual environment..."
    python3 -m venv venv
fi

source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "=== Setup Complete! Run ./run_pipeline.sh to start crawler. ==="
