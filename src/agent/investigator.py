"""Bounded Investigation Agent for ClaimCheck 2.0.

Investigates unresolved findings (needs_review, unable_to_verify) and policy ambiguities
using a strictly bounded iteration loop (maximum 2 iterations).
Selects actions via the fast model (NVIDIA Nemotron via Nebius Token Factory)
enforcing strict JSON and Pydantic validation:
- 'ask_user': Request a missing fact defined in fact vocabulary from the user.
- 'search_tavily': Query Tavily for external statutory or regulatory context.
- 'escalate': Escalate to a human claims adjudicator.

Follows strict safety rules:
- No emojis anywhere.
- No live network or AI calls unless explicitly invoked via client.
- Hard cap of at most 2 iterations.
- Never changes a finding status when Tavily guidance is attached.
- Never prints, logs, or stores secret keys.
"""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Callable, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src import settings
from src.agent import tavily_client
from src.engine.rule_engine import evaluate
from src.fact_vocabulary import FACT_VOCABULARY
from src.schemas import (
    Ambiguity,
    ClaimFact,
    Finding,
    FindingStatus,
    Rulebook,
    SourceRef,
)


class ActionType(str, Enum):
    """Permitted investigation actions."""
    ASK_USER = "ask_user"
    SEARCH_TAVILY = "search_tavily"
    ESCALATE = "escalate"


class InvestigationAction(BaseModel):
    """Pydantic model validating the action chosen by the fast model."""
    model_config = ConfigDict(extra="ignore")

    action: ActionType
    reason: str = Field(..., min_length=1)
    question: Optional[str] = None
    query: Optional[str] = None
    missing_fact: Optional[str] = None


class InvestigationItem(BaseModel):
    """Individual item investigated by the agent."""
    item_id: str
    item_type: Literal["finding", "ambiguity"]
    description: str
    status: str
    action: Optional[InvestigationAction] = None
    external_guidance: List[Dict[str, str]] = Field(default_factory=list)
    user_response: Optional[Any] = None
    resolved: bool = False
    requires_human_review: bool = True
    iteration: int = 1


# Backward compatibility aliases
InvestigationFinding = InvestigationItem


class InvestigationResult(BaseModel):
    """Aggregated output of bounded investigation workflow."""
    items: List[InvestigationItem] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)
    facts: List[ClaimFact] = Field(default_factory=list)
    iterations_run: int = 0
    max_iterations_reached: bool = False
    audit_log: List[Dict[str, Any]] = Field(default_factory=list)
    requires_human_review: bool = True


InvestigationReport = InvestigationResult


SYSTEM_PROMPT = (
    "You are a claims investigation agent for health insurance reimbursement.\n"
    "Given an unresolved finding or policy ambiguity, choose exactly ONE action:\n"
    "1. 'ask_user': When a required claim fact is missing from the submitted documents.\n"
    "   You must provide 'missing_fact' (a valid key from the vocabulary) and a 'question'.\n"
    "2. 'search_tavily': When a policy clause or statutory regulation is ambiguous or undefined.\n"
    "   You must provide 'query'.\n"
    "3. 'escalate': When the issue involves clinical judgment, conflicting evidence, or human discretion.\n\n"
    "Respond with ONLY a JSON object:\n"
    "{\n"
    '  "action": "ask_user" | "search_tavily" | "escalate",\n'
    '  "reason": "<explanation>",\n'
    '  "missing_fact": "<fact_name_if_applicable>",\n'
    '  "question": "<question_if_ask_user>",\n'
    '  "query": "<search_query_if_search_tavily>"\n'
    "}"
)


def _heuristic_action_selection(
    item_id: str,
    item_type: str,
    description: str,
    status: str,
) -> InvestigationAction:
    """Deterministic action selector when running offline or in mock mode."""
    desc_lower = description.lower()

    if item_type == "ambiguity":
        return InvestigationAction(
            action=ActionType.SEARCH_TAVILY,
            reason="Policy contains undefined clause or regulatory reference requiring statutory guidance.",
            query=f"IRDAI regulations {description[:60]}",
        )

    if "missing" in desc_lower or "unable_to_verify" in status.lower() or "not provided" in desc_lower or "required" in desc_lower:
        missing_fact = "submitted_documents"
        for fact_key in FACT_VOCABULARY:
            if fact_key in desc_lower or fact_key.replace("_", " ") in desc_lower:
                missing_fact = fact_key
                break
        return InvestigationAction(
            action=ActionType.ASK_USER,
            reason=f"Required fact '{missing_fact}' is missing from submission.",
            missing_fact=missing_fact,
            question=f"Please provide the missing information for {missing_fact}: {description}",
        )

    return InvestigationAction(
        action=ActionType.ESCALATE,
        reason="Discrepancy or ambiguity requires licensed human claims adjuster review.",
    )


def _call_model_for_action(
    model_client: Any,
    item_id: str,
    item_type: str,
    description: str,
    status: str,
) -> InvestigationAction:
    """Call the fast model to select an investigation action, enforcing strict validation."""
    model_id = settings.get_nebius_model_fast()
    user_prompt = (
        f"Item ID: {item_id}\n"
        f"Type: {item_type}\n"
        f"Status: {status}\n"
        f"Description: {description}\n"
        f"Available Fact Vocabulary: {', '.join(sorted(FACT_VOCABULARY.keys()))}\n"
    )

    try:
        from src.ai.nebius_client import chat_json
        raw_json = chat_json(
            client=model_client,
            model=model_id,
            system=SYSTEM_PROMPT,
            user=user_prompt,
            temperature=0.0,
            max_tokens=512,
        )
    except Exception as exc:
        return InvestigationAction(
            action=ActionType.ESCALATE,
            reason=f"Model call failed or returned unparseable content ({type(exc).__name__}): escalate to human review.",
        )

    try:
        action_obj = InvestigationAction.model_validate(raw_json)
        if action_obj.action == ActionType.ASK_USER:
            if not action_obj.missing_fact or action_obj.missing_fact not in FACT_VOCABULARY:
                return InvestigationAction(
                    action=ActionType.ESCALATE,
                    reason=f"Model suggested ask_user with invalid fact vocabulary key '{action_obj.missing_fact}'. Escalated.",
                )
        return action_obj
    except ValidationError:
        return InvestigationAction(
            action=ActionType.ESCALATE,
            reason="Model returned an invalid action structure not conforming to schema. Escalated.",
        )


def investigate(
    findings: List[Finding],
    rulebook: Rulebook,
    facts: List[ClaimFact],
    ask_user: Optional[Callable[[str, str], Optional[Any]]] = None,
    max_iterations: int = 2,
    model_client: Optional[Any] = None,
    tavily_transport: Optional[Callable[[dict, float], dict]] = None,
) -> InvestigationResult:
    """Investigate unresolved findings and policy ambiguities with a hard 2-iteration cap.

    Args:
        findings: Findings output by deterministic rule engine.
        rulebook: Policy rulebook containing rules and ambiguities.
        facts: Current list of extracted claim facts.
        ask_user: Optional callback taking (question, missing_fact) and returning user input.
        max_iterations: Maximum investigation cycles (capped at 2).
        model_client: Optional OpenAI client pointing to Nebius Token Factory.
        tavily_transport: Optional mock transport for Tavily API testing.

    Returns:
        InvestigationResult containing investigated items, updated facts and findings.
    """
    hard_limit = min(max_iterations, 2)
    current_facts = list(facts)
    current_findings = list(findings)

    investigated_items: Dict[str, InvestigationItem] = {}
    audit_log: List[Dict[str, Any]] = []

    iterations_run = 0

    while iterations_run < hard_limit:
        iterations_run += 1

        # 1. Identify unresolved items in this iteration
        unresolved: List[tuple[str, str, str, str]] = []

        # Check ambiguities (only in first iteration)
        if iterations_run == 1:
            for amb in getattr(rulebook, "ambiguities", []):
                amb_id = amb.ambiguity_id
                if amb_id not in investigated_items:
                    desc = f"Section {amb.section}: {amb.description} - {amb.issue}"
                    unresolved.append((amb_id, "ambiguity", desc, "ambiguity"))

        # Check findings
        for fnd in current_findings:
            f_status = str(getattr(fnd.status, "value", fnd.status)).lower()
            if f_status in ("needs_review", "unable_to_verify", "violated"):
                # If already resolved in previous iteration, skip
                prev = investigated_items.get(fnd.rule_id)
                if prev and prev.resolved:
                    continue
                # If violated due to missing document/fact, it can be investigated
                if f_status in ("needs_review", "unable_to_verify") or "missing" in fnd.explanation.lower() or "required" in fnd.explanation.lower():
                    unresolved.append((fnd.rule_id, "finding", fnd.explanation, f_status))

        if not unresolved:
            break

        facts_added_this_round = False

        # 2. Process each unresolved item
        for item_id, item_type, description, status in unresolved:
            # Select action
            if model_client is not None and settings.is_set("NEBIUS_MODEL_FAST"):
                action = _call_model_for_action(model_client, item_id, item_type, description, status)
            else:
                action = _heuristic_action_selection(item_id, item_type, description, status)

            inv_item = InvestigationItem(
                item_id=item_id,
                item_type=item_type,  # type: ignore[arg-type]
                description=description,
                status=status,
                action=action,
                iteration=iterations_run,
                requires_human_review=True,
                resolved=False,
            )

            # Execute action
            if action.action == ActionType.ASK_USER:
                if ask_user is not None and action.missing_fact:
                    user_val = ask_user(action.question or "", action.missing_fact)
                    if user_val is not None:
                        inv_item.user_response = str(user_val)
                        new_fact = ClaimFact(
                            name=action.missing_fact,
                            value=user_val,
                            source=SourceRef(
                                document="user_clarification",
                                page=1,
                                quote=f"User clarification: {action.missing_fact}={user_val}",
                            ),
                        )
                        # Replace previous value of this fact to avoid duplicate conflicting entries
                        current_facts = [f for f in current_facts if f.name != action.missing_fact]
                        current_facts.append(new_fact)
                        facts_added_this_round = True
                        inv_item.resolved = True
                        inv_item.requires_human_review = False

            elif action.action == ActionType.SEARCH_TAVILY:
                search_query = action.query or description
                search_res = tavily_client.search(
                    query=search_query,
                    transport_fn=tavily_transport,
                )
                audit_log.extend(tavily_client.get_audit_log())
                if search_res.success:
                    inv_item.external_guidance = [
                        {"url": r.url, "title": r.title, "snippet": r.snippet}
                        for r in search_res.results
                    ]
                inv_item.resolved = False
                inv_item.requires_human_review = True

            elif action.action == ActionType.ESCALATE:
                inv_item.resolved = False
                inv_item.requires_human_review = True

            investigated_items[item_id] = inv_item

        # 3. If new facts were added, re-evaluate rule engine
        if facts_added_this_round:
            try:
                current_findings = evaluate(rulebook, current_facts)
            except Exception:
                pass

    has_unresolved = False
    for fnd in current_findings:
        f_status = str(getattr(fnd.status, "value", fnd.status)).lower()
        if f_status in ("needs_review", "unable_to_verify"):
            has_unresolved = True
            break
    if getattr(rulebook, "ambiguities", []):
        has_unresolved = True

    return InvestigationResult(
        items=list(investigated_items.values()),
        findings=current_findings,
        facts=current_facts,
        iterations_run=iterations_run,
        max_iterations_reached=(iterations_run >= hard_limit),
        audit_log=audit_log,
        requires_human_review=has_unresolved,
    )
