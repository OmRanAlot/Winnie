"""LangChain / Deep Agents planning and bounded Photon conversation memory.

Nothing in this package can store tasks or send messages: every agent is built with no tools and
a virtual in-memory filesystem (see runner.py). services/planning*.py validate whatever comes
back, and routes/planning.py exposes it read-only. Importing this package imports no provider
library; deepagents and langchain_google_genai load lazily on first real use.

    prompts.py   all system prompts as plain strings (PLANNER_SYSTEM_PROMPT, STAGE_PROMPTS)
    models.py    planning_model(): "google_genai:<id>" -> configured Gemini chat model;
                 describe_model(): log-safe model name
    runner.py    run_structured_agent(): the one place a Deep Agents agent is built and invoked,
                 with timing/failure logging and the safety defaults
    planner.py   single-shot planner: mock_plan (offline) and deep_plan (one agent call)
    stages.py    StageRunner protocol + DeepStageRunner: one agent call per pipeline stage
    conversation_memory.py  pure LangGraph history append + Supabase checkpointer;
                 persists backend-validated dialogue, never task actions or message sends

Call flow:
    POST /api/planning/drafts          -> services/planning.create_draft
                                          -> planner.mock_plan | planner.deep_plan -> runner
    POST /api/planning/pipeline-drafts -> services/planning_pipeline.run_pipeline
                                          -> StageRunner.run (DeepStageRunner -> runner) x5

Mode is WINNIE_PLANNING_MODE=mock|deepagents; deepagents also needs WINNIE_PLANNING_MODEL, for
example google_genai:<model id> plus GEMINI_API_KEY. See docs/EVENT_PLANNING.md.
"""
