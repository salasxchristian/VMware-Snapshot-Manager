# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for pySnap - VMware Snapshot Manager
macOS version (Universal binary for Intel + Apple Silicon)
"""

import os
import sys

# Import version dynamically
sys.path.insert(0, os.path.dirname(os.path.abspath(SPEC)))
from version import __version__

block_cipher = None

# Get the directory containing this spec file
spec_dir = os.path.dirname(os.path.abspath(SPEC))

a = Analysis(
    ['vmware_snapshot_manager.py'],
    pathex=[spec_dir],
    binaries=[],
    datas=[
        ('icons', 'icons'),  # Include entire icons directory
        ('snapshot_filters.py', '.'),  # Include the filters module
        ('version.py', '.'),  # Include version file
    ],
    hiddenimports=[
        'keyring.backends.macOS',
        'keyring.backends.OS_X',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
        'PyQt6.sip',
        'pyVmomi',
        'pyVim',
        'pyVim.connect',
        'urllib3',
        'urllib3.exceptions',
        'ssl',
        'logging.handlers',
        'getpass',
        'json',
        're',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',  # Not needed for PyQt app
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
        'sqlite3',
        'test',
        'xmlrpc',
        'distutils',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='pySnap',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Don't show console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='universal2',  # Build for both Intel and Apple Silicon
    codesign_identity=None,  # Will be signed in build script
    entitlements_file='entitlements.plist' if os.path.exists('entitlements.plist') else None,
    icon='icons/app_icon.icns',
)

app = BUNDLE(
    exe,
    name='pySnap.app',
    icon='icons/app_icon.icns',
    bundle_identifier='net.lausd.pysnap',
    info_plist={
        'CFBundleName': 'pySnap',
        'CFBundleDisplayName': 'pySnap - VMware Snapshot Manager',
        'CFBundleIdentifier': 'net.lausd.pysnap',
        'CFBundleVersion': __version__,
        'CFBundleShortVersionString': __version__,
        'CFBundleExecutable': 'pySnap',
        'CFBundleIconFile': 'app_icon.icns',
        'CFBundlePackageType': 'APPL',
        'CFBundleSignature': 'PSNP',
        'LSMinimumSystemVersion': '10.14.0',
        'LSApplicationCategoryType': 'public.app-category.utilities',
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,  # Support dark mode
        'NSHumanReadableCopyright': 'Copyright © 2024 LAUSD. All rights reserved.',
        'NSPrincipalClass': 'NSApplication',
        'NSAppleScriptEnabled': False,
        'LSBackgroundOnly': False,
        # Permissions
        'NSAppleEventsUsageDescription': 'This app needs to send Apple events to other apps.',
        # Network access is implicit, no special key needed
        # Keychain access is handled by entitlements
    },
    # Additional options for better macOS integration
    version=__version__,
)

# Create a DMG configuration (optional, for reference)
# This would be used with create-dmg or similar tools
dmg_settings = {
    'title': 'pySnap Installer',
    'icon': 'icons/app_icon.icns',
    'background': None,  # Could add a background image
    'window_rect': ((100, 100), (600, 400)),
    'icon_locations': {
        'pySnap.app': (150, 200),
        'Applications': (450, 200)
    },
    'format': 'UDZO',  # Compressed
}