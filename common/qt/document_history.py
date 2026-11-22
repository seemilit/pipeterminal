"""Open and restore versions for an editor's current resource."""

from common.i18n import tr
from common.licensing.prompt import prompt_activation


def open_document_history(page, name, store, restore, *, preview=None):
    if name is None:
        return
    registry = page.registry
    service = registry.get_service("history")
    if service is None:
        prompt_activation(registry, page, tr("历史版本"))
        return
    if not page.can_leave():
        return

    resource = store.resource_id(name)
    store.ensure_history(name)
    options = {"preview": preview} if preview is not None else {}
    version_id = service.choose_version(resource, name, page.window(), **options)
    if version_id is None or registry.get_service("history") is not service:
        return
    version = service.read(resource, version_id)
    restore(name, version.content)
    if store.last_history_error is None:
        page.status_changed.emit(tr("已恢复历史版本：{0}", version.created_at))
