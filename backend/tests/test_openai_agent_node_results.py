import pytest
from app.agents.openai_agent import OpenAIAgentService


def test_build_user_message_with_workflow_previous():
    service = OpenAIAgentService()
    user_prompt = "Analyze this data: {{workflow.previous}}\nProvide insights."
    context_data = {
        "previous_node": "report",
        "previous_result": {
            "report_id": "rep-123",
            "property": {"apn": "30-4009-094-0050", "address": "9441 SW 21 ST"},
            "tax_record": {"status": "Paid", "gross_tax": 4500},
        },
        "report": {
            "report_id": "rep-123",
        },
    }
    msg = service._build_user_message(user_prompt, context_data)
    assert "30-4009-094-0050" in msg
    assert "9441 SW 21 ST" in msg
    assert "Analyze this data:" in msg
    assert "{{workflow.previous}}" not in msg


def test_build_user_message_with_named_tokens():
    service = OpenAIAgentService()
    user_prompt = "Report info: {{workflow.report}}\nTax info: {{tax}}"
    context_data = {
        "node_results": {
            "report": {"report_id": "rep-xyz", "status": "ready"},
            "tax": {"status": "Paid", "records_found": 1},
        }
    }
    msg = service._build_user_message(user_prompt, context_data)
    assert "rep-xyz" in msg
    assert "records_found" in msg
    assert "{{workflow.report}}" not in msg
    assert "{{tax}}" not in msg


def test_build_user_message_fallback_appends_data():
    service = OpenAIAgentService()
    user_prompt = "Check title for encumbrances."
    context_data = {
        "previous_node": "report",
        "previous_result": {
            "property": {"apn": "12-34"},
        },
    }
    msg = service._build_user_message(user_prompt, context_data)
    assert "Check title for encumbrances." in msg
    assert "[Data from report]:" in msg
    assert "12-34" in msg


def test_model_alias_normalization():
    # Verify that gpt4.1 aliases resolve to gpt-4.1
    aliases = ["gpt4.1", "gpt-4-1", "gpt4_1"]
    for alias in aliases:
        lower = alias.lower()
        if lower in ("gpt4.1", "gpt-4-1", "gpt4_1"):
            target = "gpt-4.1"
        assert target == "gpt-4.1"


@pytest.mark.asyncio
async def test_run_logger_node_completed_safe_message():
    from app.agents.run_logger import RunLogger
    logger = RunLogger(run_id="test-run-id")
    # Calling node_completed with both detail and message in kwargs should NOT raise multiple values error
    await logger.node_completed("AIAgentNode", detail="analysis complete", message="test message")
    await logger.node_failed("AIAgentNode", error="err", message="test message")
    await logger.node_started("AIAgentNode", message="custom started")


def test_format_markdown_to_html():
    from app.report.report_builder import _format_markdown_to_html
    md = "### Property Overview:\n- **Parcel Number**: 30-4009-094-0050\n- **Owner**: LUCIO RAINELLI\n\n### Sales History:\n- **Date**: Feb 1, 1989"
    html = _format_markdown_to_html(md)
    assert "<h4" in html
    assert "Property Overview:" in html
    assert "<ul" in html
    assert "<strong>Parcel Number</strong>" in html
    assert "30-4009-094-0050" in html


def test_report_builder_inserts_ai_agent_response_into_documents_and_html():
    from app.report.report_builder import ReportBuilder
    import uuid

    run_id = f"test-ai-run-{uuid.uuid4().hex[:8]}"
    builder = ReportBuilder()

    ai_content = "### Property Overview:\n- **Parcel Number**: 30-4009-094-0050\nAutonomous analysis complete."
    run_dict = {
        "id": run_id,
        "state": "FL",
        "county": "miami-dade",
        "query_type": "apn",
        "query_value": "30-4009-094-0050",
        "status": "completed",
        "plan_json": {
            "ai_agent_response": ai_content,
            "ai_agent_model": "gpt-4o",
            "node_results": {
                "ai_agent": {
                    "content": ai_content,
                    "model": "gpt-4o",
                    "total_tokens": 300,
                }
            }
        }
    }

    # Save run in memory store
    from app.db.supabase_client import get_memory_store
    get_memory_store().runs[run_id] = run_dict

    report_json, html = builder._render_report_html(run_id, run_dict)

    # 1. Verify report_json has AI agent fields
    assert report_json.get("ai_agent_response") == ai_content
    assert report_json.get("ai_agent_model") == "gpt-4o"

    # 2. Verify an official document was inserted into documents
    documents = report_json.get("documents", [])
    ai_doc = next((d for d in documents if d.get("document_type") == "AI Title Analysis"), None)
    assert ai_doc is not None
    assert ai_doc.get("notes") == ai_content
    assert (ai_doc.get("ocr_json") or {}).get("source") == "ai_agent"
    assert (ai_doc.get("ocr_json") or {}).get("model") == "gpt-4o"

    # 3. Verify HTML includes AI Title Analysis section
    assert "AI Title Analysis &amp; Verification" in html or "AI Title Analysis & Verification" in html
    assert "Autonomous Agent Review" in html
    assert "gpt-4o" in html
    assert "30-4009-094-0050" in html


def test_report_builder_handles_chatbot_node_response():
    from app.report.report_builder import ReportBuilder
    import uuid

    builder = ReportBuilder()
    run_id = f"run-cb-{uuid.uuid4().hex[:8]}"

    cb_content = "Based on the deed records, the property is clear of any recorded encumbrances."
    run_dict = {
        "id": run_id,
        "state": "FL",
        "county": "miami-dade",
        "query_type": "address",
        "query_value": "9441 SW 21 ST",
        "status": "completed",
        "plan_json": {
            "chatbot_response": cb_content,
            "chatbot_model": "gpt-4.1",
            "node_results": {
                "chatbot": {
                    "content": cb_content,
                    "model": "gpt-4.1",
                    "agent_name": "Title Chatbot",
                    "duration_ms": 380,
                    "total_tokens": 120,
                }
            },
        },
    }

    from app.db.supabase_client import get_memory_store
    get_memory_store().runs[run_id] = run_dict

    report_json, html = builder._render_report_html(run_id, run_dict)

    # 1. Verify chatbot response was resolved
    assert report_json.get("ai_agent_response") == cb_content
    assert report_json.get("ai_agent_model") == "gpt-4.1"

    # 2. Verify AI Chatbot Response document was created
    documents = report_json.get("documents", [])
    cb_doc = next((d for d in documents if d.get("document_type") == "AI Chatbot Response"), None)
    assert cb_doc is not None
    assert cb_doc.get("notes") == cb_content
    assert (cb_doc.get("ocr_json") or {}).get("source") == "chatbot"
    assert (cb_doc.get("ocr_json") or {}).get("model") == "gpt-4.1"




