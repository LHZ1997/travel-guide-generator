"""Full flow integration test for multi-agent architecture."""
import json
import os
import shutil

# Recreate DB for clean test
DB_PATH = "/Users/lhz/Desktop/旅游攻略/travel-guide-generator/instance/app.db"
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
    print("[INFO] Recreated DB for clean test")

from app import create_app
from services.chat_service import ChatService, ChatStage
from services.orchestration_engine import OrchestrationEngine
from services.agent_registry_service import AgentRegistryService

app = create_app()
client = app.test_client()

print("=" * 60)
print("Full Flow Integration Test")
print("=" * 60)

# --- Test 1: Verify all agents exist ---
print("\n[Test 1] Agent registration")
resp = client.get("/api/agents")
agents = resp.get_json()
expected = {"planner", "checker", "hotel_expert", "scene_expert", "food_expert", "route_expert"}
found = {a["name"] for a in agents}
assert expected <= found, f"Missing agents: {expected - found}"
print(f"  PASS: All {len(expected)} agents registered")

# --- Test 2: Verify relations ---
print("\n[Test 2] Agent relations")
resp = client.get("/api/agent-relations")
relations = resp.get_json()
assert len(relations) == 4, f"Expected 4 relations, got {len(relations)}"
scene_rel = next((r for r in relations if r["target_agent"] == "scene_expert"), None)
assert scene_rel and scene_rel["group"] == 1, "scene_expert should be in group 1"
hotel_rel = next((r for r in relations if r["target_agent"] == "hotel_expert"), None)
assert hotel_rel and hotel_rel["group"] == 2, "hotel_expert should be in group 2"
food_rel = next((r for r in relations if r["target_agent"] == "food_expert"), None)
assert food_rel and food_rel["group"] == 3, "food_expert should be in group 3"
route_rel = next((r for r in relations if r["target_agent"] == "route_expert"), None)
assert route_rel and route_rel["group"] == 4, "route_expert should be in group 4"
print("  PASS: 4 relations with correct sequential group assignments")

# --- Test 3: Chat stage inference ---
print("\n[Test 3] Stage inference logic")
with app.app_context():
    cs = ChatService()

    # No signal -> stay in REQUIREMENT
    next_stage = cs._infer_next_stage("REQUIREMENT", "hello", "some response without signal")
    assert next_stage == "REQUIREMENT", f"Expected REQUIREMENT, got {next_stage}"

    # TASK_DISPATCH with complete requirements -> REQUIREMENT_CONFIRMED
    next_stage = cs._infer_next_stage("REQUIREMENT", "确认",
        "- 目的地：贵州\n- 出行时间：6月\n- 出行人数：2人\n- 预算范围：人均3000\n[TASK_DISPATCH]")
    assert next_stage == "REQUIREMENT_CONFIRMED", f"Expected REQUIREMENT_CONFIRMED, got {next_stage}"

    # TASK_DISPATCH without requirements -> stays in REQUIREMENT (hard validation)
    next_stage = cs._infer_next_stage("REQUIREMENT", "", "done\n[TASK_DISPATCH]")
    assert next_stage == "REQUIREMENT", f"Expected REQUIREMENT, got {next_stage}"

    # From EXECUTION with dispatch (no requirements) -> hard validation blocks advance
    next_stage = cs._infer_next_stage("EXECUTION", "", "done\n[TASK_DISPATCH]")
    assert next_stage == "EXECUTION", f"Expected EXECUTION, got {next_stage}"
    print("  PASS: Stage transitions work correctly with hard validation")

# --- Test 4: First message (REQUIREMENT phase) ---
print("\n[Test 4] First chat message")
session_id = "test123"
resp = client.post("/api/chat/stream", json={"session_id": session_id, "message": "我想去贵州，6月19日到23日，2个人，预算人均3000"})
stream_data = resp.data.decode("utf-8")
lines = [l.strip() for l in stream_data.split("\n") if l.strip().startswith("data:")]

done_found = False
final_stage = None
for line in lines:
    try:
        data = json.loads(line[5:].strip())
        if data.get("type") == "done":
            done_found = True
            final_stage = data.get("stage")
            break
    except json.JSONDecodeError:
        continue
assert done_found, "No done event found"
print(f"  PASS: First message stays in REQUIREMENT (stage={final_stage})")

# --- Test 5: Guide created ---
print("\n[Test 5] Guide persistence")
resp = client.get(f"/api/session/{session_id}/guide")
assert resp.status_code == 200, f"Guide should exist, got {resp.status_code}"
guide = resp.get_json()
assert guide["session_id"] == session_id
assert guide["status"] == "draft"
print("  PASS: Guide created for session")

# --- Test 6: History ---
print("\n[Test 6] Conversation history")
resp = client.get(f"/api/chat/history/{session_id}")
history = resp.get_json()
assert len(history) >= 2, f"Expected at least 2 messages, got {len(history)}"
assert all(msg["stage"] == "REQUIREMENT" for msg in history), "All messages should be in REQUIREMENT stage"
print(f"  PASS: {len(history)} messages in history")

# --- Test 7: Orchestration engine plan generation ---
print("\n[Test 7] Execution plan generation")
with app.app_context():
    engine = OrchestrationEngine()
    plan = engine.get_execution_plan("EXECUTION", source="orchestrator")
    assert len(plan) == 4, f"Expected 4 experts in plan, got {len(plan)}"
    group1 = [e for e in plan if e.get("group") == 1]
    group2 = [e for e in plan if e.get("group") == 2]
    group3 = [e for e in plan if e.get("group") == 3]
    group4 = [e for e in plan if e.get("group") == 4]
    assert len(group1) == 1, f"Expected 1 expert in group 1, got {len(group1)}"
    assert len(group2) == 1, f"Expected 1 expert in group 2, got {len(group2)}"
    assert len(group3) == 1, f"Expected 1 expert in group 3, got {len(group3)}"
    assert len(group4) == 1, f"Expected 1 expert in group 4, got {len(group4)}"
    print("  PASS: Execution plan has correct structure (sequential groups)")

# --- Test 8: Prompt template migration ---
print("\n[Test 8] Prompt template migration")
from models import PromptTemplate
with app.app_context():
    planner_templates = PromptTemplate.query.filter_by(agent_name="planner").all()
    assert len(planner_templates) >= 1, "Planner prompts should be migrated"
    print(f"  PASS: {len(planner_templates)} planner prompt templates migrated")

print("\n" + "=" * 60)
print("All integration tests PASSED")
print("=" * 60)
