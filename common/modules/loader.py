"""Discover immediate feature packages once during startup."""

import importlib
import importlib.util
import pkgutil

from .descriptor import ModuleDescriptor
from .registry import ModuleRegistry

from common.i18n import tr


class ModuleLoader:
    def __init__(self, registry: ModuleRegistry) -> None:
        self._registry = registry
        self._loaded_packages: set[str] = set()

    def load(self, package_name: str) -> None:
        if package_name in self._loaded_packages:
            return
        package = importlib.import_module(package_name)
        discovered: list[ModuleDescriptor] = []
        for feature in sorted(
            pkgutil.iter_modules(package.__path__, prefix=f"{package.__name__}."),
            key=lambda feature: feature.name,
        ):
            if not feature.ispkg:
                continue
            entry_name = f"{feature.name}.module"
            if importlib.util.find_spec(entry_name) is None:
                continue
            entry = importlib.import_module(entry_name)
            descriptor = entry.get_module()
            if not isinstance(descriptor, ModuleDescriptor):
                raise TypeError(tr("{0}.get_module() 必须返回 ModuleDescriptor", entry_name))
            self._registry.register(descriptor)
            discovered.append(descriptor)
        for descriptor in discovered:
            if descriptor.service_factory is not None and self._registry.is_available(descriptor):
                service = descriptor.service_factory()
                bind_authorization = getattr(service, "bind_authorization", None)
                if callable(bind_authorization):
                    bind_authorization(self._registry.authorization, descriptor.required_capabilities)
                self._registry.register_service(descriptor.id, service)
        for descriptor in discovered:
            if descriptor.on_startup is not None:
                descriptor.on_startup()
        self._loaded_packages.add(package_name)
