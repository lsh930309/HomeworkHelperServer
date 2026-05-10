from src.core import notifier


def test_notifier_imports_and_falls_back_when_toaster_unavailable(monkeypatch):
    class FailingToaster:
        def __init__(self, _application_name):
            raise RuntimeError("not available")

    monkeypatch.setattr(notifier, "InteractableWindowsToaster", FailingToaster)

    received = []
    n = notifier.Notifier("HomeworkHelper", main_window_activated_callback=lambda task_id, source: received.append((task_id, source)))

    assert n.toaster is None
    n.send_notification("제목", "내용", task_id_to_highlight="game-a")
    n.signal_bridge.on_notification_callback(notifier.ToastActivatedEventArgs("task_id=game-a&source=body"))
    assert received == [("game-a", "body")]

