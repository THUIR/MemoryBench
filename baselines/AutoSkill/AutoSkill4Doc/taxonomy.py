"""Configurable skill taxonomy loader for document extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib import resources
import json
import os
import re
from typing import Any, Dict, List, Optional, Sequence, Set

from .core.common import dedupe_strings


_STABLE_BASE_TYPES = (
    "macro_protocol",
    "session_skill",
    "micro_skill",
    "safety_rule",
    "knowledge_reference",
)
_DEFAULT_BASE_TYPE = "session_skill"
_DEFAULT_VISIBLE_LEVELS = {
    "root_label": "总技能",
    "family_bucket_label": "Family技能",
    "level_labels": {
        "1": "一级技能",
        "2": "二级技能",
        "3": "微技能",
    },
}
_VISIBLE_ROLES = {"root", "parent", "leaf"}


def _normalize_key(value: Any) -> str:
    """Normalizes taxonomy identifiers for matching."""

    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _coerce_str_list(value: Any) -> List[str]:
    """Normalizes arbitrary list-like values into stripped string lists."""

    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _preferred_family_visible_name(raw: Dict[str, Any]) -> str:
    """Chooses one stable visible family label from a configured candidate."""

    explicit = str(raw.get("visible_name") or raw.get("name_zh") or "").strip()
    if explicit:
        return explicit
    for alias in _coerce_str_list(raw.get("aliases")):
        alias_text = str(alias or "").strip()
        if alias_text and any("\u4e00" <= ch <= "\u9fff" for ch in alias_text):
            return alias_text
    return str(raw.get("name") or "").strip()


def _coerce_base_type(value: Any) -> str:
    """Normalizes one internal base asset type."""

    raw = _normalize_key(value)
    return raw if raw in _STABLE_BASE_TYPES else _DEFAULT_BASE_TYPE


def _coerce_int(value: Any, *, default: int = 0) -> int:
    """Normalizes loosely-typed numeric fields."""

    try:
        return int(value)
    except Exception:
        return int(default)


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    """Normalizes loosely-typed boolean fields."""

    if isinstance(value, bool):
        return value
    raw = _normalize_key(value)
    if not raw:
        return bool(default)
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


def _safe_profile_component(value: Any) -> str:
    """Builds a stable id-safe component from a visible taxonomy value."""

    raw = _normalize_key(value)
    raw = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "_", raw).strip("_")
    return raw or "default"


def _load_yaml_like(text: str, *, source: str) -> Dict[str, Any]:
    """Loads a YAML-like config using PyYAML when available, otherwise JSON."""

    try:
        import yaml  # type: ignore

        payload = yaml.safe_load(text)
    except Exception:
        payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError(f"skill taxonomy at {source} must decode into an object")
    return {str(key): value for key, value in payload.items()}


def _read_builtin_taxonomy(name: str) -> Dict[str, Any]:
    """Reads one built-in taxonomy resource."""

    resource_name = f"{str(name or '').strip()}.yaml"
    package = resources.files("AutoSkill4Doc.skill_taxonomies")
    path = package.joinpath(resource_name)
    if not path.is_file():
        raise FileNotFoundError(resource_name)
    return _load_yaml_like(path.read_text(encoding="utf-8"), source=resource_name)


def _read_taxonomy_path(path: str) -> Dict[str, Any]:
    """Reads one user-provided taxonomy file."""

    src = os.path.abspath(os.path.expanduser(str(path or "").strip()))
    with open(src, "r", encoding="utf-8") as f:
        return _load_yaml_like(f.read(), source=src)


def _merge_taxonomy_payloads(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Merges a base taxonomy with one overlay by base_type."""

    merged = dict(base or {})
    for key in ("taxonomy_id", "domain_type", "display_name", "default_base_type", "family_axis", "default_family_name"):
        value = str(overlay.get(key) or "").strip()
        if value:
            merged[key] = value
    if "domain_root" in base or "domain_root" in overlay:
        merged["domain_root"] = {
            **dict(base.get("domain_root") or {}),
            **dict(overlay.get("domain_root") or {}),
        }

    asset_map: Dict[str, Dict[str, Any]] = {}
    for item in list(base.get("asset_types") or []):
        if isinstance(item, dict):
            normalized = _coerce_base_type(item.get("base_type"))
            asset_map[normalized] = {**item, "base_type": normalized}
    for item in list(overlay.get("asset_types") or []):
        if not isinstance(item, dict):
            continue
        normalized = _coerce_base_type(item.get("base_type"))
        asset_map[normalized] = {**asset_map.get(normalized, {}), **item, "base_type": normalized}

    ordered: List[Dict[str, Any]] = []
    seen = set()
    for base_type in _STABLE_BASE_TYPES:
        if base_type in asset_map:
            ordered.append(asset_map[base_type])
            seen.add(base_type)
    for base_type, payload in asset_map.items():
        if base_type not in seen:
            ordered.append(payload)
    merged["asset_types"] = ordered
    if "family_candidates" in base or "family_candidates" in overlay:
        merged["family_candidates"] = [item for item in list(base.get("family_candidates") or []) if isinstance(item, dict)]
        overlay_candidates = [item for item in list(overlay.get("family_candidates") or []) if isinstance(item, dict)]
        if overlay_candidates:
            merged["family_candidates"] = overlay_candidates
    visible_levels = dict(base.get("visible_levels") or {})
    overlay_levels = dict(overlay.get("visible_levels") or {})
    if visible_levels or overlay_levels:
        merged_levels = dict(visible_levels)
        level_labels = dict(visible_levels.get("level_labels") or {})
        level_labels.update({str(key): str(value) for key, value in dict(overlay_levels.get("level_labels") or {}).items() if str(value or "").strip()})
        merged_levels.update({key: value for key, value in overlay_levels.items() if key != "level_labels" and str(value or "").strip()})
        merged_levels["level_labels"] = level_labels
        merged["visible_levels"] = merged_levels
    if "asset_tree" in base or "asset_tree" in overlay:
        merged["asset_tree"] = [item for item in list(base.get("asset_tree") or []) if isinstance(item, dict)]
        overlay_tree = [item for item in list(overlay.get("asset_tree") or []) if isinstance(item, dict)]
        if overlay_tree:
            merged["asset_tree"] = overlay_tree
    return merged


@dataclass
class TaxonomyAssetType:
    """One domain-specific label mapping onto an internal stable asset type."""

    base_type: str
    label: str = ""
    description: str = ""
    aliases: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Normalizes taxonomy type fields."""

        self.base_type = _coerce_base_type(self.base_type)
        self.label = str(self.label or "").strip() or self.base_type
        self.description = str(self.description or "").strip()
        aliases = [self.base_type, self.label, *list(self.aliases or [])]
        deduped: List[str] = []
        seen = set()
        for alias in aliases:
            value = str(alias or "").strip()
            if not value:
                continue
            key = _normalize_key(value)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(value)
        self.aliases = deduped

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaxonomyAssetType":
        """Builds one taxonomy asset type from plain data."""

        return cls(
            base_type=str(data.get("base_type") or "").strip(),
            label=str(data.get("label") or "").strip(),
            description=str(data.get("description") or "").strip(),
            aliases=_coerce_str_list(data.get("aliases")),
        )


@dataclass
class TaxonomyAssetNode:
    """One hierarchical skill-node definition within a taxonomy tree."""

    node_id: str
    label_zh: str = ""
    label_en: str = ""
    base_type: str = _DEFAULT_BASE_TYPE
    level: int = 0
    parent: str = ""
    visible_role: str = "leaf"
    allowed_children: List[str] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)
    default_for_base_type: bool = False
    extractable: bool = True
    synthesized: bool = False

    def __post_init__(self) -> None:
        """Normalizes node fields and derived aliases."""

        self.node_id = str(self.node_id or "").strip()
        self.label_zh = str(self.label_zh or "").strip()
        self.label_en = str(self.label_en or "").strip()
        self.base_type = _coerce_base_type(self.base_type)
        self.level = max(0, _coerce_int(self.level, default=0))
        self.parent = str(self.parent or "").strip()
        raw_role = _normalize_key(self.visible_role)
        self.visible_role = raw_role if raw_role in _VISIBLE_ROLES else "leaf"
        self.allowed_children = dedupe_strings(_coerce_str_list(self.allowed_children), lower=True)
        self.aliases = dedupe_strings(
            [
                *(_coerce_str_list(self.aliases)),
                self.node_id,
                self.label_zh,
                self.label_en,
            ],
            lower=True,
        )
        self.default_for_base_type = _coerce_bool(self.default_for_base_type, default=False)
        self.extractable = _coerce_bool(self.extractable, default=True)
        self.synthesized = _coerce_bool(self.synthesized, default=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaxonomyAssetNode":
        """Builds one asset-tree node from plain data."""

        return cls(
            node_id=str(data.get("id") or data.get("node_id") or "").strip(),
            label_zh=str(data.get("label_zh") or "").strip(),
            label_en=str(data.get("label_en") or "").strip(),
            base_type=str(data.get("base_type") or "").strip(),
            level=_coerce_int(data.get("level"), default=0),
            parent=str(data.get("parent") or "").strip(),
            visible_role=str(data.get("visible_role") or "").strip(),
            allowed_children=_coerce_str_list(data.get("allowed_children")),
            aliases=_coerce_str_list(data.get("aliases")),
            default_for_base_type=_coerce_bool(data.get("default_for_base_type"), default=False),
            extractable=_coerce_bool(data.get("extractable"), default=True),
            synthesized=_coerce_bool(data.get("synthesized"), default=False),
        )

    def matches(self, value: Any) -> bool:
        """Checks whether one user/model value resolves to this node."""

        raw = _normalize_key(value)
        if not raw:
            return False
        return raw in {_normalize_key(alias) for alias in list(self.aliases or [])}


@dataclass
class SkillTaxonomy:
    """Loaded skill taxonomy used to guide extraction and normalize aliases."""

    taxonomy_id: str
    domain_type: str
    display_name: str = ""
    default_base_type: str = _DEFAULT_BASE_TYPE
    asset_types: List[TaxonomyAssetType] = field(default_factory=list)
    family_axis: str = ""
    default_family_name: str = ""
    family_candidates: List[Dict[str, Any]] = field(default_factory=list)
    domain_root: Dict[str, str] = field(default_factory=dict)
    visible_levels: Dict[str, Any] = field(default_factory=dict)
    asset_tree: List[TaxonomyAssetNode] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Normalizes taxonomy metadata and asset mappings."""

        self.taxonomy_id = str(self.taxonomy_id or "").strip() or "default"
        self.domain_type = str(self.domain_type or "").strip() or self.taxonomy_id
        self.display_name = str(self.display_name or "").strip() or self.taxonomy_id
        self.default_base_type = _coerce_base_type(self.default_base_type)
        self.asset_types = [
            item if isinstance(item, TaxonomyAssetType) else TaxonomyAssetType.from_dict(item)
            for item in list(self.asset_types or [])
        ]
        self.family_axis = str(self.family_axis or "").strip()
        self.default_family_name = str(self.default_family_name or "").strip()
        self.family_candidates = [
            {
                "id": str(item.get("id") or "").strip(),
                "name": str(item.get("name") or "").strip(),
                "visible_name": _preferred_family_visible_name(item),
                "aliases": _coerce_str_list(item.get("aliases")),
                "keywords": _coerce_str_list(item.get("keywords")),
            }
            for item in list(self.family_candidates or [])
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        raw_domain_root = dict(self.domain_root or {})
        self.domain_root = {
            "id": str(raw_domain_root.get("id") or self.taxonomy_id or self.domain_type or "domain").strip()
            or "domain",
            "name": (
                str(raw_domain_root.get("name") or "").strip()
                or str(raw_domain_root.get("name_zh") or "").strip()
                or str(raw_domain_root.get("display_name") or "").strip()
                or self.display_name
                or self.taxonomy_id
            ),
            "name_zh": str(raw_domain_root.get("name_zh") or raw_domain_root.get("name") or "").strip(),
            "name_en": str(raw_domain_root.get("name_en") or raw_domain_root.get("display_name") or "").strip(),
        }
        if not self.asset_types:
            self.asset_types = [TaxonomyAssetType(base_type=base_type) for base_type in _STABLE_BASE_TYPES]
        self.visible_levels = self._normalize_visible_levels(self.visible_levels)
        self.asset_tree = [
            item if isinstance(item, TaxonomyAssetNode) else TaxonomyAssetNode.from_dict(item)
            for item in list(self.asset_tree or [])
        ]
        if not self.asset_tree:
            self.asset_tree = self._build_fallback_asset_tree()
        self.asset_tree = self._normalize_asset_tree_relationships(self.asset_tree)

    @property
    def alias_map(self) -> Dict[str, str]:
        """Builds a normalized alias -> base type map."""

        mapping: Dict[str, str] = {}
        for item in self.asset_types:
            for alias in item.aliases:
                mapping[_normalize_key(alias)] = item.base_type
        return mapping

    @property
    def asset_node_map(self) -> Dict[str, TaxonomyAssetNode]:
        """Builds one node-id -> node lookup for the hierarchical asset tree."""

        out: Dict[str, TaxonomyAssetNode] = {}
        for item in list(self.asset_tree or []):
            key = str(item.node_id or "").strip()
            if key:
                out[key] = item
        return out

    def _normalize_visible_levels(self, value: Any) -> Dict[str, Any]:
        """Normalizes visible level labels for synthetic tree rendering."""

        payload = dict(value or {})
        level_labels = {
            str(key): str(label).strip()
            for key, label in dict(payload.get("level_labels") or {}).items()
            if str(label or "").strip()
        }
        merged = {
            "root_label": str(payload.get("root_label") or _DEFAULT_VISIBLE_LEVELS["root_label"]).strip()
            or _DEFAULT_VISIBLE_LEVELS["root_label"],
            "family_bucket_label": str(
                payload.get("family_bucket_label") or _DEFAULT_VISIBLE_LEVELS["family_bucket_label"]
            ).strip()
            or _DEFAULT_VISIBLE_LEVELS["family_bucket_label"],
            "level_labels": {
                **dict(_DEFAULT_VISIBLE_LEVELS["level_labels"]),
                **level_labels,
            },
        }
        return merged

    def _build_fallback_asset_tree(self) -> List[TaxonomyAssetNode]:
        """Builds a minimal hierarchical asset tree when the config omits one."""

        return [
            TaxonomyAssetNode(
                node_id="family_root",
                label_zh=self.visible_root_label(),
                label_en="Family Root",
                base_type="macro_protocol",
                level=0,
                visible_role="root",
                allowed_children=["macro_skill", "workflow_skill", "safety_rule_node", "knowledge_reference_node"],
                extractable=False,
                synthesized=True,
            ),
            TaxonomyAssetNode(
                node_id="macro_skill",
                label_zh=self.visible_level_label(1),
                label_en="First-Level Skill",
                base_type="macro_protocol",
                level=1,
                parent="family_root",
                visible_role="parent",
                default_for_base_type=True,
            ),
            TaxonomyAssetNode(
                node_id="workflow_skill",
                label_zh=self.visible_level_label(2),
                label_en="Second-Level Skill",
                base_type="session_skill",
                level=2,
                parent="macro_skill",
                visible_role="parent",
                default_for_base_type=True,
            ),
            TaxonomyAssetNode(
                node_id="micro_skill_node",
                label_zh=self.visible_level_label(3),
                label_en="Micro Skill",
                base_type="micro_skill",
                level=3,
                parent="workflow_skill",
                visible_role="leaf",
                default_for_base_type=True,
            ),
            TaxonomyAssetNode(
                node_id="safety_rule_node",
                label_zh=self.visible_level_label(2),
                label_en="Safety Skill",
                base_type="safety_rule",
                level=2,
                parent="family_root",
                visible_role="leaf",
                default_for_base_type=True,
            ),
            TaxonomyAssetNode(
                node_id="knowledge_reference_node",
                label_zh=self.visible_level_label(1),
                label_en="Reference Skill",
                base_type="knowledge_reference",
                level=1,
                parent="family_root",
                visible_role="leaf",
                default_for_base_type=True,
            ),
        ]

    def _normalize_asset_tree_relationships(self, nodes: Sequence[TaxonomyAssetNode]) -> List[TaxonomyAssetNode]:
        """Normalizes parent/child references so configured trees stay self-consistent."""

        deduped: List[TaxonomyAssetNode] = []
        seen: Set[str] = set()
        for item in list(nodes or []):
            key = str(getattr(item, "node_id", "") or "").strip()
            if not key or key in seen:
                continue
            deduped.append(item)
            seen.add(key)

        def _resolve_node_id(raw: Any) -> str:
            for candidate in list(deduped or []):
                if candidate.matches(raw):
                    return candidate.node_id
            return ""

        for item in deduped:
            normalized_children: List[str] = []
            for raw_child in list(item.allowed_children or []):
                resolved = _resolve_node_id(raw_child)
                if resolved and resolved != item.node_id:
                    normalized_children.append(resolved)
            item.allowed_children = dedupe_strings(normalized_children, lower=True)

        node_map = {item.node_id: item for item in deduped}
        for item in deduped:
            parent_id = _resolve_node_id(item.parent)
            item.parent = parent_id
            if not parent_id:
                continue
            parent = node_map.get(parent_id)
            if parent is None:
                continue
            if item.node_id not in list(parent.allowed_children or []):
                parent.allowed_children = dedupe_strings(list(parent.allowed_children or []) + [item.node_id], lower=True)
        return deduped

    def normalize_asset_type(self, value: Any) -> str:
        """Maps a domain-specific label or alias to an internal stable asset type."""

        raw = _normalize_key(value)
        if not raw:
            return self.default_base_type
        return self.alias_map.get(raw, _coerce_base_type(raw))

    def strict_normalize_asset_type(self, value: Any) -> str:
        """Maps one configured asset label to a stable type, rejecting unknown non-empty values."""

        raw = _normalize_key(value)
        if not raw:
            return self.default_base_type
        if raw in self.alias_map:
            return self.alias_map[raw]
        if raw in _STABLE_BASE_TYPES:
            return raw
        return ""

    def normalize_asset_node_id(self, value: Any) -> str:
        """Maps one node id/alias back to a canonical configured asset node id."""

        raw = _normalize_key(value)
        if not raw:
            return ""
        for node in list(self.asset_tree or []):
            if node.matches(raw):
                return node.node_id
        return ""

    def get_asset_node(self, node_id: str) -> Optional[TaxonomyAssetNode]:
        """Returns one configured asset node by canonical id."""

        return self.asset_node_map.get(str(node_id or "").strip())

    def default_asset_node_for_base_type(self, base_type: Any) -> Optional[TaxonomyAssetNode]:
        """Returns the configured default node for one stable base asset type."""

        normalized = self.normalize_asset_type(base_type)
        preferred = [
            node
            for node in list(self.asset_tree or [])
            if node.base_type == normalized and node.default_for_base_type and node.extractable
        ]
        if preferred:
            return sorted(preferred, key=lambda item: (item.level, item.node_id))[0]
        fallback = [
            node
            for node in list(self.asset_tree or [])
            if node.base_type == normalized and node.extractable
        ]
        if fallback:
            return sorted(fallback, key=lambda item: (item.level, item.node_id))[0]
        return None

    def resolve_asset_node(
        self,
        *,
        requested: Any = "",
        asset_type: Any = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[TaxonomyAssetNode]:
        """Resolves one extract/compile skill into a configured asset tree node."""

        md = dict(metadata or {})
        for candidate in (
            requested,
            md.get("asset_node_id"),
            md.get("asset_node"),
            md.get("node_id"),
        ):
            node_id = self.normalize_asset_node_id(candidate)
            if node_id:
                return self.get_asset_node(node_id)
        return self.default_asset_node_for_base_type(asset_type)

    def asset_path_ids(self, node_id: Any) -> List[str]:
        """Returns the canonical ancestry path ids for one node."""

        current = self.get_asset_node(str(node_id or "").strip())
        if current is None:
            return []
        out: List[str] = []
        seen = set()
        while current is not None:
            key = str(current.node_id or "").strip()
            if not key or key in seen:
                break
            seen.add(key)
            out.append(key)
            current = self.get_asset_node(current.parent)
        out.reverse()
        return out

    def asset_path(self, node_id: Any) -> str:
        """Returns a slash-joined canonical path for one node."""

        return "/".join(self.asset_path_ids(node_id))

    def visible_root_label(self) -> str:
        """Returns the configured root label for the visible tree."""

        return str((self.visible_levels or {}).get("root_label") or _DEFAULT_VISIBLE_LEVELS["root_label"]).strip()

    def family_bucket_label(self) -> str:
        """Returns the configured family container label under one domain root."""

        return str(
            (self.visible_levels or {}).get("family_bucket_label") or _DEFAULT_VISIBLE_LEVELS["family_bucket_label"]
        ).strip()

    def domain_root_name(self) -> str:
        """Returns the configured visible domain root name."""

        return (
            str((self.domain_root or {}).get("name_zh") or "").strip()
            or str((self.domain_root or {}).get("name") or "").strip()
            or str((self.domain_root or {}).get("name_en") or "").strip()
            or self.display_name
            or self.taxonomy_id
        )

    def domain_root_id(self) -> str:
        """Returns the configured stable domain root id."""

        return str((self.domain_root or {}).get("id") or self.taxonomy_id or self.domain_type or "domain").strip() or "domain"

    def resolve_family_candidate(self, *, requested: str = "", metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Resolves one explicit family id/name/alias to a canonical configured candidate."""

        md = dict(metadata or {})
        candidates = list(self.family_candidates or [])
        for candidate_value in (
            str(requested or "").strip(),
            str(md.get("family_id") or "").strip(),
            str(md.get("family_name") or "").strip(),
            str(md.get("school_name") or "").strip(),
        ):
            raw = _normalize_key(candidate_value)
            if not raw:
                continue
            for item in candidates:
                aliases = [
                    str(item.get("id") or "").strip(),
                    str(item.get("name") or "").strip(),
                    *list(item.get("aliases") or []),
                ]
                if raw in {_normalize_key(alias) for alias in aliases if str(alias or "").strip()}:
                    return dict(item)
        return None

    def visible_level_label(self, level: int) -> str:
        """Returns one configured visible label for the given level."""

        labels = dict((self.visible_levels or {}).get("level_labels") or {})
        return str(labels.get(str(int(level or 0))) or f"Level {int(level or 0)}").strip()

    def prompt_guidance(self) -> str:
        """Renders concise prompt guidance for document extraction."""

        lines = [
            f"Domain type is externally provided as `{self.domain_type}`.",
            "Do not infer or output domain_type.",
            "Return asset_type using ONLY the internal base types: "
            "macro_protocol | session_skill | micro_skill | safety_rule | knowledge_reference.",
        ]
        pretty_lines: List[str] = []
        for item in self.asset_types:
            alias_text = ", ".join([alias for alias in item.aliases if _normalize_key(alias) != _normalize_key(item.base_type)])
            detail = f"- {item.label} -> {item.base_type}"
            if item.description:
                detail += f": {item.description}"
            if alias_text:
                detail += f" (aliases: {alias_text})"
            pretty_lines.append(detail)
        if pretty_lines:
            lines.append("Domain-specific labels and aliases:")
            lines.extend(pretty_lines)
        if self.family_candidates:
            lines.append("Configured family candidates:")
            for item in self.family_candidates:
                alias_text = ", ".join(list(item.get("aliases") or []))
                detail = f"- {str(item.get('name') or '').strip()}"
                if alias_text:
                    detail += f" (aliases: {alias_text})"
                lines.append(detail)
        if self.asset_tree:
            lines.append("Configured hierarchy nodes:")
            lines.append("Return asset_node_id when the excerpt strongly maps to one configured node; otherwise omit it.")
            for node in list(self.asset_tree or []):
                detail = (
                    f"- {node.node_id} -> {node.base_type} "
                    f"(level={node.level}, role={node.visible_role}, parent={node.parent or 'null'})"
                )
                if node.label_zh or node.label_en:
                    detail += f" [{node.label_zh or ''}{' / ' if node.label_zh and node.label_en else ''}{node.label_en or ''}]"
                if node.default_for_base_type:
                    detail += " default"
                if not node.extractable:
                    detail += " synthesized-only"
                lines.append(detail)
        return "\n".join(lines)

    def resolve_family_name(self, *, requested: str = "", metadata: Optional[Dict[str, Any]] = None) -> str:
        """Resolves the visible family name with request and metadata precedence."""

        md = dict(metadata or {})
        candidate = self.ensure_configured_family_candidate(requested=requested, metadata=md)
        if candidate is not None:
            return str(candidate.get("visible_name") or candidate.get("name") or "").strip()
        for candidate in (
            str(requested or "").strip(),
            str(md.get("family_name") or "").strip(),
            str(md.get("school_name") or "").strip(),
            self.default_family_name,
        ):
            if candidate:
                return candidate
        return ""

    def ensure_configured_family_candidate(self, *, requested: str = "", metadata: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Ensures one explicit family belongs to configured family_candidates when they exist."""

        md = dict(metadata or {})
        explicit = (
            str(requested or "").strip()
            or str(md.get("family_name") or "").strip()
            or str(md.get("school_name") or "").strip()
        )
        candidate = self.resolve_family_candidate(requested=requested, metadata=md)
        if candidate is not None:
            return candidate
        if explicit and self.family_candidates:
            choices = [
                str(item.get("visible_name") or item.get("name") or item.get("id") or "").strip()
                for item in list(self.family_candidates or [])
                if str(item.get("visible_name") or item.get("name") or item.get("id") or "").strip()
            ]
            raise ValueError(
                f"family_name '{explicit}' is not in configured family_candidates: {', '.join(choices)}"
            )
        return None

    def resolve_axis_label(self, *, requested: str = "") -> str:
        """Resolves the visible axis label for manifests and tags."""

        return str(requested or "").strip() or self.family_axis

    def derive_profile_id(self, *, requested: str = "", family_name: str = "") -> str:
        """Builds a stable profile id when the caller does not provide one."""

        explicit = str(requested or "").strip()
        if explicit:
            return explicit
        family = _safe_profile_component(family_name or self.default_family_name or "default")
        taxonomy = _safe_profile_component(self.taxonomy_id or self.domain_type or "default")
        return f"{taxonomy}::{family}"

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the taxonomy to plain data."""

        return {
            "taxonomy_id": self.taxonomy_id,
            "domain_type": self.domain_type,
            "display_name": self.display_name,
            "default_base_type": self.default_base_type,
            "family_axis": self.family_axis,
            "default_family_name": self.default_family_name,
            "domain_root": dict(self.domain_root or {}),
            "visible_levels": {
                "root_label": self.visible_root_label(),
                "family_bucket_label": self.family_bucket_label(),
                "level_labels": dict((self.visible_levels or {}).get("level_labels") or {}),
            },
            "family_candidates": [
                {
                    "id": str(item.get("id") or "").strip(),
                    "name": str(item.get("name") or "").strip(),
                    "visible_name": str(item.get("visible_name") or "").strip(),
                    "aliases": list(item.get("aliases") or []),
                    "keywords": list(item.get("keywords") or []),
                }
                for item in self.family_candidates
            ],
            "asset_types": [
                {
                    "base_type": item.base_type,
                    "label": item.label,
                    "description": item.description,
                    "aliases": list(item.aliases or []),
                }
                for item in self.asset_types
            ],
            "asset_tree": [
                {
                    "id": item.node_id,
                    "label_zh": item.label_zh,
                    "label_en": item.label_en,
                    "base_type": item.base_type,
                    "level": item.level,
                    "parent": item.parent,
                    "visible_role": item.visible_role,
                    "allowed_children": list(item.allowed_children or []),
                    "aliases": list(item.aliases or []),
                    "default_for_base_type": item.default_for_base_type,
                    "extractable": item.extractable,
                    "synthesized": item.synthesized,
                }
                for item in self.asset_tree
            ],
        }


def list_builtin_skill_taxonomies() -> List[str]:
    """Lists built-in taxonomy ids packaged with AutoSkill4Doc."""

    package = resources.files("AutoSkill4Doc.skill_taxonomies")
    names: List[str] = []
    for item in package.iterdir():
        if item.is_file() and item.name.endswith(".yaml"):
            names.append(os.path.splitext(item.name)[0])
    return sorted(set(names))


def load_skill_taxonomy(*, domain_type: str = "", taxonomy_path: str = "") -> SkillTaxonomy:
    """Loads a default taxonomy plus optional built-in or file override."""

    base = _read_builtin_taxonomy("default")
    overlay: Dict[str, Any] = {}
    domain_key = str(domain_type or "").strip()
    path = str(taxonomy_path or "").strip()
    if path:
        overlay = _read_taxonomy_path(path)
    elif domain_key and domain_key.lower() != "default":
        try:
            overlay = _read_builtin_taxonomy(domain_key)
        except FileNotFoundError:
            overlay = {}

    merged = _merge_taxonomy_payloads(base, overlay)
    if domain_key:
        merged["domain_type"] = domain_key
        if not str(overlay.get("taxonomy_id") or "").strip():
            merged["taxonomy_id"] = domain_key
    return SkillTaxonomy(
        taxonomy_id=str(merged.get("taxonomy_id") or "default").strip() or "default",
        domain_type=str(merged.get("domain_type") or domain_key or "default").strip() or "default",
        display_name=str(merged.get("display_name") or "").strip(),
        default_base_type=str(merged.get("default_base_type") or _DEFAULT_BASE_TYPE).strip(),
        family_axis=str(merged.get("family_axis") or "").strip(),
        default_family_name=str(merged.get("default_family_name") or "").strip(),
        family_candidates=[item for item in list(merged.get("family_candidates") or []) if isinstance(item, dict)],
        domain_root=dict(merged.get("domain_root") or {}),
        visible_levels=dict(merged.get("visible_levels") or {}),
        asset_types=[
            TaxonomyAssetType.from_dict(item)
            for item in list(merged.get("asset_types") or [])
            if isinstance(item, dict)
        ],
        asset_tree=[
            TaxonomyAssetNode.from_dict(item)
            for item in list(merged.get("asset_tree") or [])
            if isinstance(item, dict)
        ],
    )
