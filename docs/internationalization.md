# 国际化

默认语言为英语，支持英语、简体中文、繁体中文、日语、韩语和西班牙语。

## 文案和职责

- 公共界面及客户端错误文案放在 `common/i18n/messages.py`，应用加载功能前即可使用。
- 功能文案仍由各功能的 `translations.py` 和 `module.py` 注册。私有模块自己注册文案，公开代码不导入私有模块。
- `error_message(error)` 提供本地化错误摘要，保留服务器、操作系统及第三方库返回的原始诊断信息。
- 终端默认复制/粘贴菜单、程序生成的 SSH 提示、日志提示、历史版本和设置校验错误使用 `tr()`。
- `QTabWidget.insertTab()` 保存页签文案来源，动态插入的标签支持语言切换。
- 本地文件选择框使用 Qt 界面并跟随应用语言。免费与付费共用的打包脚本显式携带六份 `qtbase_*.qm`。

服务器输出、命令、文件内容、路径、IP、文件名、历史日志原文、协议标识及开发者构建工具输出保留原文。品牌名、技术标识和标准单位保留通用名称。

## 源码核对

静态合并公开与私有文案表：每种非源语言 438 个键；直接调用及模块名称 361 个键无缺译；占位符一致。解析了 155 个 Python 文件，无语法错误。只检查源码，未启动项目、运行测试、连接服务器或执行打包；运行时切换和打包验收尚未进行。

## 本次修改文件

- `pipeterminal-private/premium/directory_cache/module.py`
- `pipeterminal-private/premium/terminal_acceleration/module.py`
- `pipeterminal/app/bootstrap.py`
- `pipeterminal/app/main_window.py`
- `pipeterminal/basic/connection/store.py`
- `pipeterminal/basic/history/dialog.py`
- `pipeterminal/basic/history/store.py`
- `pipeterminal/basic/language/dialog.py`
- `pipeterminal/basic/log/page.py`
- `pipeterminal/basic/log/store.py`
- `pipeterminal/basic/log/writer.py`
- `pipeterminal/basic/monitor/controller.py`
- `pipeterminal/basic/monitor/process_actions.py`
- `pipeterminal/basic/settings/dialog.py`
- `pipeterminal/basic/sftp/controller.py`
- `pipeterminal/basic/sftp/editor/dialog.py`
- `pipeterminal/basic/sftp/file_operations/actions.py`
- `pipeterminal/basic/sftp/file_operations/controller.py`
- `pipeterminal/basic/shell/command_integration.py`
- `pipeterminal/basic/shell/commands.py`
- `pipeterminal/basic/shell/connector.py`
- `pipeterminal/basic/shell/host_keys.py`
- `pipeterminal/basic/shell/integration.py`
- `pipeterminal/basic/shell/module.py`
- `pipeterminal/basic/shell/page.py`
- `pipeterminal/basic/shell/path_navigation.py`
- `pipeterminal/basic/shell/session.py`
- `pipeterminal/basic/terminal/widget.py`
- `pipeterminal/basic/theme/dialog.py`
- `pipeterminal/basic/theme/manager.py`
- `pipeterminal/common/i18n/__init__.py`
- `pipeterminal/common/i18n/errors.py`
- `pipeterminal/common/i18n/manager.py`
- `pipeterminal/common/i18n/messages.py`
- `pipeterminal/common/i18n/widgets.py`
- `pipeterminal/common/licensing/manager.py`
- `pipeterminal/common/modules/descriptor.py`
- `pipeterminal/common/modules/loader.py`
- `pipeterminal/common/modules/registry.py`
- `pipeterminal/common/qt/bottom_panel.py`
- `pipeterminal/common/qt/directory_panel.py`
- `pipeterminal/common/qt/page_container.py`
- `pipeterminal/common/qt/sidebar.py`
- `pipeterminal/common/settings/store.py`
- `pipeterminal/packaging/build.py`

本说明文件为新增。Controller 的修改限于错误信息展示；Service、VO、Mapper、Impl 未修改。没有修改配置格式、授权判断、终端协议或远端文件操作规则。

