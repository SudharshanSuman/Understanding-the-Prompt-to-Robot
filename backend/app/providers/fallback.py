"""Deterministic rule-based parser. Works offline and always gives the same answer."""

from __future__ import annotations

import re

from app.providers.base import LanguageModelProvider, ProviderStatus
from app.schemas import ClarificationRequest, ParsedCommand, TaskAction, TaskConstraints, TaskPlan
from app.validation.validator import clarification_for
from app.validation.world import ObjectMention, WorldModel, analyze_command, slugify

_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _mention_id(mention: ObjectMention) -> str:
    return mention.resolved or mention.guessed_id or slugify(mention.phrase)


class DeterministicFallbackProvider(LanguageModelProvider):
    name = "fallback"
    kind = "fallback"

    def status(self) -> ProviderStatus:
        return ProviderStatus(name=self.name, kind=self.kind, configured=True, available=True,
                              detail="rule-based parser, no model")

    def parse(self, command: str, world: WorldModel) -> ParsedCommand:
        analysis = analyze_command(command, world)
        if not analysis.has_action_verb:
            return ClarificationRequest(
                question="What should the robot do? Supported: pick an object and place it at a destination.",
                reason="no supported action verb found in the command",
                options=["pick_and_place"],
            )
        clarification = clarification_for(analysis, world)
        if clarification is not None:
            return clarification
        if not analysis.targets:
            return ClarificationRequest(
                question="Which object should be moved?",
                reason="the command does not name an object" + (" ('it' has nothing to refer to)"
                                                                 if analysis.uses_pronoun_only else ""),
                options=sorted(o.id for o in world.objects if o.graspable),
            )
        target = _mention_id(analysis.targets[0])
        if analysis.destination_phrase is None:
            return ClarificationRequest(
                question=f"Where should the {target.replace('_', ' ')} go?",
                reason="the command does not name a destination",
                options=sorted(world.destination_ids()),
            )
        destination = analysis.destination_id or slugify(analysis.destination_phrase)
        if target == destination:
            return ClarificationRequest(
                question=f"Where should the {target.replace('_', ' ')} go? It cannot be placed on itself.",
                reason="the object and the destination are the same",
                options=sorted(world.destination_ids() - {target}),
            )
        avoid = list(dict.fromkeys(_mention_id(m) for m in analysis.avoid if _mention_id(m) != target))
        if not all(_ID_RE.match(i) for i in (target, destination, *avoid)):
            return ClarificationRequest(
                question="Please name the object and destination using names from the scene.",
                reason="a reference could not be turned into a scene identifier",
                options=sorted(world.object_ids() | world.destination_ids()),
            )
        return TaskPlan(
            action=TaskAction.PICK_AND_PLACE,
            object=target,
            destination=destination,
            constraints=TaskConstraints(avoid_objects=avoid, keep_upright=analysis.keep_upright),
            confidence=1.0,
        )
