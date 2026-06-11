# MobileApp Service Deployment Guide

This guide outlines the production-ready deployment strategy for the MobileApp Service on a DigitalOcean Droplet using Nginx, HTTPS via Certbot, and `ufw` firewall rules.

---

## Security Requirements & Firewalls (UFW)

> [!WARNING]
> **Strict Port Isolation:** The Uvicorn app processes execute on port `8000` bound to the local loopback interface `127.0.0.1`.
> **You must configure UFW to drop external incoming traffic to port 8000.** Letting clients access port 8000 directly bypasses the reverse proxy, leaving endpoints exposed. Only ports 80 (HTTP) and 443 (HTTPS) must be allowed externally.

---

## Environment Variables

Create a `.env` file containing the following:

```env
MONGO_URI=mongodb+srv://user:pass@cluster.mongodb.net/?retryWrites=true&w=majority
GOOGLE_API_KEY=your_gemini_api_key_here
```

*(Note: Embeddings run locally via the Harrier model, but generation requires the Gemini API key).*

---

## Production Server Setup

Execute these commands as `root` to create a dedicated service user and configure SSH:

```bash
sudo useradd -m -s /usr/bin/fish app-service
sudo chsh -s /usr/bin/fish app-service
sudo mkdir -p /home/app-service/.ssh
sudo chown app-service:app-service /home/app-service/.ssh
sudo chmod 700 /home/app-service/.ssh
nvim /home/app-service/.ssh/authorized_keys
chown app-service:app-service /home/app-service/.ssh/authorized_keys
chmod 600 /home/app-service/.ssh/authorized_keys
passwd app-service
usermod -aG sudo app-service
```

---

## Swap Memory Allocation

> [!IMPORTANT]
> **CRITICAL CONFIGURATION:** Because this service loads a 1GB NLP model into RAM and processes massive Pandas DataFrames, a large Swap file is mandatory to prevent Out-of-Memory (OOM) crashes during asynchronous ingestion. Allocate at least **4GB Swap** on the host Droplet.

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h
```

---

## Service Installation

SSH into the newly created `app-service` user:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y git nginx certbot ufw python3.10-venv
python3 -m venv venv
source venv/bin/activate.fish

# Clone repository and install dependencies
pip install -r requirements.txt
chmod 600 .env
```

---

## Fish Shell Configuration

To streamline the environment, add the following to `~/.config/fish/config.fish`:

```fish
set -g fish_greeting
set -gx ENV_PATH "/home/app-service/MobileApp-Service/.env"
set -gx TERM xterm-256color
```

---

## Nginx & HTTPS Configuration

First, ensure your Hostinger DNS points the desired subdomain (e.g., `app.yourdomain.com`) to your DigitalOcean IP address.

Define the custom log format in `/etc/nginx/nginx.conf` (inside the `http { ... }` block):

```nginx
    log_format domain_access '$remote_addr - $remote_user [$time_local] '
                             '"$request" $status $body_bytes_sent '
                             '"$http_referer" "$http_user_agent" '
                             'host="$host"';
```

Configure Nginx (`sudo nvim /etc/nginx/sites-available/MobileApp-Service`):

```nginx
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;

server {
    server_name app.yourdomain.com;

    # Security headers
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Allow large PDF manual uploads from the Admin dashboard
    client_max_body_size 50M;

    location / {
        limit_req zone=api_limit burst=20 nodelay;

        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Extended timeouts for long-running AI operations if needed
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
        proxy_connect_timeout 10s;
    }

    # Certbot will inject SSL configurations here automatically
    access_log /var/log/nginx/MobileApp-Service.access.log domain_access;
}

server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name _;
    ssl_reject_handshake on;
}

server {
    listen 80 default_server;
    listen [::]:80 default_server;
    server_name _;
    return 444; # Instantly drop unencrypted traffic
}
```

Enable the site and configure SSL:

```bash
sudo ln -sf /etc/nginx/sites-available/MobileApp-Service /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t

# Obtain SSL Certificate
sudo certbot --nginx -d app.yourdomain.com

sudo systemctl restart nginx
sudo systemctl enable nginx.service
```

---

## Firewall Setup

Set up UFW rules to drop external incoming traffic to port `8000`, ensuring exposure strictly via proxy.

```bash
# Allow necessary services
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx HTTPS'
sudo ufw allow 'Nginx HTTP'

# Explicitly ensure port 8000 is blocked externally (UFW denies by default)
sudo ufw deny 8000/tcp

# Enable firewall
sudo ufw --force enable
sudo ufw status verbose
```

To run the application persistently, refer to the provided `systemd/MobileApp_Service.service` template.

