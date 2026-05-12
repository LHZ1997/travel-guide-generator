"""Flask routes for Travel Guide Generator."""
import json

from flask import Blueprint, jsonify, request, render_template, Response, stream_with_context

from config import app_config
from models import AgentConfig, AgentExecutionLog, AgentRelation, Conversation, Guide, PromptTemplate, db, generate_uuid
from services.agent_registry_service import AgentRegistryService
from services.chat_service import ChatService, ChatStage
from services.orchestration_engine import OrchestrationEngine
from services.prompt_template_service import PromptTemplateService

main_bp = Blueprint("main", __name__)
_chat_service = None


def _validate_budget(expert_results: dict, requirements: dict) -> dict:
    """Extract and validate budget from expert results.

    Returns a dict with:
        - estimated: dict of estimated costs by category
        - budget: user's budget
        - warnings: list of budget issues
    """
    import re

    budget_str = requirements.get("budget", "")
    budget_total = 0
    budget_match = re.search(r"(\d+)", str(budget_str))
    if budget_match:
        budget_total = int(budget_match.group(1))
        travelers_str = requirements.get("travelers", "1")
        travelers_match = re.search(r"(\d+)", str(travelers_str))
        travelers = int(travelers_match.group(1)) if travelers_match else 1
        budget_total = budget_total * travelers

    def extract_price(text: str) -> int:
        """Extract price numbers from text, preferring numbers near '小计' or '合计'."""
        if not text:
            return 0
        subtotal_patterns = [
            r"(?:小计|合计|总费?[用价]|预算).*?(\d{2,5})\s*(?:元|块)?",
            r"(\d{2,5})\s*(?:元|块).*?(?:小计|合计|总费?[用价]|预算)",
        ]
        for pat in subtotal_patterns:
            m = re.search(pat, text)
            if m:
                return int(m.group(1))
        prices = re.findall(r"(\d{2,5})\s*(?:元|块|/人)", str(text))
        if prices:
            return max(int(p) for p in prices)
        return 0

    estimated = {}
    category_map = {
        "hotel_expert": "住宿",
        "scene_expert": "门票",
        "food_expert": "餐饮",
        "route_expert": "交通",
    }

    for key, cat_name in category_map.items():
        text = expert_results.get(key, "")
        estimated[cat_name] = extract_price(text)

    estimated_total = sum(estimated.values())
    warnings = []

    if budget_total > 0 and estimated_total > 0:
        for cat, cost in estimated.items():
            if cost > 0 and cost > budget_total * 0.5:
                warnings.append(f"{cat}预估{cost}元，已超过总预算{budget_total}元的50%")
        if estimated_total > budget_total:
            warnings.append(
                f"预算警告：预估总费用约{estimated_total}元，超出预算{budget_total}元"
                f"（超支{estimated_total - budget_total}元）"
            )
        elif estimated_total > budget_total * 0.8:
            warnings.append(
                f"预算提醒：预估总费用约{estimated_total}元，"
                f"已达预算{budget_total}元的{int(estimated_total / budget_total * 100)}%"
            )

    return {
        "estimated": estimated,
        "estimated_total": estimated_total,
        "budget_total": budget_total,
        "warnings": warnings,
    }


def _build_summary_prompt(expert_results: dict, requirements: dict) -> str:
    """Build a prompt asking the orchestrator to summarize expert results into a final guide."""
    prompt = "请根据以下各专家的分析结果，汇总生成一份完整的结构化旅行攻略。\n\n"
    prompt += "**旅行需求**：\n"
    prompt += json.dumps(requirements, ensure_ascii=False, indent=2)
    prompt += "\n\n"

    for expert_name, result in expert_results.items():
        display_name = {
            "hotel_expert": "酒店规划",
            "scene_expert": "景点规划",
            "food_expert": "美食推荐",
            "route_expert": "路线规划",
        }.get(expert_name, expert_name)
        summary_text = result[:2000] if len(result) > 2000 else result
        prompt += f"**{display_name}**：\n{summary_text}\n\n"

    prompt += """请输出一份完整的 Markdown 格式旅行攻略，严格包含以下结构：

## 1. 行程概览
- 目的地、时间、人数、总预算一目了然

## 2. 行前准备清单
- 证件、衣物、防晒、药品、APP下载等实用清单

## 3. 每日详细行程（按天拆分）
每天包含：
- **上午**：景点+交通
- **中午**：推荐餐厅（含人均）
- **下午**：景点+交通
- **晚上**：晚餐推荐+可选活动
- **住宿**：当晚酒店

## 4. 预算总览表
用表格展示：
| 项目 | 预估费用 | 备注 |
|------|---------|------|
| 住宿 | xxx元 | x晚 |
| 门票 | xxx元 | |
| 餐饮 | xxx元 | 人均xxx×x天 |
| 交通 | xxx元 | 含大交通+当地交通 |
| **合计** | **xxx元** | 预算xxx元 |

## 5. 防坑指南和注意事项
- 至少5条具体的本地防坑建议
- 天气、安全、健康等实用提醒

要求：
- 排版精美，使用 Markdown 标题层级
- 所有价格信息必须明确标注，不得遗漏
- 语气务实，像本地老司机的实操指导
- 严禁编造不存在的景点、酒店、餐厅
- 如果某个信息来自专家推荐但你觉得不确定，标注(参考价)或(建议核实)
"""
    return prompt


def get_chat_service():
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service


@main_bp.route("/")
def index():
    """Main chat interface."""
    return render_template("index.html")


@main_bp.route("/config")
def config_page():
    """LLM configuration page."""
    return render_template("config.html")


@main_bp.route("/agents")
def agents_page():
    """Agent management page."""
    return render_template("agents.html")


@main_bp.route("/orchestration")
def orchestration_page():
    """Agent orchestration relation page."""
    return render_template("orchestration.html")


@main_bp.route("/api/config", methods=["GET"])
def get_config():
    """Get current LLM configuration."""
    return jsonify({
        "planner": app_config.planner_config.to_dict(),
        "checker": app_config.checker_config.to_dict(),
    })


@main_bp.route("/api/config", methods=["POST"])
def save_config():
    """Save LLM configuration."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    from config import LLMConfig

    if "planner" in data:
        app_config.planner_config = LLMConfig.from_dict(data["planner"])
        app_config.save_llm_config("planner", app_config.planner_config)

    if "checker" in data:
        app_config.checker_config = LLMConfig.from_dict(data["checker"])
        app_config.save_llm_config("checker", app_config.checker_config)

    # Reset chat service so next request picks up new config
    global _chat_service
    _chat_service = None

    return jsonify({"status": "ok"})


@main_bp.route("/api/chat", methods=["POST"])
def chat():
    """Process chat message."""
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Missing message"}), 400

    session_id = data.get("session_id") or generate_uuid()
    message = data["message"]

    try:
        response = get_chat_service().process_user_message(session_id, message)
        return jsonify({
            "session_id": session_id,
            "response": response,
            "stage": get_chat_service().get_current_stage(session_id),
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            "error": str(e),
            "detail": "请检查 LLM 配置（API Key、模型名称）是否正确。"
        }), 500


@main_bp.route("/api/chat/stream", methods=["POST"])
def chat_stream():
    """Process chat message with streaming response (SSE)."""
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Missing message"}), 400

    session_id = data.get("session_id") or generate_uuid()
    message = data["message"]

    try:
        stage = get_chat_service().get_current_stage(session_id)
        get_chat_service().add_message(session_id, "user", message, stage)

        # Reliable EXECUTION detection: check both message stage AND Guide status
        # The confirm_requirements endpoint sets Guide.status = "generating" as the
        # canonical signal. Message stage may lag due to DB session isolation.
        guide = Guide.query.filter_by(session_id=session_id).first()
        if guide and guide.status == "generating":
            stage = ChatStage.EXECUTION
            print(f"[SSE] Guide.status='generating', forcing stage=EXECUTION (message stage was '{stage}')", flush=True)

        history = get_chat_service().get_history(session_id)

        reasoning_parts = []
        content_parts = []

        def generate():
            nonlocal reasoning_parts, content_parts
            import time
            start_time = time.time()
            # Log planner execution start
            log = AgentExecutionLog(
                session_id=session_id,
                stage=stage,
                agent_name="planner",
                agent_role="orchestrator",
                input_text=message[:2000],
                status="running",
            )
            try:
                db.session.add(log)
                db.session.commit()
            except Exception:
                db.session.rollback()
                log = None

            try:
                # Stage-based routing
                # NOTE: REQUIREMENT_CONFIRMED is a transitional stage - user has seen
                # the requirements card and is either confirming or modifying. If they
                # confirm, the confirm_requirements endpoint already advanced to EXECUTION.
                # But due to DB session isolation, get_current_stage may still return
                # REQUIREMENT_CONFIRMED here. Force EXECUTION to ensure expert dispatch.
                effective_stage = stage
                if stage == "REQUIREMENT_CONFIRMED":
                    effective_stage = "EXECUTION"
                    # Ensure the guide status is set
                    guide = Guide.query.filter_by(session_id=session_id).first()
                    if guide and guide.status == "draft":
                        guide.status = "generating"
                        db.session.commit()

                if effective_stage == "REQUIREMENT":
                    # --- REQUIREMENT phase: normal streaming chat with planner ---
                    for chunk in get_chat_service().planner.stream(history, stage="REQUIREMENT"):
                        data_obj = json.loads(chunk)
                        if data_obj.get("type") == "done":
                            continue
                        if data_obj.get("type") == "reasoning":
                            reasoning_parts.append(data_obj.get("text", ""))
                        elif data_obj.get("type") == "content":
                            content_parts.append(data_obj.get("text", ""))
                        yield f"data: {chunk}\n\n"

                    full_response = "".join(content_parts)

                    # Detect structured options for interactive UI
                    options = get_chat_service().extract_structured_options(full_response)
                    if options:
                        yield f"data: {json.dumps({'type': 'options_ready', 'options': options}, ensure_ascii=False)}\n\n"

                    next_stage = get_chat_service()._infer_next_stage(
                        stage, message, full_response
                    )
                    clean_response = ChatService._strip_markup(full_response.replace("[TASK_DISPATCH]", ""))
                    get_chat_service().add_message(
                        session_id, "planner", clean_response, next_stage
                    )

                    if next_stage == "REQUIREMENT_CONFIRMED":
                        try:
                            get_chat_service().save_requirements(session_id, full_response)
                            get_chat_service()._run_llm_requirements_extraction(session_id)
                            req_data = get_chat_service().get_requirements_for_confirmation(session_id)
                            yield f"data: {json.dumps({'type': 'requirements_ready', 'requirements': req_data}, ensure_ascii=False)}\n\n"
                        except Exception as e:
                            print(f"[Stream] Failed to save requirements: {e}")
                            db.session.rollback()
                    else:
                        try:
                            guide = Guide.query.filter_by(session_id=session_id).first()
                            if not guide:
                                guide = Guide(session_id=session_id)
                                db.session.add(guide)
                            guide.title = guide.title or "旅行攻略"
                            db.session.commit()
                        except Exception:
                            db.session.rollback()

                elif effective_stage == "EXECUTION":
                    # --- EXECUTION phase: run expert agents then stream final guide ---
                    # First, send a "generating" status to frontend
                    status_payload = json.dumps({
                        "type": "status",
                        "text": "正在调度专家智能体生成攻略...",
                    }, ensure_ascii=False)
                    yield f"data: {status_payload}\n\n"

                    # Load requirements
                    guide = Guide.query.filter_by(session_id=session_id).first()
                    requirements = {}
                    if guide and guide.requirements:
                        requirements = json.loads(guide.requirements)

                    ctx = {"requirements": json.dumps(requirements, ensure_ascii=False)}
                    plan = get_orchestration_engine().get_execution_plan(
                        stage, source="orchestrator"
                    )
                    expert_results = {}

                    # Group experts by group number and execute with SSE events
                    groups = {}
                    for expert in plan:
                        groups.setdefault(expert.get("group", 0), []).append(expert)

                    engine = get_orchestration_engine()
                    for group_num in sorted(groups.keys()):
                        experts = groups[group_num]
                        group_names = [e["name"] for e in experts]
                        yield f"data: {json.dumps({'type': 'group_start', 'group': group_num, 'experts': group_names}, ensure_ascii=False)}\n\n"

                        from concurrent.futures import ThreadPoolExecutor, as_completed
                        with ThreadPoolExecutor(max_workers=max(len(experts), 1)) as executor:
                            futures = {}
                            for expert in experts:
                                name = expert["name"]
                                yield f"data: {json.dumps({'type': 'expert_start', 'expert': name}, ensure_ascii=False)}\n\n"
                                future = executor.submit(
                                    engine._execute_expert_safe,
                                    name,
                                    context={**ctx, **expert_results},
                                    session_id=session_id,
                                )
                                futures[future] = name

                            # Heartbeat while waiting for experts to complete
                            import time as time_mod
                            while futures:
                                done_futures = set()
                                for future in list(futures.keys()):
                                    try:
                                        result = future.result(timeout=0.5)
                                        done_futures.add(future)
                                        name = futures[future]
                                        if result is not None:
                                            expert_results[name] = result
                                            yield f"data: {json.dumps({'type': 'expert_done', 'expert': name, 'result_len': len(result)}, ensure_ascii=False)}\n\n"
                                            yield f"data: {json.dumps({'type': 'expert_result_preview', 'expert': name, 'preview': result, 'full_len': len(result)}, ensure_ascii=False)}\n\n"
                                        else:
                                            yield f"data: {json.dumps({'type': 'expert_error', 'expert': name, 'message': '执行失败或无结果'}, ensure_ascii=False)}\n\n"
                                    except TimeoutError:
                                        # Heartbeat to keep SSE connection alive
                                        yield f": heartbeat\n\n"
                                        pass
                                    except Exception as e:
                                        done_futures.add(future)
                                        name = futures[future]
                                        yield f"data: {json.dumps({'type': 'expert_error', 'expert': name, 'message': str(e)}, ensure_ascii=False)}\n\n"
                                for f in done_futures:
                                    del futures[f]

                    # Persist expert results
                    try:
                        if guide:
                            guide.expert_results = json.dumps(expert_results, ensure_ascii=False)
                            db.session.commit()
                    except Exception as e:
                        print(f"[Stream] Failed to save expert_results: {e}")
                        db.session.rollback()

                    # Budget validation
                    budget_check = _validate_budget(expert_results, requirements)
                    if budget_check.get("warnings"):
                        yield f"data: {json.dumps({'type': 'budget_warning', 'summary': budget_check}, ensure_ascii=False)}\n\n"

                    # Orchestrator composes the final guide by reviewing all expert results
                    yield f"data: {json.dumps({'type': 'orchestrator_start', 'expert_count': len(expert_results)}, ensure_ascii=False)}\n\n"

                    orch_prompt = _build_summary_prompt(expert_results, requirements)
                    orch_messages = history + [{"role": "user", "content": orch_prompt}]

                    for chunk in get_chat_service().orchestrator.stream(orch_messages, stage="COMPLETE"):
                        data_obj = json.loads(chunk)
                        if data_obj.get("type") == "done":
                            continue
                        if data_obj.get("type") == "reasoning":
                            reasoning_parts.append(data_obj.get("text", ""))
                        elif data_obj.get("type") == "content":
                            content_parts.append(data_obj.get("text", ""))
                        yield f"data: {chunk}\n\n"

                    full_response = "".join(content_parts)
                    clean_response = full_response.strip()
                    next_stage = "COMPLETE"
                    get_chat_service().add_message(
                        session_id, "orchestrator", clean_response, next_stage
                    )

                    # Save final guide
                    try:
                        guide = Guide.query.filter_by(session_id=session_id).first()
                        if not guide:
                            guide = Guide(session_id=session_id)
                            db.session.add(guide)

                        title = None
                        for line in clean_response.split("\n"):
                            if line.startswith("# "):
                                title = line[2:].strip()
                                break

                        guide.title = title or guide.title or "旅行攻略"
                        guide.content_md = clean_response
                        guide.status = "final"
                        db.session.commit()
                    except Exception:
                        db.session.rollback()

                    # Auto-run checker on the final guide
                    try:
                        check_result = get_chat_service().run_checker(session_id)
                        check_payload = json.dumps({
                            "type": "checker_result",
                            "text": check_result,
                        }, ensure_ascii=False)
                        yield f"data: {check_payload}\n\n"
                    except Exception as e:
                        print(f"[Stream] Checker auto-run failed: {e}")

                else:
                    # --- COMPLETE or other stages: normal streaming ---
                    for chunk in get_chat_service().planner.stream(history, stage=stage):
                        data_obj = json.loads(chunk)
                        if data_obj.get("type") == "done":
                            continue
                        if data_obj.get("type") == "reasoning":
                            reasoning_parts.append(data_obj.get("text", ""))
                        elif data_obj.get("type") == "content":
                            content_parts.append(data_obj.get("text", ""))
                        yield f"data: {chunk}\n\n"

                    full_response = "".join(content_parts)
                    next_stage = stage
                    clean_response = full_response.strip()
                    get_chat_service().add_message(
                        session_id, "planner", clean_response, next_stage
                    )

                # Update log
                latency = int((time.time() - start_time) * 1000)
                if log:
                    log.output_text = clean_response[:4000] if 'clean_response' in locals() else ""
                    log.latency_ms = latency
                    log.status = "success"
                    try:
                        db.session.commit()
                    except Exception:
                        db.session.rollback()

                done_payload = json.dumps({
                    "type": "done",
                    "stage": next_stage,
                    "session_id": session_id,
                }, ensure_ascii=False)
                yield f"data: {done_payload}\n\n"
            except Exception as e:
                import traceback
                traceback.print_exc()
                if log:
                    log.status = "error"
                    log.error_message = str(e)[:1000]
                    try:
                        db.session.commit()
                    except Exception:
                        db.session.rollback()
                err_payload = json.dumps({
                    "type": "error",
                    "message": str(e),
                }, ensure_ascii=False)
                yield f"data: {err_payload}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@main_bp.route("/api/session/<session_id>/confirm-requirements", methods=["POST"])
def confirm_requirements(session_id):
    """User confirms the requirements and proceeds to EXECUTION stage."""
    try:
        new_stage = get_chat_service().confirm_requirements(session_id)
        print(f"[Confirm] stage={new_stage}, session={session_id}", flush=True)
        if new_stage == "EXECUTION":
            get_chat_service().add_message(
                session_id, "user", "确认需求，开始生成攻略", new_stage
            )
        return jsonify({"stage": new_stage})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@main_bp.route("/api/session/<session_id>/reject-requirements", methods=["POST"])
def reject_requirements(session_id):
    """User rejects the requirements and goes back to REQUIREMENT for modification."""
    data = request.get_json() or {}
    feedback = data.get("feedback", "")
    new_stage = get_chat_service().reject_requirements(session_id, feedback)
    return jsonify({"stage": new_stage})


@main_bp.route("/api/session/<session_id>/requirements", methods=["GET"])
def get_session_requirements(session_id):
    """Get the current requirements for confirmation display."""
    req_data = get_chat_service().get_requirements_for_confirmation(session_id)
    return jsonify(req_data)


@main_bp.route("/api/guide/<int:guide_id>", methods=["GET"])
def get_guide(guide_id):
    """Get guide by ID."""
    guide = Guide.query.get_or_404(guide_id)
    return jsonify(guide.to_dict())


@main_bp.route("/api/guide/<int:guide_id>", methods=["PUT"])
def update_guide(guide_id):
    """Update guide content."""
    guide = Guide.query.get_or_404(guide_id)
    data = request.get_json()

    if "content_md" in data:
        guide.content_md = data["content_md"]
    if "title" in data:
        guide.title = data["title"]
    if "status" in data:
        guide.status = data["status"]

    db.session.commit()
    return jsonify(guide.to_dict())


@main_bp.route("/api/guide/<int:guide_id>/check", methods=["POST"])
def check_guide(guide_id):
    """Trigger checker agent on guide."""
    guide = Guide.query.get_or_404(guide_id)
    result = get_chat_service().run_checker(guide.session_id)
    return jsonify({"result": result})


@main_bp.route("/api/guide/<int:guide_id>/export", methods=["POST"])
def export_guide(guide_id):
    """Export guide to HTML or PDF."""
    guide = Guide.query.get_or_404(guide_id)
    data = request.get_json() or {}
    fmt = data.get("format", "html")

    if not guide.content_md:
        return jsonify({"error": "Guide content is empty"}), 400

    from utils.md2html import markdown_to_html

    html_content = markdown_to_html(guide.content_md)

    if fmt == "html":
        return jsonify({
            "format": "html",
            "content": html_content,
        })

    if fmt == "pdf":
        import tempfile
        from pathlib import Path
        from utils.pdf_export import html_to_pdf

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False, encoding="utf-8"
        ) as f:
            f.write(html_content)
            html_path = f.name

        pdf_path = str(Path(html_path).with_suffix(".pdf"))
        html_to_pdf(html_path, pdf_path)

        return jsonify({
            "format": "pdf",
            "pdf_path": pdf_path,
        })

    return jsonify({"error": "Unsupported format"}), 400


@main_bp.route("/api/session/<session_id>/guide", methods=["GET"])
def get_session_guide(session_id):
    """Get guide for a session."""
    guide = Guide.query.filter_by(session_id=session_id).first()
    if not guide:
        return jsonify({"error": "当前会话暂无攻略内容"}), 404
    return jsonify(guide.to_dict())


@main_bp.route("/api/session/<session_id>/check", methods=["POST"])
def check_session_guide(session_id):
    """Trigger checker agent on session's guide."""
    guide = Guide.query.filter_by(session_id=session_id).first()
    if not guide or not guide.content_md:
        return jsonify({"error": "当前会话暂无攻略内容"}), 404
    result = get_chat_service().run_checker(session_id)
    return jsonify({"result": result})


@main_bp.route("/api/session/<session_id>/export", methods=["POST"])
def export_session_guide(session_id):
    """Export session's guide to HTML or PDF."""
    guide = Guide.query.filter_by(session_id=session_id).first()
    if not guide or not guide.content_md:
        return jsonify({"error": "当前会话暂无攻略内容"}), 404

    data = request.get_json() or {}
    fmt = data.get("format", "html")

    from utils.md2html import markdown_to_html

    html_content = markdown_to_html(guide.content_md)

    if fmt == "html":
        return jsonify({
            "format": "html",
            "content": html_content,
        })

    if fmt == "pdf":
        import tempfile
        from pathlib import Path
        from utils.pdf_export import html_to_pdf

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False, encoding="utf-8"
        ) as f:
            f.write(html_content)
            html_path = f.name

        pdf_path = str(Path(html_path).with_suffix(".pdf"))
        html_to_pdf(html_path, pdf_path)

        return jsonify({
            "format": "pdf",
            "pdf_path": pdf_path,
        })

    return jsonify({"error": "Unsupported format"}), 400


@main_bp.route("/api/session/<session_id>/rerun-expert", methods=["POST"])
def rerun_expert(session_id):
    """Re-run a single expert agent."""
    data = request.get_json() or {}
    expert_name = data.get("expert_name")
    if not expert_name:
        return jsonify({"error": "expert_name is required"}), 400

    guide = Guide.query.filter_by(session_id=session_id).first()
    if not guide:
        return jsonify({"error": "Session not found"}), 404

    requirements = {}
    if guide.requirements:
        requirements = json.loads(guide.requirements)

    expert_results = data.get("expert_results", {})
    if not expert_results and guide.expert_results:
        try:
            expert_results = json.loads(guide.expert_results)
        except Exception:
            expert_results = {}

    ctx = {
        "requirements": json.dumps(requirements, ensure_ascii=False),
        **expert_results,
    }

    engine = get_orchestration_engine()
    result = engine._execute_expert_safe(
        expert_name, context=ctx, session_id=session_id
    )
    if result is None:
        return jsonify({"error": f"Expert {expert_name} execution failed"}), 500

    try:
        expert_results[expert_name] = result
        guide.expert_results = json.dumps(expert_results, ensure_ascii=False)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[rerun-expert] Failed to save results: {e}")

    return jsonify({
        "expert_name": expert_name,
        "result": result,
    })


@main_bp.route("/api/session/<session_id>/regenerate-guide", methods=["POST"])
def regenerate_guide(session_id):
    """Regenerate final guide from existing expert results."""
    guide = Guide.query.filter_by(session_id=session_id).first()
    if not guide:
        return jsonify({"error": "Session not found"}), 404

    requirements = {}
    if guide.requirements:
        requirements = json.loads(guide.requirements)

    data = request.get_json() or {}
    expert_results = data.get("expert_results", {})
    if not expert_results and guide.expert_results:
        try:
            expert_results = json.loads(guide.expert_results)
        except Exception:
            expert_results = {}

    # Persist edited expert_results from frontend
    if data.get("expert_results"):
        try:
            guide.expert_results = json.dumps(expert_results, ensure_ascii=False)
            db.session.commit()
        except Exception:
            db.session.rollback()

    summary_prompt = _build_summary_prompt(expert_results, requirements)
    history = get_chat_service().get_history(session_id)
    summary_messages = history + [{"role": "user", "content": summary_prompt}]

    try:
        response = get_chat_service().planner.generate(summary_messages, stage="COMPLETE")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    try:
        title = None
        for line in response.split("\n"):
            if line.startswith("# "):
                title = line[2:].strip()
                break
        guide.title = title or guide.title or "旅行攻略"
        guide.content_md = response
        guide.status = "final"
        db.session.commit()
    except Exception:
        db.session.rollback()

    return jsonify({
        "title": guide.title,
        "content_md": guide.content_md,
    })


@main_bp.route("/api/chat/history/<session_id>", methods=["GET"])
def get_chat_history(session_id):
    """Get conversation history for a session."""
    rows = (
        Conversation.query.filter_by(session_id=session_id)
        .order_by(Conversation.created_at)
        .all()
    )
    return jsonify([r.to_dict() for r in rows])


@main_bp.route("/api/sessions", methods=["GET"])
def list_sessions():
    """List all active sessions with latest message info."""
    from sqlalchemy import func

    subq = (
        db.session.query(
            Conversation.session_id,
            func.max(Conversation.created_at).label("last_at"),
            func.count(Conversation.id).label("msg_count"),
        )
        .group_by(Conversation.session_id)
        .subquery()
    )

    results = (
        db.session.query(
            subq.c.session_id,
            subq.c.last_at,
            subq.c.msg_count,
        )
        .order_by(subq.c.last_at.desc())
        .all()
    )

    sessions = []
    for sid, last_at, msg_count in results:
        sessions.append({
            "session_id": sid,
            "last_at": last_at.isoformat() if last_at else None,
            "msg_count": msg_count,
        })
    return jsonify(sessions)


@main_bp.route("/api/sessions/<session_id>/execution-logs", methods=["GET"])
def get_execution_logs(session_id):
    """Get execution logs for a session."""
    logs = (
        AgentExecutionLog.query.filter_by(session_id=session_id)
        .order_by(AgentExecutionLog.created_at.desc())
        .all()
    )
    return jsonify([l.to_dict() for l in logs])


# ========== Agent Management Routes ==========
_agent_registry = None
_prompt_service = None
_orchestration_engine = None


def get_agent_registry():
    global _agent_registry
    if _agent_registry is None:
        _agent_registry = AgentRegistryService()
    return _agent_registry


def get_prompt_service():
    global _prompt_service
    if _prompt_service is None:
        _prompt_service = PromptTemplateService()
    return _prompt_service


def get_orchestration_engine():
    global _orchestration_engine
    if _orchestration_engine is None:
        _orchestration_engine = OrchestrationEngine()
    return _orchestration_engine


@main_bp.route("/api/agents", methods=["GET"])
def list_agents():
    """List all active agents."""
    role_type = request.args.get("role_type")
    agents = get_agent_registry().list_agents(role_type=role_type)
    return jsonify(agents)


@main_bp.route("/api/agents", methods=["POST"])
def create_agent():
    """Create a new agent."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    name = data.get("name", "").strip().lower()
    display_name = data.get("display_name", "").strip()
    if not name or not display_name:
        return jsonify({"error": "name and display_name are required"}), 400

    if AgentConfig.query.filter_by(name=name).first():
        return jsonify({"error": f"Agent '{name}' already exists"}), 409

    agent = AgentConfig(
        name=name,
        display_name=display_name,
        description=data.get("description", ""),
        role_type=data.get("role_type", "expert"),
        llm_config=json.dumps(data.get("llm_config", {}), ensure_ascii=False),
        is_active=data.get("is_active", True),
        icon=data.get("icon", "🤖"),
    )
    db.session.add(agent)
    db.session.commit()
    get_agent_registry().refresh_cache()
    return jsonify(agent.to_dict()), 201


@main_bp.route("/api/agents/<name>", methods=["GET"])
def get_agent(name):
    """Get a single agent."""
    agent = AgentConfig.query.filter_by(name=name).first()
    if not agent:
        return jsonify({"error": "Agent not found"}), 404
    return jsonify(agent.to_dict())


@main_bp.route("/api/agents/<name>", methods=["PUT"])
def update_agent(name):
    """Update an agent."""
    agent = AgentConfig.query.filter_by(name=name).first()
    if not agent:
        return jsonify({"error": "Agent not found"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    if "display_name" in data:
        agent.display_name = data["display_name"]
    if "description" in data:
        agent.description = data["description"]
    if "role_type" in data:
        agent.role_type = data["role_type"]
    if "llm_config" in data:
        agent.llm_config = json.dumps(data["llm_config"], ensure_ascii=False)
    if "is_active" in data:
        agent.is_active = bool(data["is_active"])
    if "icon" in data:
        agent.icon = data["icon"]

    db.session.commit()
    get_agent_registry().refresh_cache()
    return jsonify(agent.to_dict())


@main_bp.route("/api/agents/<name>", methods=["DELETE"])
def delete_agent(name):
    """Delete an agent (soft check for relations)."""
    agent = AgentConfig.query.filter_by(name=name).first()
    if not agent:
        return jsonify({"error": "Agent not found"}), 404

    # Check for existing relations
    relations = AgentRelation.query.filter(
        (AgentRelation.source_agent == name) | (AgentRelation.target_agent == name)
    ).first()
    if relations:
        return jsonify({"error": "Cannot delete agent with active relations"}), 400

    db.session.delete(agent)
    db.session.commit()
    get_agent_registry().refresh_cache()
    return jsonify({"status": "deleted"})


@main_bp.route("/api/agents/<name>/test-connection", methods=["POST"])
def test_agent_connection(name):
    """Test LLM connection for an agent."""
    agent = AgentConfig.query.filter_by(name=name).first()
    if not agent:
        return jsonify({"error": "Agent not found"}), 404

    try:
        client = get_agent_registry().create_llm_client(name)
        # Send a simple test message
        test_messages = [{"role": "user", "content": "Hi"}]
        response = client.chat(test_messages)
        return jsonify({"status": "ok", "response_preview": response[:100]})
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# ========== Agent Relation Routes ==========
@main_bp.route("/api/agent-relations", methods=["GET"])
def list_relations():
    """List all active relations."""
    source = request.args.get("source")
    query = AgentRelation.query.filter_by(is_active=True)
    if source:
        query = query.filter_by(source_agent=source)
    relations = query.order_by(AgentRelation.order_index).all()
    return jsonify([r.to_dict() for r in relations])


@main_bp.route("/api/agent-relations", methods=["POST"])
def create_relation():
    """Create a new relation."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    source = data.get("source_agent", "").strip()
    target = data.get("target_agent", "").strip()
    if not source or not target:
        return jsonify({"error": "source_agent and target_agent are required"}), 400

    # Validate agents exist
    if not AgentConfig.query.filter_by(name=source, is_active=True).first():
        return jsonify({"error": f"Source agent '{source}' not found"}), 404
    if not AgentConfig.query.filter_by(name=target, is_active=True).first():
        return jsonify({"error": f"Target agent '{target}' not found"}), 404

    # Check for cycle
    engine = get_orchestration_engine()
    if not engine.can_add_relation(source, target):
        return jsonify({"error": "This relation would create a cycle"}), 400

    # Check duplicate
    existing = AgentRelation.query.filter_by(
        source_agent=source, target_agent=target, trigger_stage=data.get("trigger_stage", "")
    ).first()
    if existing:
        return jsonify({"error": "Relation already exists"}), 409

    rel = AgentRelation(
        source_agent=source,
        target_agent=target,
        trigger_stage=data.get("trigger_stage", ""),
        trigger_condition=data.get("trigger_condition", ""),
        input_mapping=json.dumps(data.get("input_mapping", {}), ensure_ascii=False),
        output_mapping=json.dumps(data.get("output_mapping", {}), ensure_ascii=False),
        order_index=data.get("order_index", 0),
        is_active=data.get("is_active", True),
    )
    db.session.add(rel)
    db.session.commit()
    get_agent_registry().refresh_cache()
    return jsonify(rel.to_dict()), 201


@main_bp.route("/api/agent-relations/<int:rel_id>", methods=["PUT"])
def update_relation(rel_id):
    """Update a relation."""
    rel = AgentRelation.query.get_or_404(rel_id)
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    if "trigger_stage" in data:
        rel.trigger_stage = data["trigger_stage"]
    if "trigger_condition" in data:
        rel.trigger_condition = data["trigger_condition"]
    if "input_mapping" in data:
        rel.input_mapping = json.dumps(data["input_mapping"], ensure_ascii=False)
    if "output_mapping" in data:
        rel.output_mapping = json.dumps(data["output_mapping"], ensure_ascii=False)
    if "order_index" in data:
        rel.order_index = data["order_index"]
    if "is_active" in data:
        rel.is_active = bool(data["is_active"])

    db.session.commit()
    get_agent_registry().refresh_cache()
    return jsonify(rel.to_dict())


@main_bp.route("/api/agent-relations/<int:rel_id>", methods=["DELETE"])
def delete_relation(rel_id):
    """Delete a relation."""
    rel = AgentRelation.query.get_or_404(rel_id)
    db.session.delete(rel)
    db.session.commit()
    get_agent_registry().refresh_cache()
    return jsonify({"status": "deleted"})


@main_bp.route("/api/agent-relations/graph", methods=["GET"])
def get_relation_graph():
    """Get graph data for visualization."""
    agents = get_agent_registry().list_agents()
    relations = get_agent_registry()._relations_cache

    nodes = [{"id": a["name"], "label": a["display_name"], "role": a["role_type"]} for a in agents]
    edges = [{"source": r["source_agent"], "target": r["target_agent"], "stage": r["trigger_stage"]} for r in relations]

    return jsonify({"nodes": nodes, "edges": edges})


# ========== Prompt Template Routes ==========
@main_bp.route("/api/agents/<name>/prompts", methods=["GET"])
def list_prompts(name):
    """List all prompt templates for an agent."""
    agent = AgentConfig.query.filter_by(name=name).first()
    if not agent:
        return jsonify({"error": "Agent not found"}), 404

    templates = PromptTemplate.query.filter_by(agent_name=name, is_active=True).all()
    return jsonify([t.to_dict() for t in templates])


@main_bp.route("/api/agents/<name>/prompts", methods=["POST"])
def create_prompt(name):
    """Create a prompt template for an agent."""
    agent = AgentConfig.query.filter_by(name=name).first()
    if not agent:
        return jsonify({"error": "Agent not found"}), 404

    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    layer = data.get("layer", "role")
    template_name = data.get("name", "system_prompt")

    # Core layer can only have one per agent
    if layer == "core":
        existing = PromptTemplate.query.filter_by(agent_name=name, layer="core").first()
        if existing:
            return jsonify({"error": "Core layer already exists for this agent"}), 409

    content = data.get("content", "")
    variables = data.get("variables", [])

    # Validate variables
    svc = get_prompt_service()
    undeclared = svc.validate_template(content, variables)
    if undeclared:
        return jsonify({"error": f"Undeclared variables: {undeclared}"}), 400

    result = svc.create_or_update_template(
        agent_name=name,
        layer=layer,
        name=template_name,
        content=content,
        variables=variables,
        is_editable=data.get("is_editable", layer != "core"),
    )
    svc.refresh_cache()
    return jsonify(result), 201


@main_bp.route("/api/agents/<name>/prompts/<int:template_id>", methods=["GET"])
def get_prompt(name, template_id):
    """Get a single prompt template."""
    t = PromptTemplate.query.filter_by(id=template_id, agent_name=name).first()
    if not t:
        return jsonify({"error": "Template not found"}), 404
    return jsonify(t.to_dict())


@main_bp.route("/api/agents/<name>/prompts/<int:template_id>", methods=["PUT"])
def update_prompt(name, template_id):
    """Update a prompt template."""
    t = PromptTemplate.query.filter_by(id=template_id, agent_name=name).first()
    if not t:
        return jsonify({"error": "Template not found"}), 404

    if not t.is_editable:
        return jsonify({"error": "This template layer is not editable"}), 403

    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    if "content" in data:
        t.content = data["content"]
    if "variables" in data:
        t.variables = json.dumps(data["variables"], ensure_ascii=False)
    if "is_active" in data:
        t.is_active = bool(data["is_active"])

    t.version += 1
    db.session.commit()
    get_prompt_service().refresh_cache()
    return jsonify(t.to_dict())


@main_bp.route("/api/agents/<name>/prompts/render", methods=["POST"])
def render_prompt(name):
    """Render prompt with variables for preview."""
    agent = AgentConfig.query.filter_by(name=name).first()
    if not agent:
        return jsonify({"error": "Agent not found"}), 404

    data = request.get_json() or {}
    variables = data.get("variables", {})

    svc = get_prompt_service()
    rendered, missing = svc.render_prompt(name, variables)

    return jsonify({
        "rendered": rendered,
        "missing_variables": missing,
        "is_valid": len(missing) == 0,
    })


@main_bp.route("/api/agents/generate-prompt", methods=["POST"])
def generate_prompt():
    """Use AI to generate role and format prompt templates for a new agent."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "Invalid JSON"}), 400

    description = data.get("description", "").strip()
    role_type = data.get("role_type", "expert")

    if not description:
        return jsonify({"error": "description is required"}), 400

    meta_prompt = f"""请根据以下描述，为一位AI智能体生成两个Prompt模板：

1. role层：角色定义和人设描述（200字以内，中文）
2. format层：输出格式要求（如果适用，100字以内，中文）

如果描述中涉及需要外部注入的动态信息（如目的地、时间、预算等），请以 {{变量名}} 格式标注变量。

描述：{description}
角色类型：{role_type}

请以纯JSON格式返回，不要包含markdown代码块标记：
{{
  "role": {{"content": "...", "variables": [{{"name": "...", "default": "..."}}]}},
  "format": {{"content": "...", "variables": []}}
}}
"""

    try:
        from services.llm_service import LLMFactory
        client = LLMFactory.create(app_config.planner_config)
        messages = [{"role": "user", "content": meta_prompt}]
        response = client.chat(messages)

        # Extract JSON from response
        import re
        # Try to find JSON object
        json_match = re.search(r'\{[\s\S]*\}', response)
        if not json_match:
            return jsonify({"error": "LLM did not return valid JSON"}), 500

        result = json.loads(json_match.group())

        # Validate structure
        if "role" not in result or "format" not in result:
            return jsonify({"error": "Invalid response structure from LLM"}), 500

        return jsonify(result)
    except json.JSONDecodeError as e:
        return jsonify({"error": f"Failed to parse LLM response as JSON: {str(e)}"}), 500
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"LLM generation failed: {str(e)}"}), 500
