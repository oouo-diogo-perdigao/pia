from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ActionStep(BaseModel):
    kind: Literal[
        "delete_all",
        "press_enter",
        "open_url",
        "open_target",
        "weather",
        "learned_action",
        "remember_fact",
    ]

    target: Optional[str] = None
    action_id: Optional[str] = None
    location: Optional[str] = None
    when: Optional[str] = None
    fact_key: Optional[str] = None
    fact_value: Optional[str] = None


class LearningProposal(BaseModel):
    kind: Literal["url", "path", "capability"]
    description: str
    canonical_trigger: str
    prompt: str
    success_message: str = ""
    proposed_tool_name: Optional[str] = None


class AgentDecision(BaseModel):
    mode: Literal[
        "execute",
        "answer",
        "learn_memory",
        "learn_capability",
    ]
    spoken_response: str = ""
    actions: list[ActionStep] = Field(default_factory=list)
    learning: Optional[LearningProposal] = None


class AgentResult(BaseModel):
    ok: bool = True
    transcription: str = ""
    mode: str = ""
    spoken_response: str = ""
    details: list[dict] = Field(default_factory=list)
    error: Optional[str] = None
