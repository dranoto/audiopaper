"""
SQLite-backed task queue for background processing.

This provides a simple queue system without requiring Redis or external dependencies.
"""

import json
import threading
import time
import uuid
from typing import Optional, Callable, List, Dict, Any
from datetime import datetime, timedelta
from enum import Enum

from database import db, Task


class TaskStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETE = "complete"
    ERROR = "error"
    RETRYING = "retrying"


class TaskQueue:
    """
    SQLite-backed task queue with priority support and retry logic.

    Features:
    - Priority-based ordering (lower = higher priority)
    - Automatic retry with exponential backoff
    - Task dependencies (chain tasks together)
    - Max concurrent workers
    """

    _instance = None
    _lock = threading.Lock()

    def __init__(self, max_workers: int = 3, max_retries: int = 3):
        self.max_workers = max_workers
        self.max_retries = max_retries
        self._workers: List[threading.Thread] = []
        self._running = False
        self._task_handlers: Dict[str, Callable] = {}

    @classmethod
    def get_instance(cls, max_workers: int = 3) -> "TaskQueue":
        """Get singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(max_workers=max_workers)
        return cls._instance

    def register_handler(self, task_type: str, handler: Callable):
        """Register a handler function for a task type."""
        self._task_handlers[task_type] = handler

    def enqueue(
        self,
        task_type: str,
        file_id: int,
        priority: int = 5,
        metadata: Optional[Dict[str, Any]] = None,
        depends_on: Optional[str] = None,
    ) -> str:
        """
        Add a task to the queue.

        Args:
            task_type: Type of task (e.g., 'summary', 'transcript', 'podcast')
            file_id: ID of the file to process
            priority: Lower number = higher priority (default 5)
            metadata: Additional task data
            depends_on: Task ID this task depends on

        Returns:
            task_id: UUID of the created task
        """
        task_id = str(uuid.uuid4())

        task = Task(
            id=task_id,
            status=TaskStatus.PENDING if not depends_on else TaskStatus.PENDING,
            result=json.dumps(
                {
                    "task_type": task_type,
                    "file_id": file_id,
                    "priority": priority,
                    "metadata": metadata or {},
                    "depends_on": depends_on,
                    "attempts": 0,
                    "max_attempts": self.max_retries,
                    "created_at": datetime.utcnow().isoformat(),
                }
            ),
        )

        db.session.add(task)
        db.session.commit()

        return task_id

    def enqueue_chain(self, tasks: List[Dict]) -> List[str]:
        """
        Enqueue a chain of dependent tasks.

        Args:
            tasks: List of task dicts with 'task_type', 'file_id', 'priority', 'metadata'

        Returns:
            List of task IDs in order
        """
        task_ids = []
        previous_task_id = None

        for task in tasks:
            task_id = self.enqueue(
                task_type=task["task_type"],
                file_id=task["file_id"],
                priority=task.get("priority", 5),
                metadata=task.get("metadata"),
                depends_on=previous_task_id,
            )
            task_ids.append(task_id)
            previous_task_id = task_id

        return task_ids

    def get_next_task(self) -> Optional[Task]:
        """Get the next pending task (highest priority, oldest)."""
        # Find tasks that aren't blocked by dependencies
        pending_tasks = (
            Task.query.filter(Task.status.in_([TaskStatus.PENDING, TaskStatus.QUEUED]))
            .order_by(Task.status, Task.result.desc())
            .all()
        )

        for task in pending_tasks:
            task_data = json.loads(task.result)

            # Check if dependencies are met
            depends_on = task_data.get("depends_on")
            if depends_on:
                dep_task = Task.query.get(depends_on)
                if dep_task and dep_task.status == TaskStatus.COMPLETE:
                    return task
                elif dep_task and dep_task.status == TaskStatus.ERROR:
                    # Dependency failed, mark this as error too
                    task.status = TaskStatus.ERROR
                    task.result = json.dumps(
                        {**task_data, "error": f"Dependency {depends_on} failed"}
                    )
                    db.session.commit()
                    continue
            else:
                # No dependency
                return task

        return None

    def process_task(self, task: Task, app) -> bool:
        """Process a single task."""
        task_data = json.loads(task.result)
        task_type = task_data.get("task_type")

        # Get handler
        handler = self._task_handlers.get(task_type)
        if not handler:
            task.status = TaskStatus.ERROR
            task.result = json.dumps(
                {**task_data, "error": f"No handler for task type: {task_type}"}
            )
            db.session.commit()
            return False

        # Mark as processing
        task.status = TaskStatus.PROCESSING
        task.result = json.dumps(
            {
                **task_data,
                "attempts": task_data.get("attempts", 0) + 1,
                "started_at": datetime.utcnow().isoformat(),
            }
        )
        db.session.commit()

        try:
            # Execute handler
            handler(app, task.id, task_data["file_id"])

            # Check if successful by looking at task status
            db.session.refresh(task)
            if task.status == TaskStatus.PROCESSING:
                task.status = TaskStatus.COMPLETE
                task.result = json.dumps(
                    {**task_data, "completed_at": datetime.utcnow().isoformat()}
                )
                db.session.commit()

            return task.status == TaskStatus.COMPLETE

        except Exception as e:
            db.session.rollback()

            attempts = task_data.get("attempts", 0)
            max_attempts = task_data.get("max_attempts", self.max_retries)

            if attempts < max_attempts:
                # Schedule retry with exponential backoff
                task.status = TaskStatus.RETRYING
                delay = min(2**attempts * 60, 3600)  # Max 1 hour
                task.result = json.dumps(
                    {
                        **task_data,
                        "attempts": attempts,
                        "retry_at": (
                            datetime.utcnow() + timedelta(seconds=delay)
                        ).isoformat(),
                        "last_error": str(e),
                    }
                )
            else:
                task.status = TaskStatus.ERROR
                task.result = json.dumps(
                    {
                        **task_data,
                        "error": str(e),
                        "failed_at": datetime.utcnow().isoformat(),
                    }
                )

            db.session.commit()
            return False

    def retry_task(self, task_id: str) -> bool:
        """Manually retry a failed task."""
        task = Task.query.get(task_id)
        if not task:
            return False

        task_data = json.loads(task.result)
        task.status = TaskStatus.PENDING
        task.result = json.dumps({**task_data, "attempts": 0, "retry_reason": "manual"})
        db.session.commit()
        return True

    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """Get status of a task."""
        task = Task.query.get(task_id)
        if not task:
            return None

        task_data = json.loads(task.result) if task.result else {}

        return {
            "id": task.id,
            "status": task.status,
            "task_type": task_data.get("task_type"),
            "file_id": task_data.get("file_id"),
            "attempts": task_data.get("attempts", 0),
            "max_attempts": task_data.get("max_attempts", self.max_retries),
            "error": task_data.get("error"),
            "created_at": task_data.get("created_at"),
            "completed_at": task_data.get("completed_at"),
        }

    def get_all_tasks(self, file_id: Optional[int] = None) -> List[Dict]:
        """Get all tasks, optionally filtered by file_id."""
        query = Task.query

        if file_id is not None:
            # Filter by file_id in result JSON
            all_tasks = query.all()
            tasks = []
            for task in all_tasks:
                task_data = json.loads(task.result) if task.result else {}
                if task_data.get("file_id") == file_id:
                    tasks.append(task)
            tasks.sort(
                key=lambda t: json.loads(t.result).get("created_at", ""), reverse=True
            )
        else:
            tasks = query.order_by(Task.id.desc()).limit(100).all()

        result = []
        for task in tasks:
            task_data = json.loads(task.result) if task.result else {}
            result.append(
                {
                    "id": task.id,
                    "status": task.status,
                    "task_type": task_data.get("task_type"),
                    "file_id": task_data.get("file_id"),
                    "attempts": task_data.get("attempts", 0),
                    "max_attempts": task_data.get("max_attempts", self.max_retries),
                    "error": task_data.get("error"),
                    "created_at": task_data.get("created_at"),
                }
            )

        return result

    def get_batch_status(self, batch_id: str) -> Dict:
        """Get status of a batch of tasks."""
        all_tasks = Task.query.all()

        tasks = [
            t
            for t in all_tasks
            if json.loads(t.result or "{}").get("batch_id") == batch_id
        ]

        if not tasks:
            return {
                "total": 0,
                "complete": 0,
                "error": 0,
                "processing": 0,
                "pending": 0,
                "tasks": [],
            }

        status_counts = {
            "total": len(tasks),
            "complete": 0,
            "error": 0,
            "processing": 0,
            "pending": 0,
        }

        tasks_data = []
        for task in tasks:
            task_data = json.loads(task.result) if task.result else {}
            if task.status == TaskStatus.COMPLETE:
                status_counts["complete"] += 1
            elif task.status == TaskStatus.ERROR:
                status_counts["error"] += 1
            elif task.status == TaskStatus.PROCESSING:
                status_counts["processing"] += 1
            else:
                status_counts["pending"] += 1

            tasks_data.append(
                {
                    "id": task.id,
                    "status": task.status,
                    "file_id": task_data.get("file_id"),
                    "error": task_data.get("error"),
                    "attempts": task_data.get("attempts", 0),
                }
            )

        status_counts["tasks"] = tasks_data

        return status_counts

    def start_workers(self, app, num_workers: Optional[int] = None):
        """Start background worker threads."""
        if self._running:
            return

        self._running = True
        num_workers = num_workers or self.max_workers

        for i in range(num_workers):
            worker = threading.Thread(
                target=self._worker_loop, args=(app, i), daemon=True
            )
            worker.start()
            self._workers.append(worker)

    def stop_workers(self):
        """Stop all worker threads."""
        self._running = False
        for worker in self._workers:
            worker.join(timeout=5)
        self._workers.clear()

    def _worker_loop(self, app, worker_id: int):
        """Main worker loop."""
        while self._running:
            try:
                with app.app_context():
                    # Get next task
                    task = self.get_next_task()

                    if task:
                        # Mark as queued
                        task.status = TaskStatus.QUEUED
                        db.session.commit()

                        # Process it
                        self.process_task(task, app)
                    else:
                        # No work, sleep briefly
                        time.sleep(1)

            except Exception as e:
                print(f"Worker {worker_id} error: {e}")
                time.sleep(5)


# Singleton accessor
def get_task_queue() -> TaskQueue:
    """Get the task queue instance."""
    return TaskQueue.get_instance()
