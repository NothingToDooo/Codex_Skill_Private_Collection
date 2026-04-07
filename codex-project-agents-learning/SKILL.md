---
name: project-agents-learning
description: Create or update a project's `AGENTS.md` from transcript aggregates. Use when the user wants to create `AGENTS.md`, refresh learned memory in `AGENTS.md`, or update durable user preferences and workspace facts for a project by reading transcript deltas and updating the learned sections directly.
---

# Project Agents Learning

Own the full project memory update flow for `AGENTS.md`.

## Trigger

Use when the user asks to create or refresh project memory in `AGENTS.md`.

## Workflow

1. Read existing `AGENTS.md` first. If it does not exist, create it. If it already exists, ensure it contains the following learned headers (append them if missing):
   - `## Learned User Preferences`
   - `## Learned Workspace Facts`
   - only maintain these learned sections; leave unrelated sections unchanged
2. From the current conversation `cwd`, run:
   - `python <this-skill-dir>/scripts/project_agents_learning.py`
3. Read `[project-root]/.agents/state/memory-candidates.json`.
4. Interpret `memory-candidates.json` before learning:
   - `sessions` are the review units
   - each entry in `sessions` is one complete conversation within the same project
   - use one session as the primary analysis unit, while allowing for cross-session continuation or overlap when the evidence is clear
   - in each session, `transcript` is the main learning content
5. Establish session-level context internally before extracting memory (do not output these intermediate summaries; use them only to guide evidence selection):
   - summarize what problems the session handled; a session may contain one problem or multiple problems
   - if multiple problems appear, distinguish the main problem, secondary problems, clarifications, and corrections
   - identify the files, objects, rules, tools, or outcomes involved in each problem
   - check whether any problem continues, overlaps with, repeats, or corrects material from other sessions only when that relationship is supported by evidence available in the current `memory-candidates.json` or already recorded in `AGENTS.md`
   - use this step to build project context and locate the important evidence, not as the final memory source
6. Analyze the local interaction cycles inside each session:
   - identify local interaction cycles as user-request and assistant-response sequences
   - a problem may be resolved in one cycle or across multiple cycles through clarification, revision, and completion
   - for each cycle, determine which problem it belongs to and whether it introduces, advances, clarifies, or corrects that problem
   - `role: "user"` is requirement evidence and the primary source for durable preferences, repeated requirements, and stable corrections
   - `role: "assistant", phase: "commentary"` is process evidence; each entry in `steps` is one process step
   - extract from `commentary.steps` only when they reveal repeated mistakes, requirement misunderstandings, correction patterns, or reusable process rules
   - `role: "assistant", phase: "final_answer"` is outcome evidence and should not be learned by default; use it only when it adds new stable information or clarifies which final outcome was actually adopted
   - if user requirements, process steps, and final answers diverge, infer only evidence-supported reusable conclusions
   - report mismatch reasoning in the user-facing response only when it leads to a durable conclusion worth surfacing to the user
   - do not explain ordinary iteration, routine correction, or transient trial-and-error in the user-facing response
   - do not write speculative causes or unconfirmed reasoning into `AGENTS.md`
7. Pull out only durable, reusable items:
   - recurring user preferences or corrections
   - stable workspace facts
   - repeated execution failures, misread patterns, or reusable rules inferred from requirement, process, and outcome mismatches
   - do not promote a session-local conclusion to project memory unless it shows project-level stability or support across explicit user statements, repeated evidence available in the current candidates, shared objects, later continuation/correction visible in the current evidence, or durable memory already recorded in `AGENTS.md`
8. Update `AGENTS.md` carefully:
   - update matching bullets in place
   - add only net-new bullets
   - remove duplicate bullets
   - merge bullets only when they express the same durable rule with different wording
   - keep each learned section to at most 12 bullets
   - if a section still exceeds 12 bullets, compress only by combining bullets where one clearly subsumes the other without losing actionable specificity
   - do not replace concrete, actionable rules with vague summaries during compression
   - if a section still exceeds 12 bullets after compression, retain the 12 most durable, specific, and highest-signal items
   - if any candidate items are excluded due to the capacity limit, explicitly report them in the user-facing response only; do not write discarded items into `AGENTS.md`
9. If no meaningful updates exist, if `memory-candidates.json` contains no
   candidate sessions, or if the merge produces no `AGENTS.md` changes, leave `AGENTS.md` unchanged and respond exactly:
   `This learning run produced no high-signal conclusions.`
10. If `AGENTS.md` is updated, respond with a brief user-facing summary of what changed in this run:
   - whether the run added new memory
   - whether it refined, merged, or compressed existing memory
   - whether any items were excluded due to the capacity limit
   - do not repeat the full contents of `AGENTS.md` unless the user explicitly asks for them

## Guardrails

- Use plain bullet points only.
- Keep only these learned sections:
  - `## Learned User Preferences`
  - `## Learned Workspace Facts`
- Do not write transcript summaries, evidence dumps, confidence scores, or metadata blocks.
- Do not learn routine successful completions as memory by default.
- Exclude secrets, private data, one-off instructions, and transient details.
- Do not learn from other projects.
