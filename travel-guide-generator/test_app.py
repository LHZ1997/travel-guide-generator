"""Integration test script for the multi-agent architecture."""
import json
import os
import shutil
import sys
import time

# Backup and recreate database to pick up schema changes
DB_PATH = "/Users/lhz/Desktop/旅游攻略/travel-guide-generator/instance/app.db"
if os.path.exists(DB_PATH):
    backup_path = DB_PATH + ".backup"
    shutil.copy2(DB_PATH, backup_path)
    print(f"[INFO] Backed up existing DB to {backup_path}")
    os.remove(DB_PATH)
    print("[INFO] Removed old DB to recreate with new schema")

from app import create_app

app = create_app()
client = app.test_client()

print("[INFO] Database recreated with new schema")

print("=" * 60)
print("Testing Travel Guide Generator - Multi-Agent Architecture")
print("=" * 60)

# --- Test 1: List Agents ---
print("\n[Test 1] GET /api/agents")
resp = client.get("/api/agents")
agents = resp.get_json()
expected_experts = {"hotel_expert", "scene_expert", "food_expert", "route_expert"}
found_experts = {a["name"] for a in agents}
missing = expected_experts - found_experts
if missing:
    print(f"  FAIL: Missing experts: {missing}")
else:
    print(f"  PASS: All 4 experts registered")
for a in agents:
    if a["name"] in expected_experts:
        print(f"    - {a['name']}: {a['display_name']} (role={a['role_type']}, llm_config={a.get('llm_config', {})})")

# --- Test 2: List Relations ---
print("\n[Test 2] GET /api/agent-relations")
resp = client.get("/api/agent-relations")
relations = resp.get_json()
print(f"  Found {len(relations)} relations")
for r in relations:
    print(f"    - {r['source_agent']} -> {r['target_agent']} @ stage={r['trigger_stage']}, group={r.get('group', 0)}")

# --- Test 3: Chat Stream - Requirement Phase ---
print("\n[Test 3] POST /api/chat/stream (Requirement phase)")
# First, create a new session
import uuid
session_id = str(uuid.uuid4())[:8]

resp = client.post("/api/chat/stream", json={
    "session_id": session_id,
    "message": "我想去贵州，6月19日到23日，2个人，预算人均3000"
})

# Read SSE stream
stream_data = resp.data.decode("utf-8")
lines = [l.strip() for l in stream_data.split("\n") if l.strip().startswith("data:")]

content_parts = []
stage = None
for line in lines:
    data_str = line[5:].strip()
    if not data_str:
        continue
    try:
        data = json.loads(data_str)
        if data.get("type") == "content":
            content_parts.append(data.get("text", ""))
        elif data.get("type") == "done":
            stage = data.get("stage")
    except json.JSONDecodeError:
        pass

full_response = "".join(content_parts)
print(f"  Response length: {len(full_response)} chars")
print(f"  Final stage: {stage}")
print(f"  First 200 chars: {full_response[:200]}...")

# Check if stage is still REQUIREMENT (since we didn't say [TASK_DISPATCH])
if stage == "REQUIREMENT":
    print("  PASS: Stage correctly stays in REQUIREMENT")
else:
    print(f"  WARN: Stage is {stage}, expected REQUIREMENT")

# --- Test 4: Chat History ---
print(f"\n[Test 4] GET /api/chat/history/{session_id}")
resp = client.get(f"/api/chat/history/{session_id}")
history = resp.get_json()
print(f"  Messages count: {len(history)}")
for msg in history:
    print(f"    [{msg['role']}] stage={msg['stage']}: {msg['message'][:60]}...")

# --- Test 5: Guide Persistence ---
print(f"\n[Test 5] GET /api/session/{session_id}/guide")
resp = client.get(f"/api/session/{session_id}/guide")
guide = resp.get_json()
if resp.status_code == 404:
    print(f"  PASS: Guide not yet created (expected for REQUIREMENT phase)")
else:
    print(f"  Guide: {guide}")

# --- Test 6: Session List ---
print(f"\n[Test 6] GET /api/sessions")
resp = client.get("/api/sessions")
sessions = resp.get_json()
print(f"  Sessions count: {len(sessions)}")
for s in sessions[:3]:
    print(f"    - {s['session_id']}: {s['msg_count']} messages")

print("\n" + "=" * 60)
print("Basic integration tests completed.")
print("=" * 60)
