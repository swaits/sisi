# What the owner has said about sisi

Recorded statements, quoted as recorded, each followed by where the reconciliation answers it
(`target N` is a section of `docs/target.md`; stages and cutover steps are in `docs/plan.md`).
These are requirements on the work.

- "It is NOT about that one system. This is a CORE STRATEGIC LEVEL BEHAVIOR to be smarter about how you do things. I shouldn't need to specify these menial details. This is a sisi core problem."
  Answer: the rulebook becomes strategic direction with mechanisms behind it (target 1, 10).
- "sisi should also optimize for minimize(time to delivery) for each task. Just about anything I ask it to do can take HOURS, and sometimes it can take DAYS. I don't want to give up the autonomy or completeness or correctness! But I want both. I want all that AND I want it delivered quickly. So this needs to be part of the sisi core objective optimization function."
  Answer: time to first useful result and to validated completion are measured per unit and reported with their percentiles; selection and reuse of checks; pauses and waits measured (target 5, 6; stage 2).
- "The pushed README still says 'Version 0.1.0, an early release.' under Status. This is the problem with this kind of text, hardcoded to specific versions or numbers or whatever. Also I'm pretty sure the whole README could be reduced by 25-50%."
  Answer: stage 1 rewrites the README without versions or counts, and a test scans the product for perishable material.
- "For price and benchmarking, I'm totally fine with sisi doing web research on that, and updating it every now and then. Generally sisi is built for SWE tasks, so those kinds of benchmarks are what's most useful, and if they do well there they probably do well in other places too, with a few exceptions like specialized software security models."
  Answer: worker facts with source and date, researched by a cheap worker when stale (target 9; stage 3).
- "the brand and title is always **sisi** is still improving. Lowercase, and emph on sisi if it is available."
  Answer: stage 1 and stage 7 documents.
- "Make sure they do a cleanup and backfill to get that garbage out of my global disk data. Stuff like the keymap for phrp belong in that project's work list and design documentation!!! (on project-specific items stored in sisi's global data; lessons must be universally applicable, project details allowed only as the historical example of where a lesson came from)"
  Answer: scope is earned by evidence and a learning is in force only in its own project until then; the migration in stage 6 re-scopes the existing lessons and hands project items to their projects (target 8; cutover step 2).
- "As part of the orchestrator incorporation into sisi, make sure you delete the old version so my sessions aren't running two orchestrators. Also we will need to let current running sessions know about the changes or else I need to restart them."
  Answer: cutover steps 4 and 6.
- "Subagent performance history goes in the user sisi store, not sisi core. And sisi needs to work in t3 or Claude or Hermes or anything else out there. It should always choose the native subagent delegation mechanism!!!!!"
  Answer: the ledger and worker facts live in the user store; `sisi route` names the host's own mechanism first (target 2, 9).
- "I feel like I'm really still having to lead you around by the nose. With sisi I thought you were going to be getting smarter, seeing around corners, anticipating and building what I need before I realize it????"
  Answer: the requirement model with implied, contextual, anticipated and experiential requirements, required where the risk warrants; requirement surprise measured per unit (target 3, 4, 6).
- "The question you have to ask is whether something applies to ALL projects where sisi may be in play AND if it would be universally useful to ALL USERS who install and use sisi. If so it goes in sisi core! If not it's either a user-preference or project-specific and it goes in my user sisi data store. Working on the sisi project itself is the exception -- we'll normally just have sisi as our shell while we work on a wide variety of different projects."
  Answer: the four layers and the universality test (target 2; stage 1).
- "OBTW part of this is deprecating the whole standalone orch.py thing to make that a core part of sisi. But it should be GENERIC and STRATEGIC in direction, so the agent works out the tactics on the fly. IOW, it shouldn't explicitly say use THIS EXACT MODEL or whatever. It sets out OBJECTIVES about how to discover models, discover pricing, discover benchmarking, measure performance, and dispatch and orchestrate DYNAMICALLY and INTELLIGENTLY. And it can leverage subagents with specific orchestration tasks like assessing, routing decisions, whatever. That could be a Haiku/Ember level model sometimes too! This should play DIRECTLY into the main system's objective function, especially around wall time, cost, efficiency."
  Answer: target 9; stage 3; delegation time, tokens and overlap feed the scorecard (target 6).
- "Ok get to work. Also note that I'm totally fine with GROSS change. Rearchitecting is okay. The ONLY thing that matters is that we implement the spec (plus orchestration layer) PERFECTLY."
  Answer: backward compatibility with the old design is not a goal; what is replaced is deleted.

