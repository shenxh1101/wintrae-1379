import json
import os
import shutil
import uuid
from datetime import datetime
from typing import List, Dict, Optional


class Operation:
    def __init__(self, op_type: str, details: dict, timestamp: str = None,
                 batch_id: str = None, description: str = None):
        self.op_type = op_type
        self.details = details
        self.timestamp = timestamp or datetime.now().isoformat(timespec="seconds")
        self.batch_id = batch_id
        self.description = description

    def to_dict(self) -> dict:
        return {
            "op_type": self.op_type,
            "details": self.details,
            "timestamp": self.timestamp,
            "batch_id": self.batch_id,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Operation":
        return cls(
            op_type=data["op_type"],
            details=data["details"],
            timestamp=data.get("timestamp"),
            batch_id=data.get("batch_id"),
            description=data.get("description"),
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

    def _new_batch_id(self) -> str:
        return uuid.uuid4().hex[:8]

    def add_operation(self, op_type: str, details: dict,
                      batch_id: str = None, description: str = None) -> None:
        op = Operation(op_type, details, batch_id=batch_id, description=description)
        self.operations.append(op)
        self._save()

    def add_batch_operations(self, ops: List[tuple],
                             batch_id: str = None, description: str = None) -> str:
        if batch_id is None:
            batch_id = self._new_batch_id()
        for op_type, details in ops:
            self.operations.append(
                Operation(op_type, details, batch_id=batch_id, description=description)
            )
        self._save()
        return batch_id

    def start_batch(self, description: str = None) -> str:
        return self._new_batch_id()

    def get_last_batch(self, batch_size: int = None) -> List[Operation]:
        if batch_size:
            return self.operations[-batch_size:]
        return list(self.operations)

    def get_recent(self, count: int = 10) -> List[Operation]:
        return self.operations[-count:] if self.operations else []

    def get_last_batch_ops(self) -> Optional[List[Operation]]:
        if not self.operations:
            return None
        last_batch_id = self.operations[-1].batch_id
        if last_batch_id is None:
            return [self.operations[-1]]
        batch = []
        for op in reversed(self.operations):
            if op.batch_id == last_batch_id:
                batch.append(op)
            else:
                break
        return list(reversed(batch))

    def get_batches(self, count: int = 10) -> List[dict]:
        batches = []
        current_batch_id = None
        current_batch = []

        for op in reversed(self.operations):
            bid = op.batch_id
            if bid != current_batch_id:
                if current_batch:
                    batches.append({
                        "batch_id": current_batch_id,
                        "description": current_batch[0].description,
                        "timestamp": current_batch[0].timestamp,
                        "operations": list(reversed(current_batch)),
                    })
                    if len(batches) >= count:
                        break
                current_batch_id = bid
                current_batch = [op]
            else:
                current_batch.append(op)

        if current_batch and len(batches) < count:
            batches.append({
                "batch_id": current_batch_id,
                "description": current_batch[0].description,
                "timestamp": current_batch[0].timestamp,
                "operations": list(reversed(current_batch)),
            })

        return batches

    def get_ops_by_batch(self, batch_id: str) -> List[Operation]:
        return [op for op in self.operations if op.batch_id == batch_id]

    def remove_batch(self, batch_id: str) -> int:
        n_before = len(self.operations)
        self.operations = [op for op in self.operations if op.batch_id != batch_id]
        removed = n_before - len(self.operations)
        self._save()
        return removed

    def clear(self) -> None:
        self.operations = []
        self._save()


class RollbackManager:
    def __init__(self, log_dir: str):
        self.log = OperationLog(log_dir)
        self.backup_dir = os.path.join(log_dir, "backups")
        self._current_batch_id = None
        self._current_batch_desc = None

    def start_batch(self, description: str = None) -> str:
        self._current_batch_id = self.log.start_batch(description)
        self._current_batch_desc = description
        return self._current_batch_id

    def end_batch(self) -> Optional[str]:
        bid = self._current_batch_id
        self._current_batch_id = None
        self._current_batch_desc = None
        return bid

    def record_rename(self, old_path: str, new_path: str) -> None:
        self.log.add_operation(
            "rename",
            {"old_path": old_path, "new_path": new_path},
            batch_id=self._current_batch_id,
            description=self._current_batch_desc,
        )

    def record_move(self, src: str, dst: str) -> None:
        self.log.add_operation(
            "move",
            {"source": src, "destination": dst},
            batch_id=self._current_batch_id,
            description=self._current_batch_desc,
        )

    def record_metadata_update(self, file_path: str, old_meta: dict, new_meta: dict) -> None:
        self.log.add_operation(
            "metadata_update",
            {
                "file_path": file_path,
                "old_metadata": old_meta,
                "new_metadata": new_meta,
            },
            batch_id=self._current_batch_id,
            description=self._current_batch_desc,
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

    def rollback_last_batch(self) -> Dict[str, list]:
        batch_ops = self.log.get_last_batch_ops()
        if not batch_ops:
            return {"success": [], "failed": ["没有可回滚的批次"]}

        batch_id = batch_ops[0].batch_id
        results = {"success": [], "failed": [], "batch_id": batch_id,
                   "description": batch_ops[0].description, "count": len(batch_ops)}

        for op in reversed(batch_ops):
            try:
                if op.op_type == "rename":
                    self._rollback_rename(op.details)
                    results["success"].append(
                        f"回滚重命名: {os.path.basename(op.details['new_path'])} "
                        f"→ {os.path.basename(op.details['old_path'])}"
                    )
                elif op.op_type == "move":
                    self._rollback_move(op.details)
                    results["success"].append(
                        f"回滚移动: {os.path.basename(op.details['destination'])} "
                        f"→ {os.path.basename(op.details['source'])}"
                    )
                elif op.op_type == "metadata_update":
                    results["success"].append(
                        f"回滚元数据: {os.path.basename(op.details['file_path'])}"
                    )
            except Exception as e:
                results["failed"].append(f"回滚失败 ({op.op_type}): {str(e)}")

        if batch_id:
            self.log.remove_batch(batch_id)
        else:
            n = len(batch_ops)
            self.log.operations = self.log.operations[:-n]
            self.log._save()

        return results

    def rollback_batch(self, batch_id: str) -> Dict[str, list]:
        batch_ops = self.log.get_ops_by_batch(batch_id)
        if not batch_ops:
            return {"success": [], "failed": [f"未找到批次 {batch_id}"]}

        results = {"success": [], "failed": [], "batch_id": batch_id,
                   "description": batch_ops[0].description, "count": len(batch_ops)}

        for op in reversed(batch_ops):
            try:
                if op.op_type == "rename":
                    self._rollback_rename(op.details)
                    results["success"].append(
                        f"回滚重命名: {os.path.basename(op.details['new_path'])} "
                        f"→ {os.path.basename(op.details['old_path'])}"
                    )
                elif op.op_type == "move":
                    self._rollback_move(op.details)
                    results["success"].append(
                        f"回滚移动: {os.path.basename(op.details['destination'])} "
                        f"→ {os.path.basename(op.details['source'])}"
                    )
                elif op.op_type == "metadata_update":
                    results["success"].append(
                        f"回滚元数据: {os.path.basename(op.details['file_path'])}"
                    )
            except Exception as e:
                results["failed"].append(f"回滚失败 ({op.op_type}): {str(e)}")

        self.log.remove_batch(batch_id)
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

    def get_batches(self, count: int = 10) -> List[dict]:
        return self.log.get_batches(count)
