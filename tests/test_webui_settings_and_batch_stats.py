import asyncio
from contextlib import contextmanager

from src.web.routes import settings as settings_routes
from src.web.routes import registration
from src.core.register import RegistrationCancelled


class DummyRequest:
    def __init__(self, access_password=None, host=None, port=None, debug=None):
        self.access_password = access_password
        self.host = host
        self.port = port
        self.debug = debug


class DummyTask:
    def __init__(self, status, error_message=""):
        self.status = status
        self.error_message = error_message


def test_update_webui_settings_rotates_secret_key(monkeypatch):
    captured = {}

    def fake_update_settings(**kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(settings_routes, "update_settings", fake_update_settings)

    request = DummyRequest(access_password="admin123")
    result = asyncio.run(settings_routes.update_webui_settings(request))

    assert result["success"] is True
    assert captured["webui_access_password"] == "admin123"
    assert isinstance(captured["webui_secret_key"], str)
    assert len(captured["webui_secret_key"]) >= 32


def test_batch_parallel_counts_cancelled_as_failed(monkeypatch):
    batch_id = "batch-1"
    task_uuids = ["task-1"]
    fake_task = DummyTask(status="cancelled", error_message="")

    @contextmanager
    def fake_get_db():
        yield object()

    def fake_get_registration_task(db, task_uuid):
        return fake_task

    async def fake_run_registration_task(*args, **kwargs):
        return None

    monkeypatch.setattr(registration, "get_db", fake_get_db)
    monkeypatch.setattr(registration.crud, "get_registration_task", fake_get_registration_task)
    monkeypatch.setattr(registration, "run_registration_task", fake_run_registration_task)
    monkeypatch.setattr(registration.task_manager, "is_batch_cancelled", lambda _: False)

    asyncio.run(
        registration.run_batch_parallel(
            batch_id=batch_id,
            task_uuids=task_uuids,
            email_service_type="tempmail",
            proxy=None,
            email_service_config=None,
            email_service_id=None,
            concurrency=1,
        )
    )

    state = registration.batch_tasks[batch_id]
    assert state["success"] == 0
    assert state["failed"] == 1
    assert state["completed"] == 1


def test_batch_pipeline_counts_cancelled_as_failed(monkeypatch):
    batch_id = "batch-2"
    task_uuids = ["task-2"]
    fake_task = DummyTask(status="cancelled", error_message="")

    @contextmanager
    def fake_get_db():
        yield object()

    def fake_get_registration_task(db, task_uuid):
        return fake_task

    async def fake_run_registration_task(*args, **kwargs):
        return None

    monkeypatch.setattr(registration, "get_db", fake_get_db)
    monkeypatch.setattr(registration.crud, "get_registration_task", fake_get_registration_task)
    monkeypatch.setattr(registration, "run_registration_task", fake_run_registration_task)
    monkeypatch.setattr(registration.task_manager, "is_batch_cancelled", lambda _: False)

    asyncio.run(
        registration.run_batch_pipeline(
            batch_id=batch_id,
            task_uuids=task_uuids,
            email_service_type="tempmail",
            proxy=None,
            email_service_config=None,
            email_service_id=None,
            interval_min=0,
            interval_max=0,
            concurrency=1,
        )
    )

    state = registration.batch_tasks[batch_id]
    assert state["success"] == 0
    assert state["failed"] == 1
    assert state["completed"] == 1


def test_cancel_batch_marks_pending_child_tasks(monkeypatch):
    batch_id = "batch-cancel"
    registration.batch_tasks[batch_id] = {
        "task_uuids": ["task-a", "task-b"],
        "finished": False,
        "cancelled": False,
    }

    tasks = {
        "task-a": DummyTask(status="pending"),
        "task-b": DummyTask(status="running"),
    }
    updates = []
    cancelled = []

    @contextmanager
    def fake_get_db():
        yield object()

    def fake_get_registration_task(db, task_uuid):
        return tasks[task_uuid]

    def fake_update_registration_task(db, task_uuid, **kwargs):
        updates.append((task_uuid, kwargs))
        task = tasks[task_uuid]
        for key, value in kwargs.items():
            setattr(task, key, value)
        return task

    monkeypatch.setattr(registration, "get_db", fake_get_db)
    monkeypatch.setattr(registration.crud, "get_registration_task", fake_get_registration_task)
    monkeypatch.setattr(registration.crud, "update_registration_task", fake_update_registration_task)
    monkeypatch.setattr(registration.task_manager, "cancel_batch", lambda _: None)
    monkeypatch.setattr(registration.task_manager, "cancel_task", lambda task_uuid: cancelled.append(task_uuid))
    monkeypatch.setattr(registration.task_manager, "update_status", lambda *args, **kwargs: None)

    result = asyncio.run(registration.cancel_batch(batch_id))

    assert result["success"] is True
    assert cancelled == ["task-a", "task-b"]
    assert any(task_uuid == "task-a" and kwargs["status"] == "cancelled" for task_uuid, kwargs in updates)
    assert not any(task_uuid == "task-b" and kwargs["status"] == "cancelled" for task_uuid, kwargs in updates)


def test_stop_batch_due_to_luckmail_no_stock_cancels_pending_tasks(monkeypatch):
    batch_id = "batch-no-stock"
    registration.batch_tasks[batch_id] = {
        "task_uuids": ["task-a", "task-b"],
        "finished": False,
        "cancelled": False,
        "logs": [],
    }

    tasks = {
        "task-a": DummyTask(status="pending"),
        "task-b": DummyTask(status="running"),
    }
    cancelled = []
    status_updates = []
    updates = []
    batch_logs = []

    @contextmanager
    def fake_get_db():
        yield object()

    def fake_get_registration_task(db, task_uuid):
        return tasks[task_uuid]

    def fake_update_registration_task(db, task_uuid, **kwargs):
        updates.append((task_uuid, kwargs))
        task = tasks[task_uuid]
        for key, value in kwargs.items():
            setattr(task, key, value)
        return task

    monkeypatch.setattr(registration, "get_db", fake_get_db)
    monkeypatch.setattr(registration.crud, "get_registration_task", fake_get_registration_task)
    monkeypatch.setattr(registration.crud, "update_registration_task", fake_update_registration_task)
    monkeypatch.setattr(registration.task_manager, "cancel_batch", lambda current_batch_id: cancelled.append(("batch", current_batch_id)))
    monkeypatch.setattr(registration.task_manager, "cancel_task", lambda task_uuid: cancelled.append(("task", task_uuid)))
    monkeypatch.setattr(registration.task_manager, "update_batch_status", lambda *args, **kwargs: status_updates.append((args, kwargs)))
    monkeypatch.setattr(registration.task_manager, "add_batch_log", lambda current_batch_id, message: batch_logs.append((current_batch_id, message)))

    registration._stop_batch_due_to_luckmail_no_stock(batch_id, "key=batch-no-stock")

    assert registration.batch_tasks[batch_id]["cancelled"] is True
    assert registration.batch_tasks[batch_id]["stop_reason"] == "key=batch-no-stock"
    assert ("batch", batch_id) in cancelled
    assert ("task", "task-a") in cancelled
    assert ("task", "task-b") in cancelled
    assert any(task_uuid == "task-a" and kwargs["status"] == "cancelled" for task_uuid, kwargs in updates)
    assert batch_logs and "[邮箱预热] LuckMail 连续无库存，当前批次已停止" in batch_logs[0][1]
    assert status_updates and status_updates[0][1]["status"] == "cancelling"


def test_get_batch_status_includes_incremental_logs():
    batch_id = "batch-logs"
    registration.batch_tasks[batch_id] = {
        "total": 3,
        "completed": 1,
        "success": 1,
        "failed": 0,
        "current_index": 1,
        "cancelled": False,
        "finished": False,
        "logs": ["[系统] 启动", "[邮箱预热] LuckMail 批量预扫描完成"],
        "stop_reason": None,
    }

    result = asyncio.run(registration.get_batch_status(batch_id, cursor=1))

    assert result["logs"] == ["[邮箱预热] LuckMail 批量预扫描完成"]
    assert result["next_cursor"] == 2


def test_run_sync_registration_task_marks_cancelled_on_cooperative_stop(monkeypatch):
    updates = []
    statuses = []
    logs = []

    @contextmanager
    def fake_get_db():
        yield object()

    def fake_update_registration_task(db, task_uuid, **kwargs):
        updates.append((task_uuid, kwargs))
        return DummyTask(status=kwargs.get("status", "pending"), error_message=kwargs.get("error_message", ""))

    monkeypatch.setattr(registration, "get_db", fake_get_db)
    monkeypatch.setattr(registration.crud, "update_registration_task", fake_update_registration_task)
    monkeypatch.setattr(registration.task_manager, "is_cancelled", lambda _: True)
    monkeypatch.setattr(registration.task_manager, "update_status", lambda *args, **kwargs: statuses.append((args, kwargs)))
    monkeypatch.setattr(registration.task_manager, "add_log", lambda task_uuid, message: logs.append((task_uuid, message)))

    registration._run_sync_registration_task(
        task_uuid="task-x",
        email_service_type="tempmail",
        proxy=None,
        email_service_config=None,
    )

    assert any(kwargs.get("status") == "cancelled" for _, kwargs in updates)
    assert any(args[1] == "cancelled" for args, _ in statuses)
    assert any("[取消]" in message for _, message in logs)


def test_run_registration_task_returns_early_when_already_cancelled(monkeypatch):
    statuses = []
    logs = []

    monkeypatch.setattr(registration.task_manager, "is_cancelled", lambda _: True)
    monkeypatch.setattr(registration.task_manager, "update_status", lambda *args, **kwargs: statuses.append((args, kwargs)))
    monkeypatch.setattr(registration.task_manager, "add_log", lambda task_uuid, message: logs.append((task_uuid, message)))

    asyncio.run(
        registration.run_registration_task(
            task_uuid="task-y",
            email_service_type="tempmail",
            proxy=None,
            email_service_config=None,
        )
    )

    assert any(args[1] == "cancelled" for args, _ in statuses)
    assert any("任务已取消" in message for _, message in logs)


def test_registration_engine_reports_cancelled_result(monkeypatch):
    engine = registration.RegistrationEngine(
        email_service=type("EmailService", (), {"service_type": type("SvcType", (), {"value": "tempmail"})()})(),
        cancel_checker=lambda: True,
    )

    monkeypatch.setattr(engine, "_check_ip_location", lambda: (True, "US"))

    result = engine.run()

    assert result.success is False
    assert result.error_message == "任务已取消"




def test_batch_parallel_stops_launching_new_tasks_after_cancel(monkeypatch):
    batch_id = "batch-stop"
    task_uuids = ["task-1", "task-2", "task-3", "task-4"]
    started = []
    state = {"cancelled": False}

    @contextmanager
    def fake_get_db():
        yield object()

    def fake_get_registration_task(db, task_uuid):
        return DummyTask(status="cancelled" if task_uuid in started else "pending", error_message="任务已取消")

    async def fake_run_registration_task(task_uuid, *args, **kwargs):
        started.append(task_uuid)
        if len(started) == 1:
            state["cancelled"] = True
        return None

    monkeypatch.setattr(registration, "get_db", fake_get_db)
    monkeypatch.setattr(registration.crud, "get_registration_task", fake_get_registration_task)
    monkeypatch.setattr(registration, "run_registration_task", fake_run_registration_task)
    monkeypatch.setattr(registration.task_manager, "is_batch_cancelled", lambda _: state["cancelled"])
    monkeypatch.setattr(registration.task_manager, "update_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(registration.crud, "update_registration_task", lambda *args, **kwargs: DummyTask(status=kwargs.get("status", "cancelled"), error_message=kwargs.get("error_message", "")))

    asyncio.run(
        registration.run_batch_parallel(
            batch_id=batch_id,
            task_uuids=task_uuids,
            email_service_type="tempmail",
            proxy=None,
            email_service_config=None,
            email_service_id=None,
            concurrency=3,
        )
    )

    assert started == ["task-1"]
    assert registration.batch_tasks[batch_id]["finished"] is True
