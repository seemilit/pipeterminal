# Windows 便携包

这两个入口可单独执行，不需要先打包另一个版本，也不制作安装器。

| 版本 | 双击脚本 | 打包内容 |
| --- | --- | --- |
| 免费版 | 公共项目的 `build_free.bat` | 公共程序与 `basic` 模块 |
| 付费版 | 私有项目的 `build_paid.bat` | 公共程序、`basic` 与私有 `premium` 模块 |

付费版需要两个源码项目并排放置：

```text
工作目录/
├── pipeterminal/
│   └── build_free.bat
└── pipeterminal-private/
    └── build_paid.bat
```

免费版不依赖私有项目。私有项目目前没有实际付费功能，付费包先提供统一启动和模块发现入口。

## 执行方式

在 Windows 上双击对应 `.bat`，等待窗口显示成功和输出路径。也可以在命令行中单独运行。

脚本优先使用项目自身或工作目录的 `.venv\Scripts\python.exe`，其次使用 `py -3` 或 `python`。需要 Python 3.10 及以上，建议沿用 Python 3.12；如需指定解释器，设置环境变量 `PIPETERMINAL_BUILD_PYTHON` 为解释器的完整路径。

首次执行需要联网安装依赖。两个版本各自使用所在项目的 `build/packaging/.venv`，不会向开发用 `.venv` 或全局 Python 安装打包依赖。

## 输出

输出在对应项目的 `dist` 下，每次使用新的时间戳目录，例如：

```text
dist/
├── PipeTerminal-Free-20261011-120000/
│   ├── PipeTerminal-Free.exe
│   └── _internal/
└── PipeTerminal-Free-20261011-120000.zip
```

付费版名称为 `PipeTerminal-Paid`。解压 ZIP 后，直接双击目录内的 `.exe`，目标电脑无需安装 Python。分发时必须保留整个目录，不能只复制 `.exe`。

本地 `conf`、服务器凭据、日志、历史版本、测试、旧 `ssh` 项目和开发虚拟环境均不复制进包。首次保存设置或数据时，程序在 `.exe` 同级的 `conf` 下创建自己的数据；请解压到可写目录。再次打包生成新目录，保留旧包中的数据。

## 打包逻辑

共用 `packaging/build.py`，使用 PyInstaller 的 `onedir` 模式。只安装应用声明的 `PySide6-Essentials` 等依赖，不安装完整 Qt Addons；明确排除 QtWebEngine、QtWebChannel，打包后也检查这些组件是否意外出现。Pillow 仅用于构建阶段把项目 PNG 图标转换为 Windows ICO。

动态功能包通过 `--collect-submodules` 收集，非 Python 资源通过 `--collect-data` 收集。PyInstaller 自带的 `pkgutil` 运行时支持保持现有 `ModuleLoader` 启动发现机制，无需在 MainWindow 中写模块名称。后续功能资源应放在各自的 package 内。

私有启动入口向公共 `bootstrap.run(module_packages=...)` 提供要加载的包名；公共代码不导入 `premium`。新增私有依赖写入私有项目的 `requirements.txt`，新增功能继续使用 `premium/功能名/module.py` 和 `get_module()` 规范。

参考：[PyInstaller 打包参数](https://www.pyinstaller.org/en/stable/usage.html)、[冻结包的 pkgutil 支持](https://github.com/pyinstaller/pyinstaller/blob/develop/PyInstaller/hooks/rthooks/pyi_rth_pkgutil.py)。
