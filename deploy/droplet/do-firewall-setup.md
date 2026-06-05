# DigitalOcean Cloud Firewall Setup Guide -- OBD-Cortex

This guide outlines how to configure the DigitalOcean Cloud Firewall for the Droplet hosting the Hybrid-Automotive-RAG backend.

## Step 1: Create the Firewall via DO Console
1. Log in to the DigitalOcean Control Panel.
2. Navigate to **Networking** -> **Firewalls**.
3. Click **Create Firewall**.
4. Name the firewall (e.g., `obd-cortex-fw`).

## Step 2: Configure Inbound Rules
Configure the inbound rules to strictly allow only necessary traffic.

| Type | Protocol | Port Range | Sources | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **SSH** | TCP | 22 | `<Your Admin IP Address(es)>` | **IMPORTANT**: Restrict SSH to your known IPs. Update this if your IP changes. |
| **HTTP** | TCP | 80 | All IPv4, All IPv6 | Handled by Nginx (redirects to HTTPS). |
| **HTTPS**| TCP | 443 | All IPv4, All IPv6 | Handled by Nginx. |

> [!WARNING]
> Do **NOT** open port `8000`. Uvicorn listens on `127.0.0.1:8000` internally, and Nginx handles all external public traffic on ports 80/443.

## Step 3: Configure Outbound Rules
By default, DigitalOcean permits all outbound traffic. Ensure these rules are present:

| Type | Protocol | Port Range | Destinations |
| :--- | :--- | :--- | :--- |
| All TCP | TCP | All | All IPv4, All IPv6 |
| All UDP | UDP | All | All IPv4, All IPv6 |
| ICMP | ICMP | - | All IPv4, All IPv6 |

## Step 4: Apply to Droplet
1. Under **Apply to Droplets**, search for and select your OBD-Cortex Droplet.
2. Click **Create Firewall**. The rules will apply instantly at the hypervisor level.

---

## Alternative: Using `doctl` CLI
If you prefer using the command line:

```bash
doctl compute firewall create \
  --name "obd-cortex-fw" \
  --inbound-rules "protocol:tcp,ports:22,address:<YOUR_IP>/32 protocol:tcp,ports:80,address:0.0.0.0/0,address:::/0 protocol:tcp,ports:443,address:0.0.0.0/0,address:::/0" \
  --outbound-rules "protocol:tcp,ports:all,address:0.0.0.0/0,address:::/0 protocol:udp,ports:all,address:0.0.0.0/0,address:::/0 protocol:icmp,address:0.0.0.0/0,address:::/0" \
  --droplet-ids <YOUR_DROPLET_ID>
```
*(Replace `<YOUR_IP>` and `<YOUR_DROPLET_ID>` with your actual values).*
