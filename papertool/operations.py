import json
import os
import shutil
from datetime import datetime
from typing import List, Dict, Optional


class Operation:
    def __init__(self, op_type: str, details: dict, timestamp: str = None):
        self.op_type = op_type
        self.details = details
        self.timestamp = timestamp or datetime.now().isoformat(timespec="seconds")

    def to_dict(self) -> dict:
        return {
            "op_type": self.op_type,
            "details": self.details,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Operation":
        return cls(
            op_type=data["op_type"],
            details=data["details"],
            timestamp=data.get("timestamp"),
        )


class OperationLog:
    def __init__(self, log_dir: str):
        self.log_dir = log_dir
        self.log_file = os.path.join(log_dir, "operations.json")
        self.operations: List[Operation] = []
        self._load()

    def _load(self) -> None:
        if os.path.exists(self.log_file):
            try:
                with open(self.log_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.operations = [Operation.from_dict(op) for op in data]
            except (json.JSONDecodeError, IOError):
                self.operations = []

    def _save(self) -> None:
        os.makedirs(self.log_dir, exist_ok=True)
        with open(self.log_file, "w", encoding="utf-8") as f:
            json.dump(
                [op.to_dict() for op in self.operations],
                f,
                ensure_ascii=False,
                indent=2,
            )

    def add_operation(self, op_type: str, details: dict) -> None:
        op = Operation(op_type, details)
        self.operations.append(op)
        self._save()

    def add_batch_operations(self, ops: List[tuple]) -> None:
        for op_type, details in ops:
            self.operations.append(Operation(op_type, details))
        self._save()

    def get_last_batch(self, batch_size: int = None) -> List[Operation]:
        if batch_size:
            return self.operations[-batch_size:]
        return list(self.operations)

    def get_recent(self, count: int = 10) -> List[Operation]:
        return self.operations[-count:] if self.operations else []

    def clear(self) -> None:
        self.operations = []
        self._save()


class RollbackManager:
    def __init__(self, log_dir: str):
        self.log = OperationLog(log_dir)
        self.backup_dir = os.path.join(log_dir, "backups")

    def record_rename(self, old_path: str, new_path: str) -> None:
        self.log.add_operation(
            "rename",
            {"old_path": old_path, "new_path": new_path},
        )

    def record_move(self, src: str, dst: str) -> None:
        self.log.add_operation(
            "move",
            {"source": src, "destination": dst},
        )

    def record_metadata_update(self, file_path: str, old_meta: dict, new_meta: dict) -> None:
        self.log.add_operation(
            "metadata_update",
            {
                "file_path": file_path,
                "old_metadata": old_meta,
                "new_metadata": new_meta,
            },
        )

    def rollback_last(self, count: int = 1) -> Dict[str, list]:
        results = {"success": [], "failed": []}
        recent_ops = list(reversed(self.log.operations))

        ops_to_rollback = recent_ops[:count] if count < len(recent_ops) else recent_ops

        for op in ops_to_rollback:
            try:
                if op.op_type == "rename":
                    self._rollback_rename(op.details)
                    results["success"].append(f"回滚重命名: {op.details['new_path']} -> {op.details['old_path']}")
                elif op.op_type == "move":
                    self._rollback_move(op.details)
                    results["success"].append(f"回滚移动: {op.details['destination']} -> {op.details['source']}")
                elif op.op_type == "metadata_update":
                    results["success"].append(f"回滚元数据: {op.details['file_path']}")
            except Exception as e:
                results["failed"].append(f"回滚失败 ({op.op_type}): {str(e)}")

        if count < len(self.log.operations):
            self.log.operations = self.log.operations[:-count]
        else:
            self.log.operations = []
        self.log._save()

        return results

    def _rollback_rename(self, details: dict) -> None:
        old_path = details["old_path"]
        new_path = details["new_path"]
        if os.path.exists(new_path):
            os.makedirs(os.path.dirname(old_path), exist_ok=True)
            os.rename(new_path, old_path)

    def _rollback_move(self, details: dict) -> None:
        src = details["source"]
        dst = details["destination"]
        if os.path.exists(dst):
            os.makedirs(os.path.dirname(src), exist_ok=True)
            shutil.move(dst, src)

    def get_history(self, count: int = 10) -> List[dict]:
        ops = self.log.get_recent(count)
        return [op.to_dict() for op in ops]
