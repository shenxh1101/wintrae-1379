import json
import os
from dataclasses import dataclass, field, asdict
from typing import List, Optional


READ_STATUS = ["unread", "reading", "read", "skimmed"]


@dataclass
class PaperMetadata:
    file_path: str
    title: Optional[str] = None
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    doi: Optional[str] = None
    journal: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    read_status: str = "unread"
    topic: Optional[str] = None
    file_size: int = 0
    file_hash: Optional[str] = None
    added_at: Optional[str] = None
    modified_at: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PaperMetadata":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class PaperDatabase:
    papers: dict = field(default_factory=dict)
    version: int = 1

    def add_paper(self, paper: PaperMetadata) -> None:
        self.papers[paper.file_path] = paper

    def get_paper(self, file_path: str) -> Optional[PaperMetadata]:
        return self.papers.get(file_path)

    def remove_paper(self, file_path: str) -> None:
        if file_path in self.papers:
            del self.papers[file_path]

    def all_papers(self) -> List[PaperMetadata]:
        return list(self.papers.values())

    def save(self, db_path: str) -> None:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        data = {
            "version": self.version,
            "papers": {k: v.to_dict() for k, v in self.papers.items()},
        }
        with open(db_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, db_path: str) -> "PaperDatabase":
        if not os.path.exists(db_path):
            return cls()
        try:
            with open(db_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            db = cls(version=data.get("version", 1))
            for k, v in data.get("papers", {}).items():
                db.papers[k] = PaperMetadata.from_dict(v)
            return db
        except (json.JSONDecodeError, IOError):
            return cls()
