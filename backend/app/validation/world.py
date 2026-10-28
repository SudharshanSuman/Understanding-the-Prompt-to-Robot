"""World model (known objects and destinations) and deterministic command analysis.

The scene is loaded from config (munder_difflin/config/scene.json, or MD_SCENE_CONFIG) so the
Gazebo scene and the perception interface can supply poses and reachability later.
The analysis here is shared by the fallback parser and the safety validator so both
agree on what a command mentions.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_SCENE_PATH = Path(__file__).resolve().parents[3] / "config" / "scene.json"

COLORS = frozenset(
    {"red", "blue", "green", "yellow", "black", "white", "orange", "purple", "pink", "grey", "gray", "brown"}
)
OBJECT_TYPES = frozenset({"box", "cube", "cylinder", "bottle", "can", "ball", "block", "cup", "mug"})
# Verbs that take hold of an object, and verbs that put it somewhere.
ACQUIRE_VERBS = frozenset({"pick", "grab", "take", "lift", "grasp"})
PLACE_VERBS = frozenset({"move", "put", "place", "bring", "transfer", "carry", "set", "drop", "stack", "push"})
ACTION_VERBS = ACQUIRE_VERBS | PLACE_VERBS
# Words that name a direction or a vague place, never a destination on their own.
DIRECTIONAL = frozenset(
    {"left", "right", "front", "back", "behind", "forward", "backward", "up", "down",
     "there", "here", "somewhere", "elsewhere", "side", "over", "away", "corner"}
)
PRONOUNS = frozenset({"it", "that", "this", "them", "those", "these", "one", "something", "everything"})
# Nouns too vague to be an unknown object: they call for a clarification instead.
VAGUE_NOUNS = frozenset({"thing", "things", "object", "objects", "item", "items", "stuff", "piece", "pieces"})

# Words that may sit before an object noun without changing which object it is.
_LEAD_WORDS = frozenset({"the", "a", "an", "that", "this", "up", "and", "then", "to", "on", "in", "into", "onto",
                         "of", "it", "with", "from", "small", "big", "large", "little"}) | ACTION_VERBS
_VERB_ALT = "|".join(sorted(ACTION_VERBS))
_AVOID_RE = re.compile(
    r"\b(?:avoid(?:ing)?|stay(?:ing)? away from|keep(?:ing)? away from|"
    r"(?:do not|don't|without) (?:touch(?:ing)?|hit(?:ting)?|bump(?:ing)? into))\s+(?P<body>[^,.;]*)"
)
_UPRIGHT_RE = re.compile(r"\bupright\b|\bdon't (?:tip|tilt|flip)\b|\bdo not (?:tip|tilt|flip)\b")
_NEGATION_RE = re.compile(rf"\b(?:do not|don't|dont|never|no need to|stop)\b(?:\s+[a-z]+){{0,2}}?\s+(?:{_VERB_ALT})\b")
_DEST_RE = re.compile(
    r"\b(?:on|onto|in|into|to|at|inside|toward|towards)\s+"
    r"(?P<phrase>.+?)(?=\s+(?:and|then|but|while|without|keeping|so|after)\b|[,.;]|$)"
)
# Placement relative to something ("next to the bin") is not a destination the robot can resolve.
_RELATIVE_RE = re.compile(
    r"\b(?:next to|beside|near|nearby|close to|by the|in front of|behind|(?:to the )?(?:left|right) of|"
    r"on top of the (?:" + "|".join(sorted(OBJECT_TYPES)) + r")|between)\b")
_SEQUENCE_RE = re.compile(r"\b(?:then|after that|afterwards|and also|followed by)\b")
_TARGET_RE = re.compile(
    rf"\b(?:{_VERB_ALT})\b(?:\s+up)?\s+(?:the\s+|a\s+|an\s+)?(?P<phrase>[a-z][a-z0-9 ]*?)"
    r"(?=\s+(?:and|then|up)\b|[,.;]|$)"
)
_ARTICLES = re.compile(r"\b(?:the|a|an|its|their)\b")


def normalize(text: str) -> str:
    text = text.lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9_',.; ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def slugify(phrase: str) -> str:
    phrase = _ARTICLES.sub(" ", phrase)
    return re.sub(r"[^a-z0-9]+", "_", phrase.strip().lower()).strip("_")


class Pose(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    x: float
    y: float
    z: float
    frame_id: str = "world"


class WorldObject(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    type: str
    color: str | None = None
    aliases: tuple[str, ...] = ()
    graspable: bool = True
    pose: Pose | None = None
    reachable: bool | None = None  # None = not known yet; MoveIt IK must confirm


class WorldDestination(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    aliases: tuple[str, ...] = ()
    pose: Pose | None = None
    reachable: bool | None = None


class WorldModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    objects: tuple[WorldObject, ...]
    destinations: tuple[WorldDestination, ...]

    @classmethod
    def from_json_file(cls, path: str | Path) -> "WorldModel":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate({k: v for k, v in data.items() if not k.startswith("_")})

    def object_ids(self) -> set[str]:
        return {o.id for o in self.objects}

    def destination_ids(self) -> set[str]:
        return {d.id for d in self.destinations}

    def get_object(self, object_id: str) -> WorldObject | None:
        return next((o for o in self.objects if o.id == object_id), None)

    def get_destination(self, destination_id: str) -> WorldDestination | None:
        return next((d for d in self.destinations if d.id == destination_id), None)

    def destination_phrases(self) -> dict[str, str]:
        """Map every spoken form of a destination to its id, longest first."""
        phrases: dict[str, str] = {}
        for dest in self.destinations:
            for form in (dest.id, dest.id.replace("_", " "), *dest.aliases):
                phrases[normalize(form)] = dest.id
        return dict(sorted(phrases.items(), key=lambda kv: -len(kv[0])))


def default_world() -> WorldModel:
    """The configured scene: MD_SCENE_CONFIG if set, else munder_difflin/config/scene.json."""
    return WorldModel.from_json_file(os.environ.get("MD_SCENE_CONFIG") or DEFAULT_SCENE_PATH)


@dataclass(frozen=True)
class ObjectMention:
    """One reference to an object in the command, with the world objects it could mean."""

    phrase: str
    guessed_id: str | None  # e.g. "purple_box" for an unknown but well-formed reference
    candidates: tuple[str, ...]

    @property
    def resolved(self) -> str | None:
        return self.candidates[0] if len(self.candidates) == 1 else None

    @property
    def ambiguous(self) -> bool:
        return len(self.candidates) > 1

    @property
    def unknown(self) -> bool:
        return not self.candidates


@dataclass
class CommandAnalysis:
    text: str
    has_action_verb: bool = False
    negated: bool = False
    targets: list[ObjectMention] = field(default_factory=list)
    avoid: list[ObjectMention] = field(default_factory=list)
    destination_phrase: str | None = None
    destination_id: str | None = None
    destination_is_directional: bool = False
    destination_count: int = 0
    keep_upright: bool = False
    uses_pronoun_only: bool = False
    multi_step: bool = False

    @property
    def unknown_destination(self) -> str | None:
        if self.destination_phrase and not self.destination_id and not self.destination_is_directional:
            return slugify(self.destination_phrase) or self.destination_phrase
        return None


def _find_mentions(text: str, world: WorldModel) -> list[ObjectMention]:
    words = re.findall(r"[a-z0-9_]+", text)
    mentions: list[ObjectMention] = []
    alias_hits = set()
    for obj in world.objects:
        for alias in (obj.id.replace("_", " "), *obj.aliases):
            if re.search(rf"\b{re.escape(normalize(alias))}\b", text):
                alias_hits.add(obj.id)
    for i, word in enumerate(words):
        if word not in OBJECT_TYPES:
            continue
        color = words[i - 1] if i > 0 and words[i - 1] in COLORS else None
        if color == "gray":
            color = "grey"
        typed = [o for o in world.objects if o.type == word or word in {a.split()[-1] for a in o.aliases}]
        prev = words[i - 1] if i > 0 else None
        if color:
            candidates = tuple(o.id for o in typed if o.color == color)
            mentions.append(ObjectMention(f"{color} {word}", f"{color}_{word}", candidates))
        elif prev and prev not in _LEAD_WORDS:
            # "storage box" names a known object; "ghost box" names nothing we know.
            phrase = f"{prev} {word}"
            named = tuple(o.id for o in world.objects if phrase in {normalize(a) for a in o.aliases})
            mentions.append(ObjectMention(phrase, f"{prev}_{word}", named))
        else:
            mentions.append(ObjectMention(word, None, tuple(o.id for o in typed)))
    for obj_id in sorted(alias_hits):
        if not any(obj_id in m.candidates for m in mentions):
            mentions.append(ObjectMention(obj_id.replace("_", " "), obj_id, (obj_id,)))
    # Collapse duplicates of the same reference ("the red cube ... the red cube").
    unique: dict[tuple[str, tuple[str, ...]], ObjectMention] = {}
    for m in mentions:
        unique.setdefault((m.phrase, m.candidates), m)
    return list(unique.values())


def _unknown_noun_target(text: str) -> ObjectMention | None:
    """The object phrase after the verb when it names nothing we know ("the purple elephant")."""
    match = _TARGET_RE.search(text)
    if not match:
        return None
    phrase = match.group("phrase").strip()
    if not phrase or set(phrase.split()) & (PRONOUNS | VAGUE_NOUNS) or set(phrase.split()) <= DIRECTIONAL:
        return None
    slug = slugify(phrase)
    return ObjectMention(phrase, slug or None, ()) if slug and re.match(r"^[a-z]", slug) else None


def analyze_command(command: str, world: WorldModel) -> CommandAnalysis:
    text = normalize(command)
    analysis = CommandAnalysis(text=text)
    words = re.findall(r"[a-z]+", text)
    analysis.has_action_verb = any(w in ACTION_VERBS for w in words)
    analysis.keep_upright = bool(_UPRIGHT_RE.search(text))
    analysis.negated = bool(_NEGATION_RE.search(text))

    remainder = text
    for match in _AVOID_RE.finditer(text):
        analysis.avoid.extend(_find_mentions(match.group("body"), world))
        remainder = remainder.replace(match.group(0), " ")

    relative = _RELATIVE_RE.search(remainder)
    if relative:
        analysis.destination_phrase = remainder[relative.start():].split(",")[0].strip()
        analysis.destination_is_directional = True
        analysis.destination_count = 1
        remainder = remainder[: relative.start()]
    phrases = world.destination_phrases()
    for match in (() if relative else list(_DEST_RE.finditer(remainder))):
        phrase = match.group("phrase").strip()
        phrase_words = set(re.findall(r"[a-z]+", phrase))
        known = next((dest for form, dest in phrases.items() if re.search(rf"\b{re.escape(form)}\b", phrase)), None)
        if known:
            is_destination, directional = True, False
        elif phrase_words & DIRECTIONAL:
            is_destination, directional = True, True
        else:
            is_destination, directional = not (phrase_words & OBJECT_TYPES), False
        if not is_destination:
            continue
        analysis.destination_count += 1
        remainder = remainder.replace(match.group(0), " ", 1)
        # Keep the first concrete destination; a known one beats a vague one.
        if analysis.destination_phrase is None or (known and analysis.destination_id is None):
            analysis.destination_phrase, analysis.destination_id = phrase, known
            analysis.destination_is_directional = directional

    analysis.targets = _find_mentions(remainder, world)
    if not analysis.targets:
        unknown = _unknown_noun_target(remainder)
        if unknown is not None:
            analysis.targets = [unknown]
        else:
            analysis.uses_pronoun_only = bool(set(re.findall(r"[a-z]+", remainder)) & PRONOUNS)

    place_verbs = sum(w in PLACE_VERBS for w in words)
    acquire_verbs = sum(w in ACQUIRE_VERBS for w in words)
    analysis.multi_step = (
        analysis.destination_count > 1
        or place_verbs > 1
        or (bool(_SEQUENCE_RE.search(text)) and acquire_verbs > 1)
    )
    return analysis
