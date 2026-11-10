# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['declaracoes_escolares.py'],
    pathex=[],
    binaries=[],
    datas=[('icone_declaracoes.ico', '.')],
    hiddenimports=['reportlab.graphics.barcode.common', 'docx', 'frequencia_gier', 'gier_auto', 'gier_online', 'registro', 'estoque', 'tela_estoque', 'leitor_nota', 'pypdfium2', 'pypdfium2_raw', 'pdfplumber'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='DeclaracoesEscolares',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icone_declaracoes.ico'],
)
