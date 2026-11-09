"""Native terminal drawing component without a standalone navigation page."""

from common.modules.descriptor import ModuleDescriptor


def get_module() -> ModuleDescriptor:
    return ModuleDescriptor(id="terminal", name="终端", sidebar=False)
