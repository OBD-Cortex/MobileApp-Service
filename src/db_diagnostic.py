#!/usr/bin/env python3
import os
import sys
import socket
import ssl
import time
import urllib.request
import json

# Try to load dotenv
try:
    from dotenv import load_dotenv
    # Load from ENV_PATH if set, else look in parent directory or current directory
    env_path = os.getenv("ENV_PATH")
    if env_path:
        load_dotenv(env_path)
    else:
        load_dotenv()
except ImportError:
    print("[!] warning: python-dotenv not installed in this environment. Using raw env variables.")

import pymongo
import certifi

def run_diagnostics():
    print("=" * 60)
    print(" OBD-CORTEX MONGO DB DIAGNOSTIC TOOL")
    print("=" * 60)
    
    # 1. Check System Time
    print("\n[1] Checking System Time...")
    local_time = time.strftime('%Y-%m-%d %H:%M:%S %Z', time.localtime())
    print(f"    Local time: {local_time}")
    try:
        # Fetch time from a public API to compare
        with urllib.request.urlopen("https://worldtimeapi.org/api/timezone/Etc/UTC", timeout=3) as response:
            data = json.loads(response.read().decode())
            utc_time_api = data.get("datetime")
            print(f"    Reference UTC Time: {utc_time_api}")
    except Exception as e:
        print(f"    [!] Could not contact reference time server: {e}")
        print("    Please ensure your system time is reasonably accurate (check with command: date)")

    # 2. Check OpenSSL and Certifi
    print("\n[2] Checking SSL/TLS Environment...")
    print(f"    Python Version: {sys.version.split()[0]}")
    print(f"    OpenSSL Version: {ssl.OPENSSL_VERSION}")
    print(f"    Certifi location: {certifi.where()}")
    try:
        with open(certifi.where(), "r") as f:
            certs = f.read()
            print(f"    Certifi CA Bundle Size: {len(certs)} bytes (looks valid)")
    except Exception as e:
        print(f"    [!] Error reading certifi CA bundle: {e}")

    # 3. Check MONGO_URI Env Var
    print("\n[3] Checking Environment Variables...")
    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        print("    [!] MONGO_URI is not set! Please check your .env file and ENV_PATH.")
        return
    
    # Redact credentials for logging
    redacted_uri = mongo_uri
    if "@" in mongo_uri:
        parts = mongo_uri.split("@")
        scheme = parts[0].split("://")
        redacted_uri = f"{scheme[0]}://[REDACTED_USER:REDACTED_PASS]@{parts[1]}"
    print(f"    MONGO_URI: {redacted_uri}")

    # 4. Resolve DNS and Test Ports
    print("\n[4] Resolving Database Hostnames and Testing Network Access...")
    # Extract hostname
    host = ""
    try:
        if "://" in mongo_uri:
            uri_body = mongo_uri.split("://")[1]
            if "@" in uri_body:
                uri_body = uri_body.split("@")[1]
            host_port = uri_body.split("/")[0]
            host = host_port.split(":")[0]
            if "?" in host:
                host = host.split("?")[0]
        
        print(f"    Extracted host: {host}")
        
        # Resolve SRV record or standard hostname
        is_srv = mongo_uri.startswith("mongodb+srv://")
        if is_srv:
            print("    Using SRV connection string. Resolving SRV records requires dnspython...")
            try:
                import dns.resolver
                print("    dnspython is installed.")
                srv_results = dns.resolver.resolve(f"_mongodb._tcp.{host}", "SRV")
                hosts_to_test = []
                for r in srv_results:
                    hosts_to_test.append((str(r.target).rstrip("."), r.port))
                print(f"    Found {len(hosts_to_test)} cluster nodes in SRV record:")
                for h, p in hosts_to_test:
                    print(f"      - {h}:{p}")
            except Exception as e:
                print(f"    [!] Error resolving SRV records: {e}")
                print("    Will fall back to testing the base domain on port 27017.")
                hosts_to_test = [(host, 27017)]
        else:
            port = 27017
            if ":" in host_port:
                port = int(host_port.split(":")[1])
            hosts_to_test = [(host, port)]

        # Test socket connection to all hosts
        for h, p in hosts_to_test:
            print(f"    Testing TCP connection to {h}:{p}...")
            start = time.time()
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3.0)
                sock.connect((h, p))
                sock.close()
                elapsed = (time.time() - start) * 1000
                print(f"      [✓] TCP Port 27017 is OPEN! (Connected in {elapsed:.1f}ms)")
            except socket.timeout:
                print(f"      [!] Connection TIMEOUT! Port 27017 is blocked or cluster is down.")
                print("          -> Check MongoDB Atlas Network Access IP whitelist.")
            except Exception as e:
                print(f"      [!] TCP Connection Failed: {e}")
                print("          -> Check MongoDB Atlas Network Access IP whitelist.")
                
    except Exception as e:
        print(f"    [!] Error parsing URI or resolving host: {e}")

    # 5. Try PyMongo Connection (TLS verified)
    print("\n[5] Attempting Standard Connection (TLS Verification Enabled)...")
    try:
        client = pymongo.MongoClient(
            mongo_uri, 
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=3000
        )
        # Force a command to run
        start = time.time()
        client.admin.command("ping")
        elapsed = (time.time() - start) * 1000
        print(f"    [✓] Connection Successful! Ping returned in {elapsed:.1f}ms.")
        return
    except Exception as e:
        print(f"    [!] Standard Connection Failed:")
        print(f"        Error message: {e}")

    # 6. Try PyMongo Connection (TLS verification DISABLED)
    print("\n[6] Attempting Insecure Connection (TLS Verification Disabled)...")
    print("    WARNING: This is for diagnostics only! Never use this in production.")
    try:
        client = pymongo.MongoClient(
            mongo_uri,
            tlsAllowInvalidCertificates=True,
            serverSelectionTimeoutMS=3000
        )
        start = time.time()
        client.admin.command("ping")
        elapsed = (time.time() - start) * 1000
        print(f"    [✓] Insecure Connection Successful! (Ping returned in {elapsed:.1f}ms)")
        print("\n    >>> CONCLUSION: NETWORK ACCESS / WHITELIST IS OK! <<<")
        print("    The issue is strictly SSL/TLS certificate verification.")
        print("    Possible fixes:")
        print("    1. Reinstall/Upgrade certifi: `pip install --upgrade certifi`")
        print("    2. Reinstall ca-certificates on host: `sudo apt-get install --reinstall ca-certificates`")
    except Exception as e:
        print(f"    [!] Insecure Connection Also Failed:")
        print(f"        Error message: {e}")
        print("\n    >>> CONCLUSION: CONNECTION BLOCKED OR INVALID URI <<<")
        print("    Since connection fails even with TLS verification disabled:")
        print("    1. Your Droplet's public IP is likely not whitelisted in MongoDB Atlas Network Access.")
        print("       Action: Log in to Atlas -> Network Access -> Add IP Address.")
        print("       (Add the IP of the Droplet, or if testing, temporarily add 0.0.0.0/0)")
        print("    2. The MONGO_URI in your .env contains an error (e.g. incorrect password or username).")
        print("    3. A firewall or security group is blocking outgoing connections on port 27017.")

if __name__ == "__main__":
    run_diagnostics()
