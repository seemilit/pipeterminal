"""In-memory registry shared by public and extension modules."""

from .descriptor import ModuleDescriptor

from common.i18n import tr


class ModuleRegistry:
    def __init__(self, authorization=None) -> None:
        self.authorization = authorization
        self._modules: dict[str, ModuleDescriptor] = {}
        self._services: dict[str, object] = {}

    @property
    def has_paid_features(self) -> bool:
        return any(module.required_capabilities for module in self._modules.values())

    def register_service(self, service_id: str, service: object) -> None:
        if service_id in self._services:
            raise ValueError(tr("服务已注册：{0}", service_id))
        self._services[service_id] = service

    def get_service(self, service_id: str) -> object | None:
        descriptor = self._modules.get(service_id)
        if descriptor is not None and not self.is_available(descriptor):
            return None
        return self._services.get(service_id)

    def is_available(self, descriptor: ModuleDescriptor) -> bool:
        return not descriptor.required_capabilities or (
            self.authorization is not None and self.authorization.allows(descriptor.required_capabilities)
        )

    def register(self, descriptor: ModuleDescriptor) -> None:
        if descriptor.id in self._modules:
            raise ValueError(tr("模块已注册：{0}", descriptor.id))
        self._modules[descriptor.id] = descriptor

    def get(self, module_id: str) -> ModuleDescriptor:
        descriptor = self._modules[module_id]
        if not self.is_available(descriptor):
            raise KeyError(module_id)
        return descriptor

    def get_sidebar_modules(self) -> list[ModuleDescriptor]:
        return sorted(
            (module for module in self._modules.values() if module.sidebar and self.is_available(module)),
            key=lambda module: (module.order, module.id),
        )
