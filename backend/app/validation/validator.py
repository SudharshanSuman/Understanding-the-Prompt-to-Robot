"""Deterministic safety and feasibility checks. No model call can bypass these."""

from __future__ import annotations

from collections.abc import Callable

from app.schemas import ClarificationRequest, TaskPlan, ValidationIssue, ValidationReport
from app.validation.world import CommandAnalysis, WorldModel, analyze_command

LOW_CONFIDENCE = 0.6

# Returns True (reachable), False (not reachable) or None (unknown: MoveIt IK must confirm).
ReachabilityCheck = Callable[[TaskPlan, WorldModel], "bool | None"]


def scene_reachability(plan: TaskPlan, world: WorldModel) -> bool | None:
    """Default check: use the scene's reachable flags; unknown unless both ends are known."""
    target, dest = world.get_object(plan.object), world.get_destination(plan.destination)
    flags = [x.reachable for x in (target, dest) if x is not None]
    if any(f is False for f in flags):
        return False
    return True if len(flags) == 2 and all(flags) else None


class SafetyValidator:
    def __init__(
        self,
        world: WorldModel,
        low_confidence: float = LOW_CONFIDENCE,
        reachability: ReachabilityCheck = scene_reachability,
    ) -> None:
        self.world = world
        self.low_confidence = low_confidence
        self.reachability = reachability

    def check_command(self, command: str) -> ClarificationRequest | None:
        """Return a clarification request when the raw command is ambiguous, else None.

        Runs on the user's words, before and independently of any provider, so a model
        cannot silently guess what an ambiguous command meant.
        """
        return clarification_for(analyze_command(command, self.world), self.world)

    def check_references(self, command: str) -> ValidationReport | None:
        """Report objects or destinations the command names that are not in the scene, else None."""
        analysis = analyze_command(command, self.world)
        if not analysis.has_action_verb or analysis.negated:
            return None
        errors = [
            ValidationIssue(code="UNKNOWN_OBJECT", field="object",
                            message=f"'{m.guessed_id or m.phrase}' is not an object in the scene")
            for m in analysis.targets if m.unknown
        ]
        errors += [
            ValidationIssue(code="UNKNOWN_AVOID_OBJECT", field="constraints.avoid_objects",
                            message=f"cannot avoid '{m.guessed_id or m.phrase}': it is not an object in the scene")
            for m in analysis.avoid if m.unknown
        ]
        if analysis.unknown_destination:
            errors.append(ValidationIssue(
                code="UNKNOWN_DESTINATION", field="destination",
                message=f"'{analysis.unknown_destination}' is not a known destination"))
        return ValidationReport(ok=False, errors=errors) if errors else None

    def validate_plan(self, plan: TaskPlan, command: str | None = None) -> ValidationReport:
        """Scene checks and feasibility together (schema_validation + feasibility stages)."""
        scene = self.check_scene(plan, command)
        if not scene.ok:
            return scene
        feasible = self.check_feasibility(plan)
        return ValidationReport(ok=feasible.ok, errors=feasible.errors, warnings=[*scene.warnings, *feasible.warnings])

    def check_scene(self, plan: TaskPlan, command: str | None = None) -> ValidationReport:
        """Does the plan name real, graspable things and match what the user asked?"""
        errors: list[ValidationIssue] = []
        known_objects = self.world.object_ids()

        target = self.world.get_object(plan.object)
        if target is None:
            errors.append(ValidationIssue(
                code="UNKNOWN_OBJECT", field="object",
                message=f"'{plan.object}' is not an object in the scene"))
        elif not target.graspable:
            errors.append(ValidationIssue(
                code="OBJECT_NOT_GRASPABLE", field="object",
                message=f"'{plan.object}' cannot be picked up"))

        if plan.destination not in self.world.destination_ids():
            errors.append(ValidationIssue(
                code="UNKNOWN_DESTINATION", field="destination",
                message=f"'{plan.destination}' is not a known destination"))

        for i, avoid_id in enumerate(plan.constraints.avoid_objects):
            if avoid_id not in known_objects:
                errors.append(ValidationIssue(
                    code="UNKNOWN_AVOID_OBJECT", field=f"constraints.avoid_objects[{i}]",
                    message=f"cannot avoid '{avoid_id}': it is not an object in the scene"))

        if command is not None:
            errors += _plan_matches_request(plan, analyze_command(command, self.world))
        return ValidationReport(ok=not errors, errors=errors)

    def check_feasibility(self, plan: TaskPlan) -> ValidationReport:
        """Reachability (pluggable; MoveIt IK at L1) and parser confidence."""
        errors: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []
        reachable = self.reachability(plan, self.world)
        if reachable is False:
            errors.append(ValidationIssue(
                code="UNREACHABLE", field="object",
                message=f"'{plan.object}' or '{plan.destination}' is outside the arm's reach"))
        elif reachable is None:
            warnings.append(ValidationIssue(
                code="REACHABILITY_UNCONFIRMED", field="object",
                message="reachability unknown: must be confirmed by MoveIt IK before execution"))

        if plan.confidence < self.low_confidence:
            warnings.append(ValidationIssue(
                code="LOW_CONFIDENCE", field="confidence",
                message=f"parser confidence {plan.confidence:.2f} is below {self.low_confidence:.2f}"))

        return ValidationReport(ok=not errors, errors=errors, warnings=warnings)


def _plan_matches_request(plan: TaskPlan, analysis: CommandAnalysis) -> list[ValidationIssue]:
    """Compare a (possibly model-made) plan with what the user's words can be shown to mean."""
    issues: list[ValidationIssue] = []
    allowed = {c for m in analysis.targets for c in m.candidates}
    if allowed and plan.object not in allowed:
        issues.append(ValidationIssue(
            code="PLAN_MISMATCH", field="object",
            message=f"plan moves '{plan.object}' but the command refers to {sorted(allowed)}"))
    if analysis.destination_id and plan.destination != analysis.destination_id:
        issues.append(ValidationIssue(
            code="PLAN_MISMATCH", field="destination",
            message=f"plan goes to '{plan.destination}' but the command says '{analysis.destination_id}'"))
    for m in analysis.avoid:
        if m.resolved and m.resolved not in plan.constraints.avoid_objects:
            issues.append(ValidationIssue(
                code="CONSTRAINT_DROPPED", field="constraints.avoid_objects",
                message=f"the command says to avoid '{m.resolved}' but the plan does not"))
    if analysis.keep_upright and not plan.constraints.keep_upright:
        issues.append(ValidationIssue(
            code="CONSTRAINT_DROPPED", field="constraints.keep_upright",
            message="the command says to keep the object upright but the plan does not"))
    return issues


def clarification_for(analysis: CommandAnalysis, world: WorldModel) -> ClarificationRequest | None:
    if analysis.negated:
        return ClarificationRequest(
            question="The command says not to do something. What should the robot do instead?",
            reason="negated commands are never executed",
        )
    if analysis.multi_step:
        return ClarificationRequest(
            question="Please give one pick-and-place task at a time. Which one should run first?",
            reason="the command contains several steps; only single pick-and-place tasks are supported",
        )
    ambiguous = [m for m in analysis.targets if m.ambiguous]
    if ambiguous:
        mention = ambiguous[0]
        return ClarificationRequest(
            question=f"Which {mention.phrase} do you mean?",
            reason=f"'{mention.phrase}' matches {len(mention.candidates)} objects in the scene",
            options=list(mention.candidates),
        )
    if analysis.destination_is_directional and analysis.destination_id is None:
        return ClarificationRequest(
            question=f"Where exactly is '{analysis.destination_phrase}'? Please name a destination.",
            reason="relative directions and positions are not a destination the robot can resolve",
            options=sorted(world.destination_ids()),
        )
    if len({m.guessed_id or m.phrase for m in analysis.targets}) > 1:
        return ClarificationRequest(
            question="Which object should be moved?",
            reason="the command mentions more than one object to move",
            options=[m.resolved for m in analysis.targets if m.resolved],
        )
    for mention in analysis.avoid:
        if mention.ambiguous:
            return ClarificationRequest(
                question=f"Which {mention.phrase} should be avoided?",
                reason=f"'{mention.phrase}' matches {len(mention.candidates)} objects in the scene",
                options=list(mention.candidates),
            )
    return None
