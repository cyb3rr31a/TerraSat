"""Load and validate audit profiles (YAML files in this folder)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field

PROFILE_DIR = Path(__file__).resolve().parent


class ClassSpec(BaseModel):
    prompts: list[str] = Field(min_length=1)
    color: str = "#FFFFFF"
    min_area_m2: float = 0.0
    max_area_m2: float = float("inf")


class AuditDefaults(BaseModel):
    side_m: float = 2100
    zoom: int = 18


class MemoSpec(BaseModel):
    framing: str = ""
    sections: list[str] = []
    languages: list[str] = ["en"]


class Profile(BaseModel):
    id: str
    name: str
    tagline: str = ""
    status: Literal["case_study", "beta", "planned"] = "beta"
    audience: str = ""
    audit: AuditDefaults = AuditDefaults()
    classes: dict[str, ClassSpec]
    layers: list[str] = []
    analyzer: str
    params: dict = {}
    memo: MemoSpec = MemoSpec()

    def sam_classes(self) -> dict[str, dict]:
        """Class config in the plain-dict shape sam_service expects."""
        return {k: v.model_dump() for k, v in self.classes.items()}


@lru_cache(maxsize=None)
def load_profile(profile_id: str) -> Profile:
    path = PROFILE_DIR / f"{profile_id}.yaml"
    if not path.exists():
        raise KeyError(f"Unknown profile {profile_id!r}. Available: {list_profile_ids()}")
    return Profile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def list_profile_ids() -> list[str]:
    return sorted(p.stem for p in PROFILE_DIR.glob("*.yaml"))


def list_profiles() -> list[Profile]:
    return [load_profile(i) for i in list_profile_ids()]
