# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.building.datastruct import TOC

block_cipher = None


a = Analysis(
    ['ui/app.py'],
    pathex=[],
    binaries=[
        ('E:/etheriaZd/game-ai-assistant/venv/Lib/site-packages/pythonnet/runtime/Python.Runtime.dll', 'pythonnet/runtime'),
        # certifi SSL 证书（EasyOCR 下载模型时验证 HTTPS 需要）
        ('E:/etheriaZd/game-ai-assistant/venv/Lib/site-packages/certifi/cacert.pem', 'certifi'),
    ],
    datas=[
        ('ui/static', 'ui/static'),
        ('templates', 'templates'),
        ('easyocr_models', 'easyocr_models'),
        ('.env', '.'),
        ('app.ico', '.'),
    ],
    hiddenimports=[
        'webview',
        'webview.platforms.winforms',
        'webview.platforms.edgechromium',
        'PIL',
        'cv2',
        'numpy',
        'psutil',
        'win32gui',
        'win32con',
        'win32process',
        'win32api',
        'mss',
        'pyautogui',
        'pynput',
        'easyocr',
        'torch',
        'core._base',
        'core._common',
        'core.daily',
        'core.events',
        'core.rta',
        'http.server',
    ],
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'pandas',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# 剔掉 PyInstaller 自动收集的系统 DLL。这些必须由 Windows 从 System32 加载，
# 打包进去会导致 DLL 版本不匹配 → c10.dll 的 DllMain 初始化失败。
_SYS_DLLS = {
    'ucrtbase.dll',
    'vcruntime140.dll',
    'vcruntime140_1.dll',
    'msvcp140.dll',
    'concrt140.dll',
    'vccorlib140.dll',
}
a.binaries = TOC([
    (n, p, t) for (n, p, t) in a.binaries
    if n.lower() not in _SYS_DLLS and not n.lower().startswith('api-ms-win-crt-')
])

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='瑞玛丽小助手',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=['torch', 'c10', 'fbgemm', 'asmjit', 'libiomp', 'shm', 'uv', 'torch_cpu'],
    name='瑞玛丽小助手',
)
