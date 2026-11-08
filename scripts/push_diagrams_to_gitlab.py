#!/usr/bin/env python3
"""
Sync local theory diagrams to GitLab media asset repository:
Repo: shedrackgodstime/utmelab-bank
Target path: images/theory/diagrams/<filename>.svg
Reads GITLAB_TOKEN from utmelab-bank/.env
"""

import base64
import os
import sys
import urllib.parse
import urllib.request
import urllib.error
import json

def load_env(env_path):
    env_vars = {}
    if not os.path.exists(env_path):
        return env_vars
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip().strip('"').strip("'")
    return env_vars

def main():
    bank_env = load_env("utmelab-bank/.env")
    token = bank_env.get("GITLAB_TOKEN") or os.environ.get("GITLAB_TOKEN")
    project = bank_env.get("GITLAB_MEDIA_REPO", "shedrackgodstime/utmelab-bank")
    host = bank_env.get("GITLAB_HOST", "gitlab.com")
    
    if not token:
        print("Error: GITLAB_TOKEN not found in utmelab-bank/.env or environment.")
        sys.exit(1)

    encoded_project = urllib.parse.quote(project, safe="")
    api_base = f"https://{host}/api/v4/projects/{encoded_project}/repository/files"
    diagrams_dir = "data/theory/diagrams"

    if not os.path.isdir(diagrams_dir):
        print(f"Error: {diagrams_dir} directory not found.")
        sys.exit(1)

    svg_files = [f for f in sorted(os.listdir(diagrams_dir)) if f.endswith(".svg")]
    print(f"Found {len(svg_files)} SVG diagrams to sync to {project}...")

    success = 0
    failed = 0

    for filename in svg_files:
        filepath = os.path.join(diagrams_dir, filename)
        with open(filepath, "rb") as f:
            data = f.read()

        b64_content = base64.b64encode(data).decode("ascii")
        target_path = f"images/theory/diagrams/{filename}"
        encoded_path = urllib.parse.quote(target_path, safe="")
        file_url = f"{api_base}/{encoded_path}"

        headers = {
            "PRIVATE-TOKEN": token,
            "Content-Type": "application/json",
            "User-Agent": "utmelab-theory-sync/1.0"
        }

        # Check if file exists
        check_req = urllib.request.Request(f"{file_url}?ref=main", headers={"PRIVATE-TOKEN": token})
        exists = False
        try:
            with urllib.request.urlopen(check_req) as resp:
                if resp.status == 200:
                    exists = True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                exists = False
            elif e.code == 401:
                print(f"Authentication failed (HTTP 401). Token revoked or invalid: {e.read().decode('utf-8')}")
                sys.exit(2)
            else:
                print(f"Failed to check {filename}: {e}")
                failed += 1
                continue

        action = "PUT" if exists else "POST"
        commit_msg = f"update theory diagram {filename}" if exists else f"add theory diagram {filename}"
        payload = json.dumps({
            "branch": "main",
            "content": b64_content,
            "encoding": "base64",
            "commit_message": commit_msg
        }).encode("utf-8")

        req = urllib.request.Request(file_url, data=payload, headers=headers, method=action)
        try:
            with urllib.request.urlopen(req) as resp:
                if resp.status in (200, 201):
                    print(f"✓ [{action}] {target_path}")
                    success += 1
                else:
                    print(f"Unexpected status {resp.status} for {filename}")
                    failed += 1
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8")
            if "already exists" in err_msg.lower():
                print(f"✓ [EXISTS] {target_path}")
                success += 1
            else:
                print(f"✗ Failed {filename} ({e.code}): {err_msg}")
                failed += 1

    print(f"\nSync complete: {success} succeeded, {failed} failed.")

if __name__ == "__main__":
    main()
