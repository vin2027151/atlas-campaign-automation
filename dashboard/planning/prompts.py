"""System prompts and message builders for the planning LLM calls (analyze, draft, revise, repair)."""

import json
from typing import Any, Dict, List, Optional

import yaml

ANALYZE_SYSTEM = """You review a paid-media account (Google Ads + Meta) for a B2B SaaS selling trial signups, against its 30-day plan. Your output is read by the founder and the Atlas team on a simple display.

You get: the plan (YAML), a compact state document of the live account, deterministic facts computed by code comparing the two, the 30-day checklist progress, and test_reads: code-computed statistics for every test (observed value, 95% interval, minimums met, verdict).

Return only a JSON object:
{"items": [{"title": str, "plan": str, "running": str, "testing": str, "evidence": str, "recommendation": str, "research": str, "priority": "high"|"medium"|"low", "platform": "google"|"meta"|"both", "campaign_id": str|null, "test_id": str|null}], "notes": [str]}

Each item is one line of reasoning, always in this order:
1. plan: what the plan called for. Cite the plan's own numbers or rule.
2. running: what is live now toward it (a named test, campaign or setting).
3. testing: what that test is trying to learn: whether X change produces Y result or Z result. If no test covers this, say "No test running on this."
4. evidence: the data so far and whether it is enough to conclude. Quote the test_reads verdict, interval and minimums for tests; never claim significance the test_reads do not show. For items without a test, use state metrics.
5. recommendation: therefore, the one change to make (or "keep running until <condition>").
- research: optional one sentence on where to dig further or a caveat; "" if none.
Example of the voice: plan "Optimize nonbrand budget with a target CPA per Search Atlas offering." running "Test t07 runs agency vs individual keyword groups." testing "Whether splitting by offering lowers CPT below $260 or just moves spend." evidence "Interval $210-$248 sits under $260 with minimums met (spend $4,100 of $4,000, trials 19 of 15): significant win." recommendation "Make the split permanent and move the shared budget to per-offering budgets."

- 4-8 items, most important first. title is 3-8 words. Every field is one sentence, under 30 words. No narration, preamble or hedging.
- notes: 0-4 short bullets for anything that does not fit an item.
- Use only numbers that appear in the inputs. Never invent or extrapolate figures. Trials are PostHog-attributed truth; platform conversions are claims.
- campaign_id is the dashboard id (e.g. "g_search_brand_us") or null; test_id is a test id from test_reads or null.
- You only advise. You cannot change the account.

Company context: the company and brand is Search Atlas. AgentStack is one Search Atlas offering (its own ads, landing page and 14-day-trial offer), not the brand. The plan covers the AgentStack offering. Search Atlas SEO ads in the account belong to other Search Atlas offerings; call them off-plan for these campaigns, never a branding error."""

CHANGESET_SYSTEM = """You turn a media buyer's brief into a changeset for a Google Ads + Meta account. Company context: the company and brand is Search Atlas. AgentStack is one Search Atlas offering (its own ads, landing page and 14-day-trial offer), not the brand. The plan covers the AgentStack offering. Search Atlas SEO ads in the account belong to other Search Atlas offerings; call them off-plan for these campaigns, never a branding error.

The changeset is YAML whose operations are shaped exactly like Google Ads API and Meta Marketing API requests, following the schema document you are given. Code validates it, computes a diff against the current state, and shows the diff to a human.

You have no authority to publish and no access to the accounts. A human reads the diff and publishes by hand, or not at all. Write the proposal; do not claim anything was changed.

Rules:
- Reference only resource names and Meta ids present in the state document. Set changeset.based_on_snapshot to the snapshot id given.
- Use only operations the schema allows. Google budgets are amount_micros (dollars x 1,000,000); Meta budgets and bids are cents. New Meta ads start PAUSED.
- Use only media ids from the approved media list. Prefer the media ids the brief tags.
- Respect the guardrails in the schema (budget change limits, minimum daily budget). If the brief asks for something that would break them, do the closest allowed change and say so in assumptions.
- Do exactly what the brief asks; no extra changes. If the brief is ambiguous, make the safest reasonable choice, list it under assumptions, and ask under questions.
- rationale, summary, assumptions and questions are short bullets, each under 25 words. Use only numbers present in the inputs.

Return only a JSON object:
{"yaml": "<the full changeset YAML as one string>", "summary": [str], "assumptions": [str], "questions": [str]}
summary: what the changeset does, one bullet per operation group. assumptions and questions may be empty lists."""


def _dump_yaml(obj):
    # type: (Any) -> str
    if isinstance(obj, str):
        return obj
    return yaml.safe_dump(obj, sort_keys=False, allow_unicode=True, width=120)


def _dump_json(obj):
    # type: (Any) -> str
    return json.dumps(obj, indent=1, ensure_ascii=False, default=str)


def _block(tag, body):
    # type: (str, str) -> str
    return "<%s>\n%s\n</%s>" % (tag, body.strip(), tag)


def analyze_messages(plan, compact_snapshot, facts, checklist, test_reads=None):
    # type: (Any, Dict[str, Any], List[Dict[str, Any]], Dict[str, Any], Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]
    text = "\n\n".join([
        _block("plan", _dump_yaml(plan)),
        _block("state_document", _dump_json(compact_snapshot)),
        _block("facts", _dump_json(facts)),
        _block("checklist_progress", _dump_json(checklist)),
        _block("test_reads", _dump_json(test_reads or [])),
        "Analyze the account against the plan. Reply with the JSON object only.",
    ])
    return [{"role": "user", "content": text}]


def _changeset_context(compact_snapshot, schema_doc, media_assets, plan, tagged_media):
    # type: (Dict[str, Any], str, List[Dict[str, Any]], Any, List[str]) -> List[str]
    return [
        _block("changeset_schema", schema_doc),
        _block("state_document", "snapshot_id: %s\n%s" % (compact_snapshot.get("id"), _dump_json(compact_snapshot))),
        _block("approved_media", _dump_json(media_assets) if media_assets else "[] (no approved media)"),
        _block("tagged_media_ids", ", ".join(tagged_media) if tagged_media else "none"),
        _block("plan", _dump_yaml(plan)),
    ]


def draft_messages(directive, compact_snapshot, schema_doc, media_assets, plan, tagged_media):
    # type: (str, Dict[str, Any], str, List[Dict[str, Any]], Any, List[str]) -> List[Dict[str, Any]]
    parts = _changeset_context(compact_snapshot, schema_doc, media_assets, plan, tagged_media)
    parts += [_block("brief", directive), "Write the changeset for this brief. Reply with the JSON object only."]
    return [{"role": "user", "content": "\n\n".join(parts)}]


def revise_messages(directive, revision_note, prior_yaml, compact_snapshot, schema_doc, media_assets, plan,
                    tagged_media, prior_validation=None):
    # type: (str, str, str, Dict[str, Any], str, List[Dict[str, Any]], Any, List[str], Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]
    parts = _changeset_context(compact_snapshot, schema_doc, media_assets, plan, tagged_media)
    parts += [_block("original_brief", directive), _block("prior_changeset_yaml", prior_yaml)]
    if prior_validation:
        parts.append(_block("prior_validation", _dump_json(prior_validation)))
    parts += [_block("revision_notes", revision_note),
              "Revise the prior changeset per the revision notes, against the current state document "
              "(update based_on_snapshot). Return the complete new YAML, not a patch. Reply with the JSON object only."]
    return [{"role": "user", "content": "\n\n".join(parts)}]


def repair_messages(messages, prior_reply_text, errors):
    # type: (List[Dict[str, Any]], str, List[str]) -> List[Dict[str, Any]]
    note = "Validation rejected that changeset:\n" + "\n".join("- " + e for e in errors) + \
        "\nFix these errors and return the complete corrected JSON object only."
    return list(messages) + [{"role": "assistant", "content": prior_reply_text or "(empty)"},
                             {"role": "user", "content": note}]
